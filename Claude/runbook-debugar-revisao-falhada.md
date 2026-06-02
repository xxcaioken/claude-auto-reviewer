---
title: Runbook — debugar revisão que falhou
type: runbook
status: active
tags:
  - runbook
  - backend
  - bug
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[error-handling]]"
  - "[[regras-negocio]]"
  - "[[arquitetura-banco]]"
  - "[[bugs-conhecidos]]"
tier: 3
---

# Runbook — debugar revisão que ficou com `runned=0`

## Quando usar
- PR foi pra revisão mas o comentário não apareceu.
- Datasette mostra linha com `runned=0` recente.
- Suspeita que o Claude está falhando consistentemente.

## Triagem inicial (60s)

### Identificar a linha problemática
```bash
sqlite3 ~/.claude/heartbeat/state.db <<'SQL'
SELECT id, runned_at, repo, pr_number, head_sha,
       substr(log, 1, 200) AS log_inicio
FROM code_reviews
WHERE runned = 0
ORDER BY runned_at DESC
LIMIT 5;
SQL
```

Pegar o `id` da linha de interesse pra próximas queries.

### Ver o log completo
```bash
sqlite3 ~/.claude/heartbeat/state.db \
  "SELECT log FROM code_reviews WHERE id = <ID>;" | less
```

O `log` tem:
```
rc=<código>
--- stdout ---
<até 5000 chars do stdout do claude>
--- stderr ---
<até 2000 chars do stderr>
```

## Classificar a causa

### Caso 1: `rc=0` + stdout dizendo "diff só docs" ou "PR draft"

**Diagnóstico**: filtro do prompt funcionando como esperado. Ver [[regras-prompt-review]] §"Filtros de 'não publicar'".

**Ação**: nenhuma. `runned=0` é "publicação intencionalmente pulada", não erro.

**Como confirmar**: stdout deve mencionar uma das razões. Se confirmar, fechar investigação.

---

### Caso 2: `rc != 0` ou stderr com erro de `gh`

**Diagnóstico**: falha do binário externo. Categorias comuns:

| Stderr | Causa | Fix |
|---|---|---|
| `gh: command not found` | `gh` desinstalado | `sudo apt install gh` ou `brew install gh` |
| `error: not authenticated` | Token GitHub expirou | `gh auth refresh` ou `gh auth login` |
| `HTTP 403: Resource not accessible` | Scopes faltando | `gh auth refresh -s repo,workflow` |
| `HTTP 404: Not Found` | Repo movido/privado/sem acesso | Verificar acesso em github.com manualmente |
| `dial tcp ... timeout` | Rede caiu | Aguardar; próximo tick reprocessará após retry manual (§Forçar retry) |

**Ação**: corrigir o root cause; rodar `python3 ~/.claude/heartbeat/heartbeat.py` manual pra validar.

---

### Caso 3: `rc=-1` + `TIMEOUT após 600s`

**Diagnóstico**: Claude rodou mais que o timeout. Causas comuns:
- PR gigantesco com diff de milhares de linhas.
- Prompt fez análise iterativa muito profunda (raro).
- Modelo Claude retornou loop interno (regression).

**Ação**:
- Verificar tamanho do diff: `gh pr diff <num> --repo <r> | wc -l`.
- Se >5000 linhas, aumentar timeout pra esse PR específico via env var, OU aplicar label `skip-code-review` se for caso especial.
- Se diff normal mas Claude trava: registrar como possível regression. Verificar versão do `claude` CLI.

---

### Caso 4: `rc=0` + stdout normal mas comentário não apareceu

**Diagnóstico**: Claude rodou, mas snapshot before/after não detectou. Causas:

#### a. Marcador HTML errado

Ver corpo dos últimos comentários do PR:
```bash
gh api repos/<owner>/<repo>/issues/<pr_number>/comments \
  --jq '.[] | {id, author: .user.login, body_start: .body[0:80]}'
```

Se há comentário do bot mas começa com algo diferente de `<!-- code-review-bot:v1 -->`, o Claude esqueceu o marcador. **Investigar mudança recente em `commands/code-review.md`** (`git log -- commands/code-review.md`).

Fix: garantir que o prompt mantém o marcador como primeira linha. Não mudar `MARKER` em produção ([[bugs-conhecidos]] §B-002).

#### b. `fetch_bot_comments` falhou silenciosamente

Stderr do `gh api` não vai pro log do `process_pr` (a function loga warning separado em `~/.claude/heartbeat/logs/heartbeat.log`). Procurar:
```bash
grep "fetch_bot_comments" ~/.claude/heartbeat/logs/heartbeat.log | tail -10
```

Se há warnings frequentes, é problema de rede ou rate-limit. Aguardar.

#### c. Race condition rara (Claude posta após o snapshot after)

Detecção: o comentário existe no PR mas `created_at` é depois do `runned_at` da linha. Extremamente raro (Claude espera publicação antes de retornar).

Fix: forçar retry manual (§Forçar retry abaixo).

---

## Forçar retry

Se quer re-revisar **o mesmo `head_sha`** (porque a causa foi transitória):

```bash
# 1. Confirmar a linha a apagar
sqlite3 ~/.claude/heartbeat/state.db \
  "SELECT id, runned_at, repo, pr_number FROM code_reviews WHERE id = <ID>;"

# 2. Deletar (cuidadoso — é a única forma de retry em append-only)
sqlite3 ~/.claude/heartbeat/state.db \
  "DELETE FROM code_reviews WHERE id = <ID>;"

# 3. Próximo tick (até 5 min) re-revisa. Ou força agora:
python3 ~/.claude/heartbeat/heartbeat.py
```

Verificar resultado no log e no DB.

## Cenário: muitos `runned=0` recentes

Se >10 falhas seguidas, provavelmente é problema sistêmico:

```bash
# Quantos por causa (proxy: primeira linha do log)
sqlite3 ~/.claude/heartbeat/state.db <<'SQL'
SELECT
  CASE
    WHEN log LIKE '%TIMEOUT%' THEN 'timeout'
    WHEN log LIKE 'rc=0%' THEN 'rc=0 (filtro?)'
    WHEN log LIKE 'rc=%' THEN 'rc!=0'
    ELSE 'outro'
  END AS causa,
  COUNT(*) AS n
FROM code_reviews
WHERE runned = 0 AND runned_at > datetime('now', '-1 day')
GROUP BY causa;
SQL
```

- Predominância `timeout`: aumentar `CLAUDE_TIMEOUT` ou investigar regressão no modelo.
- Predominância `rc!=0`: checar `gh auth status` e binários.
- Predominância `rc=0`: provavelmente filtro normal (`skip-code-review` em vários PRs, diffs só docs em série).

## Mudar `MARKER` pra recuperar histórico (não recomendado)

Se o problema é "marcador divergente" (Caso 4a), **NÃO mude** `MARKER` em produção — quebra detecção histórica ([[bugs-conhecidos]] §B-002). Em vez disso, alinhe o prompt pra usar o marcador correto.

## Notas relacionadas
- [[error-handling]] — todos os cenários de erro do sistema.
- [[regras-negocio]] §1 — por que `runned=0` bloqueia retry automático.
- [[arquitetura-banco]] — schema completo.
- [[bugs-conhecidos]] §B-002 — armadilha de mudar MARKER.
