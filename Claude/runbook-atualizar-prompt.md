---
title: Runbook — atualizar o prompt de review
type: runbook
status: active
tags:
  - runbook
  - backend
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[regras-prompt-review]]"
  - "[[regras-negocio]]"
  - "[[runbook-testar-localmente]]"
tier: 3
---

# Runbook — atualizar `commands/code-review.md`

## Quando usar
- Mudar critérios de severidade.
- Adicionar/remover seções do template do comentário.
- Ajustar filtros de "não publicar".
- Trocar formato de output.

## Antes de começar

Pergunte-se:

1. **A mudança quebra contrato com o heartbeat?** Os contratos críticos são:
   - Primeira linha = `<!-- code-review-bot:v1 -->` (marcador) — **não mudar**.
   - Postagem direta via `gh pr comment` (não retorna markdown) — **não mudar sem revisar [[ADR-005-claude-cli-stdin]]**.
   - Modo detectado por "publique" em $ARGUMENTS — **não mudar sem coordenar com `invoke_claude`**.

2. **A mudança aumenta tokens?** Cada token adicional é cobrado por revisão. Hoje ~3000 tokens fixos. Aumentar pra 5000 = 67% mais caro. Prefira condensar ao adicionar.

3. **A mudança vai virar um ADR?** Mudanças que alteram comportamento estrutural (não só refinar regra existente) devem registrar uma ADR nova.

## Passos

### 1. Branch e edit
```bash
cd <repo-do-claude-auto-reviewer>
git checkout -b prompt/<descricao-curta>
nano commands/code-review.md
```

### 2. Lint visual

- Headings hierárquicos consistentes (não pular `## → ####`).
- Code fences com linguagem (` ```bash`, ` ```python`).
- Numeração de listas só onde a ordem importa.

### 3. Teste local — modo interativo

Use o próprio Claude CLI em modo interativo num PR de teste:
```bash
cd ~  # garantir cwd sem .claude/commands/code-review.md local
claude
> /code-review https://github.com/<seu>/<repo>/pull/<num>
```

(Sem `publique` — só exibe o relatório.)

Validações:
- Estrutura segue o template novo.
- Marcador HTML presente.
- Severidades coerentes.
- Sem placeholders tipo "Nenhum item nesta categoria" (seções vazias devem ser omitidas).
- IDs `CR-XXX` contínuos.

### 4. Teste local — modo heartbeat (publica de verdade)

Use um **PR de teste descartável** (idealmente em repo de sandbox):

```bash
# Garantir que NÃO há linha pro head_sha em code_reviews
sqlite3 ~/.claude/heartbeat/state.db \
  "DELETE FROM code_reviews WHERE repo='<sandbox>' AND pr_number=<num>;"

# Disparar manual
python3 ~/.claude/heartbeat/heartbeat.py

# Verificar SQLite
sqlite3 ~/.claude/heartbeat/state.db \
  "SELECT runned, comment_id, substr(log,1,300) FROM code_reviews WHERE repo='<sandbox>' AND pr_number=<num> ORDER BY id DESC LIMIT 1;"

# Verificar no PR
gh pr view <num> --repo <sandbox> --comments | head -50
```

`runned` deve ser `1`, `comment_id` não-nulo, comentário visível no PR com marcador correto.

### 5. Commit + PR
```bash
git add commands/code-review.md
git commit -m "prompt: <descrição curta>"
git push -u origin prompt/<descricao>
gh pr create --fill
```

### 6. Deploy
Symlink ([[ADR-003-symlinks-no-install]]) faz o deploy ser `git pull`:
```bash
cd <repo>
git pull origin main
```

Próxima invocação do Claude usa o novo prompt — sem restart, sem nada.

## Validar em produção (smoke)

Depois do merge:
1. Observar primeiras 3-5 revisões via Datasette ou tail do `heartbeat.log`.
2. Sample manual: ler 1-2 comentários completos no GitHub, verificar formato.
3. Se algo errado: `git revert` rápido. Symlinks propagam o revert imediatamente.

## Rollback

```bash
cd <repo>
git revert <commit-do-prompt>
git push
git pull  # garantir local sincronizado
```

Comentários já publicados ficam — não há retroativo. Revisões futuras usarão prompt revertido imediatamente.

## Casos específicos

### Mudar `MARKER`
**Não fazer em produção.** Quebra detecção histórica ([[bugs-conhecidos]] §B-002). Se inevitável:
1. Discutir + ADR documentando.
2. Migration script que reescreve `<!-- v1 -->` → `<!-- v2 -->` em comments antigos via `gh api PATCH`.
3. Atualizar `MARKER` env var em conjunto.

### Adicionar nova seção opcional no template
Documentar no `commands/code-review.md` que a seção é opcional (omitir se vazia) — seguindo padrão das outras seções (🔴/🟡/🟢, Análise Técnica).

### Mudar critérios de severidade
- Atualizar §"Critérios de severidade" no prompt.
- Atualizar [[regras-prompt-review]] (esta nota do vault) pra refletir.
- Considerar se mudança força recalibração — PRs revisados antes têm severidade "antiga". Aceitável (PR já mergeado é histórico).

### Adicionar análise por linguagem (ex: regras Python específicas)
- Adicionar §"Análise por stack" condicional.
- Cuidado com tokens — se for grande, considerar prompt secundário invocado apenas pra stacks específicas (mas requer mudança em `invoke_claude` pra passar arg de stack). Hoje não há suporte. Tech debt.

## Notas relacionadas
- [[regras-prompt-review]] — análise completa das regras atuais.
- [[ADR-005-claude-cli-stdin]] — por que o Claude posta direto.
- [[regras-negocio]] §3 — `bypassPermissions` e `cwd=$HOME`.
- [[runbook-testar-localmente]] — setup pra rodar tick sem cron.
