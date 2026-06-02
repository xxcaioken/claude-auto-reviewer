---
title: Regras do prompt de Code Review
type: business-rules
status: active
tags:
  - backend
  - pattern
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[arquitetura]]"
  - "[[regras-negocio]]"
  - "[[runbook-atualizar-prompt]]"
  - "[[error-handling]]"
tier: 2
---

# Regras do prompt — `commands/code-review.md`

O prompt é o **coração** do sistema. Toda a inteligência do reviewer vive nele, não no `heartbeat.py`. Esta nota documenta as regras estritas que ele impõe e por quê. Mudanças aqui têm impacto direto na qualidade da revisão — ver [[runbook-atualizar-prompt]] pra processo de alteração.

## Identidade e contexto

> "Você é a personificação do subagente `/code-review`. Todo o comportamento, rigor técnico e inteligência de Code Review (CR) da nossa infraestrutura residem exclusivamente em você."

Isso seta a identidade — o Claude age como ferramenta autônoma, não como assistente conversacional. Reflete em:
- Sem saudações ("Olá! Vou revisar..."). 
- Sem reconfirmação ("Entendi, vou seguir as regras...").
- Sem auto-referência ("Como modelo de IA, eu..."). 

## Detecção de modo

Trigger: o prompt detecta pelo formato de `$ARGUMENTS`.

| Padrão | Modo | Comportamento |
|---|---|---|
| `/code-review <url> publique` | Heartbeat | Posta direto via `gh pr comment`. Retorna só "Publicado em <url>". |
| `/code-review PR-123 publique` | Heartbeat | Idem. |
| `/code-review` (sem args) | Interativo | Revisa arquivos modificados na branch atual. |
| `/code-review --staged` | Interativo | Revisa `git diff --cached`. |
| `/code-review --last-commit` | Interativo | Revisa `git diff HEAD~1 HEAD`. |
| `/code-review PR-123` (sem `publique`) | Interativo | Gera relatório, oferece via `AskUserQuestion`. |
| `/code-review <arquivo>` | Interativo | Revisa arquivo específico. |

Heartbeat sempre invoca a primeira forma. Modo interativo é uso dev manual.

## Regras estritas (modo Heartbeat)

Numeradas no prompt (`commands/code-review.md:33-41`):

1. **Adaptabilidade global**: identifica stack por extensão (`.py`, `.ts`, `.tsx`, `.go`, `.sql`, `.rs`). Ajusta análise. Não assume Python/TS/etc.
2. **Foco cirúrgico**: arquitetura, segurança, performance, bugs lógicos. Não outras coisas.
3. **Ignorar estilo**: zero feedback sobre formatação, espaços, quotes, ordem de imports. **Linter cuida.** Reduz ruído e respeita ferramentas existentes do repo.
4. **Tom profissional**: sem saudação, sem repetir o comando, sem confirmar regras.
5. **Postagem direta**: usa `gh pr comment <num> --repo <owner>/<repo> --body-file -` com heredoc/stdin. Retorna só `Publicado em <url-do-comentário>` — **não** repete o markdown.
6. **Marcador obrigatório**: primeira linha do corpo = `<!-- code-review-bot:v1 -->`. Sem isso, [[regras-negocio]] §2 quebra.

## Leitura do vault do repo-alvo (capability adicionada)

Decisão e tradeoffs em [[ADR-006-leitura-vault-repo-alvo]]. Resumo do que o prompt impõe:

- **Detectar `<REPO_PATH>/Claude/`** em cascata: (1) `path_local` do `repos.txt`; (2) `$HOME/code/<basename>/Claude/` — convenção NPU-Brain; (3) `./Claude/` no modo interativo.
- Se existe, **ler arquivos prioritários** antes da análise:
  1. `regras-negocio.md`
  2. `bugs-conhecidos.md`
  3. `ADR-*.md`
  4. `regras-*.md` (relevantes à área do diff)
  5. `arquitetura.md` + `arquitetura-banco.md` (só se a mudança toca camada estrutural)
- **Citar referências no comentário** quando aplicável:
  - Violação de regra → no mínimo 🟡 com link `[[Claude/regras-X]]`.
  - Contradição de ADR → 🔴 a menos que o PR proponha revisar.
  - Reintrodução de bug conhecido → 🔴 com `[[Claude/bugs-conhecidos]] §B-NNN`.
- **Sem vault → comportar como antes**, sem mencionar a ausência. Graceful degradation total.
- **Não atualizar o vault** — leitura unidirecional. Curadoria é outro processo (`/knowledge-sync`).
- **Tratar vault como guia, não fato absoluto** — line numbers podem estar stale; cruzar com código atual sempre.

Implementação: `commands/code-review.md` §"Contexto do repo via Obsidian vault (opcional)" + regra estrita 7.

## Filtros de "não publicar"

Modo Heartbeat **silencia** (não posta nada) se:

- PR é draft (`isDraft: true`).
- Diff só tem: `*.md`, `*.lock`, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `*.min.js`, ícones, imagens, fixtures.
- Diff vazio (PR só renomeou branch, etc.).
- PR tem label `skip-code-review`.

Resultado dos filtros: `runned=0` no SQLite **sem erro de execução**. Confunde com falha real se não inspecionar o `log`. Ver [[regras-negocio]] §5 e [[runbook-debugar-revisao-falhada]].

PRs muito grandes (>50 arquivos OU >2000 linhas adicionadas):
- Revisão **parcial** — top-15 arquivos por importância (rotas/services/handlers/migrations > testes/docs).
- Marca o comentário com: `> ⚠️ Revisão parcial: PR grande (X arquivos / Y linhas)...`.
- Não cria flag estruturada no SQLite — limitação registrada em [[bugs-conhecidos]] §B-003.

## Limite de tamanho do comentário

GitHub corta em ~65k chars. Hierarquia de preservação (do mais ao menos prioritário):
1. **Resumo Executivo** completo (sempre).
2. **Todos** os 🔴 Críticos completos (sempre, com Problema/Impacto/Solução).
3. Sugestões 🟢 Baixas — truncar primeiro, com nota `> ... (N itens adicionais truncados pra caber no limite)`.
4. Pontos Positivos — truncar pra top-3.

## Estrutura obrigatória do comentário

Template completo em `commands/code-review.md:92-199`. Ordem das seções:

1. **Marcador HTML** (linha 1, sempre).
2. `# Code Review Report` + metadados (arquivos, data, escopo, stack detectada).
3. `## 🔍 Resumo do PR` — 1-2 frases sobre o objetivo técnico.
4. `## Resumo Executivo` — tabela contagem por severidade + Veredicto (✅ Aprovado / ⚠️ com ressalvas / ❌ Requer mudanças).
5. `## Issues Encontradas` — subdivididas em 🔴/🟡/🟢. **Seções vazias são OMITIDAS inteiras** (não escrever "Nenhum item").
6. `## ✅ Pontos Positivos` — até 5. Omite se sem destaques.
7. `## Análise Técnica` — opcional, só pra mudanças com nuance arquitetural.
8. `## Métricas de Qualidade` — tabela com 4 linhas: escopo, risco regressão, cobertura, aderência a padrões.
9. **Footer** com badge "Code Review automatizado".

### Padrão dos IDs

`CR-001`, `CR-002`, ... — **contínuos por severidade** (não reseta entre 🔴/🟡/🟢). Permite referenciar issues de forma única em conversas/PRs.

### Padrão de Problema/Solução

```markdown
**Problema:**
```<linguagem>
[trecho do código atual problemático]
```

**Impacto:** [Por que é crítico]

**Solução:**
```<linguagem>
[código corrigido]
```
```

Sempre código com fence + linguagem correta. Bloco "Problema" mostra **código atual** (do diff). Bloco "Solução" mostra **como deveria ficar**.

## Critérios de severidade

Definidos em `commands/code-review.md:230-264`.

### 🔴 Crítico (bloqueia merge)
- Vulnerabilidades: XSS, SQL injection, path traversal, auth bypass, CSRF.
- Race conditions, memory leaks, deadlocks.
- Loops infinitos / recursão sem base.
- Dados sensíveis expostos (tokens, senhas, PII em logs).
- Breaking changes não-documentadas em APIs públicas.
- Migrations destrutivas sem rollback.
- `dangerouslySetInnerHTML` com input não-sanitizado.
- N+1 queries em rotas de produção.

### 🟡 Médio (recomendado corrigir)
- Falta de tratamento de erros em I/O / chamadas externas.
- Re-renders excessivos / falta de memoização claramente necessária.
- Tipos `any` em fronteiras de API públicas.
- Inconsistência com `CLAUDE.md` do repo.
- Código duplicado significativo.
- Testes ausentes para caminho crítico.
- Mudanças semânticas não-óbvias.

### 🟢 Baixo (sugestão)
- Naming inconsistente / pouco descritivo.
- Magic numbers.
- Comentários desnecessários ou desatualizados.
- Pequenas melhorias de legibilidade.
- Typos em identificadores não-públicos.

### ✅ Positivo
- Tratamento robusto de erros / edge cases.
- Testes bem escritos.
- Tipagem completa em fronteiras.
- Decomposição limpa.
- Correção cirúrgica e bem fundamentada.

## Análise de segurança (sempre obrigatória)

Lista de verificação automática (mesmo se diff "parece inocente"):
- Injeção (SQL, shell, path traversal, deserialization).
- XSS (interpolação insegura no DOM, innerHTML, templates não-escapados).
- Auth/AuthZ (rotas que esquecem verificação de token/permissão).
- Exposição (tokens hardcoded, secrets em commits, logs com PII).
- CORS / CSP permissivas demais.
- CSRF (mutações via GET, falta de tokens em forms).
- Dependências (pacotes novos com licença incompatível ou CVE).

## Análise de performance (sempre que aplicável)

- **Backend**: N+1, índices ausentes, locks longos, transações abertas demais.
- **Frontend**: re-renders desnecessários, bundle bloat, assets não-otimizados, falta de lazy loading.
- **Geral**: hot loops, alocações em hot paths, fetches serializados quando paralelo é possível.

## Notas pra integradores

Documentadas no próprio prompt (`commands/code-review.md:289-295`):
- Invocar `claude` com `cwd=$HOME` (ou outro sem `.claude/commands/code-review.md`). Sem isso, comando local sobrescreve o global. Heartbeat usa `CLAUDE_CWD` (default `$HOME`). Ver [[regras-negocio]] §3.
- `--permission-mode bypassPermissions` obrigatório.
- Detecção via `gh api .../comments | jq 'startswith("<!-- code-review-bot:v1 -->")'`.
- Label `skip-code-review` silencia.

## Tratamento de erros pelo prompt

| Erro | Comportamento heartbeat | Comportamento interativo |
|---|---|---|
| PR não existe / sem permissão `gh` | Silenciar (não publica) | `gh auth login` ou avisar |
| Diff vazio / só lock files | Silenciar | "Nada para revisar" |
| Timeout / erro de modelo | Silenciar (heartbeat salva `runned=0` com log) | Reportar |

**Nunca publica stack trace ou "desculpa, não consegui"**. Em produção, isso polui o PR.

## O que NÃO está no prompt (e por quê)

- **Sem template por linguagem**: o prompt é stack-agnóstico. Specs por linguagem entrariam como subseções, mas trade-off de tamanho do prompt (já 304 linhas).
- **Sem exemplos few-shot**: confia no modelo. Adicionar exemplos aumenta tokens fixos por chamada.
- **Sem auto-aprovação ou auto-merge**: bot só comenta. Decisão final é humana.
- **Sem priorização entre 🔴 críticos**: todos são "bloqueia merge". Se 5 críticos, todos importantes igualmente.

## Regras e Invariantes

- **Primeira linha = marcador HTML** (`<!-- code-review-bot:v1 -->`) sempre, sem exceção. Contrato com `fetch_bot_comments`.
- **Não retornar markdown no stdout** — só `Publicado em <url>`. Quebra de [[ADR-005-claude-cli-stdin]].
- **Filtros de "não publicar" vivem aqui**, não no `heartbeat.py`. Mover invalida o modelo.
- **IDs `CR-NNN` são contínuos**, não resetam por severidade. Permite referência única.
- **Análise de segurança é sempre executada**, mesmo em diffs "inocentes" (paranoia justificada).
- **Sem estilo / formatação no review** — linter cuida. Cada palavra sobre estilo é ruído.
- **Mudar `MARKER` requer migration de comentários antigos** — [[bugs-conhecidos]] §B-002.
- **Adicionar tokens ao prompt aumenta custo por revisão** — cada N tokens fixos × cada invocação.

## Mudanças no prompt afetam custo

Cada token a mais no prompt = custo a mais por revisão (cada PR é 1 invocação). Hoje ~3000 tokens de prompt fixo. Cuidado ao adicionar seções — preferir editar/condensar.
