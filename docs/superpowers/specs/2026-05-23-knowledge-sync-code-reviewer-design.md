# Design — `knowledge-sync-code-reviewer`

**Data**: 2026-05-23
**Status**: Aprovado pelo brainstorming, aguardando review humano antes de implementação.
**Tipo**: Skill local versionada no repo.

---

## 1. Contexto

O repo `claude-auto-reviewer` é independente do mesh NPU-Brain por decisão consciente:
- Não tem `.knowledge-sync.yml`.
- Não participa do `knowledge-sync-all`.
- Não é tocado pelo hook diário de `/knowledge-sync` que o curador roda nos 6 repos hinc.

Resultado: o vault Obsidian em `Claude/` (28 notas + 5 templates), montado nesta sessão, **não tem mecanismo de proteção contra drift**. Em 3 meses, line numbers nas notas podem mentir, ADRs podem estar desatualizadas, e o reviewer (que agora lê esse vault via [ADR-006](../../../Claude/ADR-006-leitura-vault-repo-alvo.md)) pode usar info errada.

Solução proposta: skill local enxuta, manualmente invocada quando o dev volta a mexer no repo, que valida coerência código↔vault sem se acoplar ao mesh NPU-Brain.

Adicionalmente, o feature de leitura cross-repo do ADR-006 cria uma dependência implícita: o `commands/code-review.md` espera que os vaults dos 6 repos hinc tenham `regras-negocio.md`, `bugs-conhecidos.md`, `ADR-*.md`. Se algum renomeia/remove, o reviewer falha silenciosamente. A skill oferece um modo opcional read-only pra detectar isso.

## 2. Objetivos

- **Primário**: detectar drift entre código (`heartbeat.py`, `commands/code-review.md`, `install.sh`, `.env.example`, schema SQL) e vault (`Claude/*.md`) deste repo.
- **Secundário**: detectar regressão no contrato entre `commands/code-review.md` e a estrutura dos vaults dos 6 repos NPU (read-only, opt-in).
- **Não-objetivo**: substituir `/knowledge-sync` genérico (que continua sendo o que o curador roda nos 6 hinc).
- **Não-objetivo**: análise profunda dos vaults dos 6 hinc (isso vira `/vault-review` em brainstorming separado).

## 3. Escopo

### In-scope
- Skill local `.claude/skills/knowledge-sync-code-reviewer/SKILL.md`.
- Lista de targets em `.claude/skills/knowledge-sync-code-reviewer/targets.txt`.
- Invocação: `/knowledge-sync-code-reviewer` (default) e `/knowledge-sync-code-reviewer --check-targets`.
- 8 checks (detalhados na §5).
- Relatório markdown no stdout.

### Out-of-scope
- Hook `Stop` automático (curador invoca manualmente).
- `.knowledge-sync.yml` (config hardcoded no SKILL.md).
- Diagnóstico de magnitude light/deep (sempre roda completo — repo é pequeno).
- Captura de regras implícitas via grep extensivo (custo > benefício pro escopo).
- Sister vaults bidirecional (independência).
- Modificação de qualquer arquivo nos 6 vaults NPU (read-only).
- Análise profunda de vaults remotos (vault-review fará isso, em design separado).

## 4. Localização e invocação

| Item | Caminho |
|---|---|
| Skill | `.claude/skills/knowledge-sync-code-reviewer/SKILL.md` |
| Targets opcionais | `.claude/skills/knowledge-sync-code-reviewer/targets.txt` |
| Versionamento | Git deste repo (viaja com o clone) |

**Formato do `targets.txt`**:
```
# Um repo por linha. Path implícito: ~/code/<nome>/Claude/
# Linhas começando com # ou vazias são ignoradas.
hinc-backend
hinc-onepage
hinc-pda-frontend
hinc-dashboards
hinc-dashboards-backend
hinc-etl
```

**Invocação**:
- `/knowledge-sync-code-reviewer` — roda checks 1-7 (validação local).
- `/knowledge-sync-code-reviewer --check-targets` — roda checks 1-8 (inclui targets read-only).

## 5. Checks (ordem importa)

### Check 1 — Diagnóstico do diff
- Comando: `git diff HEAD~10..HEAD -- heartbeat/ commands/ install.sh .env.example .obsidian/`
- Resultado: lista de arquivos mudados + contagem de LOC adicionadas.
- Se zero mudanças → reportar "validação rápida apenas" e pular checks 4-5.

### Check 2 — Line numbers de `heartbeat.py`
- Extrair `grep -n "^def " heartbeat/heartbeat.py` → tabela função/linha.
- Comparar com tabela citada em `Claude/arquitetura.md` (§"Componentes (na ordem do fluxo)") e `Claude/modulo-heartbeat.md` (§"Layout do arquivo").
- Reportar discrepâncias: função X listada em linha Y na nota, mas está em linha Z no código.
- Não corrigir automaticamente — humano decide.

### Check 3 — Cobertura "Regras e Invariantes"
- T1 substantivas (não-MOC): contar quantas têm seção `## Regras e Invariantes`. Meta: 100%.
- T2 grandes (>200 linhas): mesma contagem. Meta: 100%.
- MOCs (`_MOC *.md`): pulados intencionalmente (decisão consciente documentada — meta-navegação, não conteúdo).
- Reportar FALTA: <nome> para cada nota descoberta sem a seção.

### Check 4 — Sync matrix (mudança óbvia)
Tabela de relações 1-pra-1:

| Arquivo de código mudou | Nota correspondente atualizada? |
|---|---|
| `heartbeat/heartbeat.py` | `Claude/modulo-heartbeat.md` ∧ `Claude/arquitetura.md` |
| `commands/code-review.md` | `Claude/regras-prompt-review.md` |
| `install.sh` | `Claude/deploy.md` ∧ `Claude/ADR-003-symlinks-no-install.md` |
| SCHEMA (const em `heartbeat.py`) | `Claude/arquitetura-banco.md` |
| `.env.example` | `Claude/env-setup.md` |

Pra cada arquivo de código mudado no diff: checar se a(s) nota(s) correspondente(s) também está(ão) no diff. Se não → flag "vault drift suspeito".

### Check 5 — ADRs pendentes
- Heurística: mudou >50 LOC em `heartbeat.py` OU >30 LOC em `commands/code-review.md` desde o último commit, SEM novo `Claude/ADR-*.md` no diff?
- Se sim → flag "mudança estrutural sem ADR — considere criar".
- Falsos positivos esperados (refactor sem mudança de decisão). Humano filtra.

### Check 6 — Validação básica
- Contagem: notas substantivas + templates + links.
- Ilhas: notas com zero outbound links (excluir templates).
- Frontmatter: toda nota substantiva tem frontmatter YAML válido (`---` na linha 1)?
- Broken links: wikilinks `[[X]]` que não resolvem pra `Claude/X.md` ou `Claude/_templates/X.md`.
- Excluir intencionalmente: `[[outra-nota]]` em `_templates/nota-livre.md` (placeholder do template).

### Check 7 — Áreas universais
- Fallback genérico do `/knowledge-sync` original.
- Validar que `regras-negocio.md`, `glossario.md`, `arquitetura.md` existem e têm ≥3 inbound links cada.

### Check 8 — Targets check (opt-in)
- Só roda com flag `--check-targets`.
- Pra cada linha em `targets.txt`:
  - Tentar `ls $HOME/code/<nome>/Claude/`.
  - Se não existe → status ❌ "vault ausente".
  - Se existe, verificar presença de:
    - `regras-negocio.md` → ✓ ou ❌
    - `bugs-conhecidos.md` → ✓ ou ❌
    - `ADR-*.md` → contagem (0 é OK, só reportar)
  - Status final do repo:
    - ✅ se ambos arquivos presentes
    - ⚠️ se 1 dos 2 ausente
    - ❌ se vault ausente
- **Read-only**: nenhuma modificação nos 6 vaults.
- Output: tabela formato do mockup aprovado em conversa.

## 6. Output esperado

Relatório markdown no stdout, salvo opcionalmente em `~/.claude/heartbeat/logs/knowledge-sync-cr-YYYY-MM-DD-HHMM.log`:

```markdown
## Knowledge Sync Code-Reviewer Report — 2026-05-23 17:42

### Modo
{validação rápida | validação completa | validação completa + targets}

### Diff desde último sync
- 3 arquivos mudados, 47 LOC adicionadas
- heartbeat/heartbeat.py (+30 LOC)
- commands/code-review.md (+15 LOC)
- Claude/regras-prompt-review.md (+2 LOC)

### Line numbers (heartbeat.py)
- ✅ Todas as 13 funções batem com Claude/arquitetura.md
- ⚠️ Claude/modulo-heartbeat.md cita `process_pr` em linha 282 mas está em 285 (drift de 3 linhas)

### Cobertura "Regras e Invariantes"
- T1 substantivas: 6/6 ✅
- T2 grandes (>200): 4/4 ✅
- MOCs: 0/5 (intencional — meta-navegação)

### Sync matrix
| Código mudou | Nota atualizada? |
|---|---|
| heartbeat/heartbeat.py | modulo-heartbeat.md ✅ arquitetura.md ❌ |
| commands/code-review.md | regras-prompt-review.md ✅ |

### ADRs pendentes
- ⚠️ heartbeat.py mudou 30 LOC sem novo ADR — verificar se há decisão estrutural

### Validação básica
- 29 notas substantivas + 5 templates
- 344 wikilinks
- 0 ilhas
- 0 sem frontmatter
- 0 broken links (excluindo placeholders intencionais)

### Áreas universais
- ✅ regras-negocio: 18 inbound
- ✅ glossario: 3 inbound
- ✅ arquitetura: 20 inbound

### Targets check (--check-targets)
| Repo | regras-negocio | bugs-conhecidos | ADRs | Status |
|---|---|---|---|---|
| hinc-backend | ✓ | ✓ | 5 | ✅ |
| hinc-onepage | ✓ | ✓ | 6 | ✅ |
| hinc-dashboards | ✓ | ✗ | 8 | ⚠️ |
| hinc-etl | ✓ | ✓ | 0 | ✅ |
| hinc-pda-frontend | ✗ | ✓ | 4 | ⚠️ |
| hinc-dashboards-backend | ✓ | ✓ | 3 | ✅ |

### Gaps acionáveis
- [ ] Atualizar Claude/modulo-heartbeat.md — line number de process_pr está em drift
- [ ] Decidir se mudança no heartbeat.py precisa de ADR
- [ ] Investigar gaps de targets: hinc-dashboards (bugs-conhecidos faltando), hinc-pda-frontend (regras-negocio faltando)
```

## 7. Implementação

### Estrutura de arquivos
```
.claude/skills/knowledge-sync-code-reviewer/
├── SKILL.md              # ~150 linhas — definição da skill com os 8 checks
└── targets.txt           # ~10 linhas — lista de repos NPU pro check 8
```

### SKILL.md — esboço de estrutura
- Frontmatter (name, description, when to use).
- §"Quando usar".
- §"Checks na ordem" — cada check com descrição, comando bash, output esperado.
- §"Formato do relatório" — template.
- §"Anti-patterns" — o que NÃO fazer (modificar vaults remotos, sobrescrever notas, etc.).

### Dependências
- `bash` (gnu).
- `grep`, `find`, `wc`, `git` (padrão).
- Nada de Python externo. Nada de YAML parsing complexo.

### Não-dependências
- `yq` / `jq` (não precisa — sem YAML parsing externo).
- Skill genérica `knowledge-sync` (skill é standalone, não importa nada).

## 8. Critérios de aceitação

A implementação está completa quando:

- [ ] `.claude/skills/knowledge-sync-code-reviewer/SKILL.md` existe e tem os 8 checks documentados.
- [ ] `.claude/skills/knowledge-sync-code-reviewer/targets.txt` existe com os 6 repos NPU listados.
- [ ] Invocar `/knowledge-sync-code-reviewer` no Claude Code (cwd = raiz deste repo) produz o relatório nos checks 1-7.
- [ ] Invocar `/knowledge-sync-code-reviewer --check-targets` adiciona o check 8 com tabela dos 6 repos.
- [ ] Vault deste repo (`Claude/*.md`) tem nota documentando a skill (ex: nova entrada em `Claude/runbook-*` ou nota nova `Claude/knowledge-sync-code-reviewer.md`).
- [ ] `CLAUDE.md` raiz menciona a skill na seção "Comandos" ou similar.

## 9. Smoke test pós-implementação (não-bloqueante)

- Rodar `/knowledge-sync-code-reviewer` no estado atual do repo. Esperado: validação limpa, 0 gaps acionáveis (acabamos de sincronizar tudo).
- Rodar `/knowledge-sync-code-reviewer --check-targets`. Esperado: tabela dos 6 hinc com status real.
- Fazer mudança trivial em `heartbeat.py` (ex: comentário). Rodar de novo. Esperado: check 4 flag "vault drift suspeito" porque `modulo-heartbeat.md` não foi atualizado.

## 10. Trabalho relacionado / próximos brainstormings

- **`/vault-review`** (skill separada): análise profunda dos vaults (local + opcional NPU). Métricas ricas (health score, notas stale, ADRs órfãos, tier coverage, etc.). Brainstorming separado, depois desta skill estar implementada.
- **TD-002 (`outcome` estruturado em `code_reviews`)**: tech debt mencionado em conversa. Não bloqueia esta skill, mas faria sentido como próxima feature do sistema principal.
- **ADR-007 candidato**: se a skill mudar algum comportamento do reviewer (ex: gatear merge baseado em check 4), virar ADR.

## 11. Riscos conhecidos

| Risco | Mitigação |
|---|---|
| Skill não roda em cwd errado (precisa estar na raiz deste repo) | Documentar no SKILL.md; check inicial valida que `pwd` é a raiz |
| Targets.txt fica desatualizado se NPU adicionar/remover repos | Comentário no arquivo lembrando que é manual; futuro: auto-detect a partir de `~/code/hinc-*` |
| Heurística do check 5 (ADRs pendentes) gera muito falso positivo | Marcado como warning, não bloqueio; humano filtra |
| Curador esquece de rodar a skill | Aceito — mesma natureza do `/knowledge-sync` que é manual |
| Targets check fica pesado se NPU crescer pra 20+ repos | Aceito por ora; futuro: paralelizar com `xargs -P` ou virar `/vault-review` |

---

**Autor**: brainstorming session 2026-05-23
**Próximo passo após approval**: invocar `superpowers:writing-plans` pra gerar plano de implementação.
