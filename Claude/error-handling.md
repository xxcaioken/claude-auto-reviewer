---
title: Tratamento de erros — fluxos e fail-modes
type: flow
status: active
tags:
  - backend
  - reference
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[arquitetura]]"
  - "[[regras-negocio]]"
  - "[[regras-prompt-review]]"
  - "[[bugs-conhecidos]]"
  - "[[runbook-debugar-revisao-falhada]]"
tier: 2
---

# Tratamento de erros

Cada ponto de falha possível, o que acontece, e como rastrear. Filosofia geral: **fail-soft** — erros em um PR/repo nunca abortam o tick inteiro. Estado vai pro SQLite, log vai pro `heartbeat.log`.

## Mapa de erros por camada

### Camada: pré-requisitos (`check_prerequisites`, heartbeat.py:329-345)

| Erro | Detecção | Ação |
|---|---|---|
| `claude` não existe | `Path(CLAUDE_BIN).exists()` False | `log.error` + `return False` → `main` faz `sys.exit(1)` |
| `gh` não existe | idem | idem |
| `gh auth status` rc != 0 ou timeout | subprocess | idem |
| `repos.txt` não existe | `REPOS_FILE.exists()` False | idem |

**Resultado**: tick aborta. Sem entrada no `code_reviews`. Sem retry interno — próximo tick (5 min) tenta de novo. Se o problema é persistente (binário desinstalado), todos os ticks falham até resolver.

### Camada: lock fcntl (`main`, heartbeat.py:351-356)

| Erro | Detecção | Ação |
|---|---|---|
| Outro tick em execução | `fcntl.flock(LOCK_NB)` → `BlockingIOError` | `log.info("outro tick em progresso, abortando este (sem erro)")` + `return` (não sys.exit, não erro) |

**Resultado**: tick aborta silenciosamente. **Não é erro** — é o comportamento desejado quando lote grande atravessa intervalos do cron.

### Camada: descoberta de PRs (`gh_pr_list`, heartbeat.py:158-176)

| Erro | Detecção | Ação |
|---|---|---|
| `gh pr list` rc != 0 | `subprocess.CalledProcessError` | `log.error("gh pr list falhou em <repo>: <stderr[:500]>")` + `return []` |
| `gh pr list` timeout (60s) | `subprocess.TimeoutExpired` | `log.error` + `return []` |
| JSON inválido | `json.JSONDecodeError` | `log.error` + `return []` |

**Resultado**: o repo processa zero PRs neste tick. **Sem fallback ou retry**. Próximo tick reprocessa todos os PRs do repo (já que não houve INSERT em `code_reviews`).

**Caso problemático**: rate-limit do GitHub. `gh` tem retry interno básico, mas se cair em 429, retorna erro. Ticks sucessivos podem reproduzir até o limite resetar. Não há circuit breaker.

### Camada: detecção de comentários do bot (`fetch_bot_comments`, heartbeat.py:179-201)

| Erro | Detecção | Ação |
|---|---|---|
| `gh api` rc != 0 | CalledProcessError | `log.warning` + `return []` |
| Timeout | TimeoutExpired | `log.warning` + `return []` |
| Linha JSON inválida | JSONDecodeError (no parsing de cada linha) | `continue` (pula só a linha) |

**Resultado**: `before_ids` ou `after` fica vazio. Em `process_pr`:
- Se `before_ids` falhou: `new_comments = after - {} = after`. Pode marcar comentário antigo como "novo" → `runned=1` falso positivo.
- Se `after` falhou: `new_comments = [] - before_ids = []`. Marca `runned=0` falso negativo (Claude publicou, sistema não detectou).

**Mitigação**: warning no log. Operador investiga via [[runbook-debugar-revisao-falhada]].

### Camada: invocação do Claude (`invoke_claude`, heartbeat.py:241-257)

| Erro | Detecção | Ação |
|---|---|---|
| Claude rc != 0 | `subprocess.run` retorna rc != 0 | retorna tupla `(rc, stdout, stderr)`, `process_pr` salva `runned=0` + log com stderr |
| Claude timeout (600s default) | `subprocess.TimeoutExpired` | retorna `(-1, "", "TIMEOUT após 600s: <e>")`, salva `runned=0` |
| Claude rodou mas não publicou (filtro do prompt) | rc=0 mas `new_comments` vazio em `process_pr` | `log.info("⊘ claude rodou mas não publicou comentário")`, `runned=0` |

**Importante**: `runned=0` é **sobrecarregado** — mistura 3 causas:
1. Claude falhou (timeout, rc != 0).
2. Claude rodou ok, mas filtro do prompt decidiu não publicar (diff só docs, PR draft inesperado, etc.).
3. Claude publicou mas snapshot não detectou (marcador errado, bug em `fetch_bot_comments`).

A única forma de distinguir é inspecionar o `log`:
- `rc=0` + stdout dizendo "diff só docs/lockfiles" → filtro do prompt (caso 2, **OK**).
- `rc != 0` → falha real (caso 1).
- `rc=0` + stdout vazio ou normal → suspeita do caso 3, investigar manualmente.

Tech debt registrado: [[tech-debt]] §TD-002 (separar falha de filtro).

### Camada: persistência (`save_review`, heartbeat.py:260-279)

| Erro | Detecção | Ação |
|---|---|---|
| `database is locked` | sqlite3 com `busy_timeout=30000` — espera 30s | Após 30s, levanta `sqlite3.OperationalError` |
| Tabela não existe | UNLIKELY (init_db roda antes) | Exception propaga até `process_repo` que faz `log.exception` |

**Resultado**: erro propaga. Em `process_pr` há `except Exception` (heartbeat.py:325-326) que loga e segue pro próximo PR. **Não aborta o tick** — só perde esse PR (que será re-tentado no próximo tick, já que `code_reviews` não recebeu INSERT).

### Camada: orquestração (`process_repo`, `process_pr`)

`process_repo` (heartbeat.py:310-326) tem `try/except Exception` em volta do `process_pr`. Garante que erro em 1 PR não derruba o resto do repo.

`main` (heartbeat.py:367-371) tem `try/except Exception` em volta do `process_repo`. Garante que erro em 1 repo não derruba o tick.

---

## Cenários compostos

### Cenário A: GitHub fora do ar por 1h

- Ticks 1-12 (1 hora): `gh_pr_list` retorna `[]` pra todos os repos. Logs com error. Zero INSERTs.
- Tick 13: GitHub volta. `gh_pr_list` retorna PRs. `needs_review` consulta `code_reviews` — não acha nada pra esses head_sha → revisa tudo.
- Resultado: lote grande processa todos os PRs que ficaram esperando. Pode atravessar vários intervalos de cron (lock fcntl aborta os ticks intermediários).

**Sem perda de revisão**, mas latência aumenta (alguns PRs revisados ~1h após push).

### Cenário B: Claude CLI desinstalado

- `check_prerequisites` falha. `sys.exit(1)` em todo tick.
- cron acumula falhas — visível em `/var/log/syslog`.
- Notar que: `heartbeat.log` tem `ERROR` linhas mas pode passar despercebido. Sem alerta proativo.

**Backlog**: alerta por email ou Discord webhook quando N ticks consecutivos falham. Não implementado.

### Cenário C: PR com diff inválido (binário corrompido no diff)

- `gh pr diff` (dentro do Claude) pode falhar.
- Claude tenta tratar — depende do prompt. Provavelmente retorna mensagem curta sem publicar → `runned=0` com log mostrando "diff inválido".
- Próximo push corrige → `head_sha` muda → revisa de novo.

### Cenário D: Comentário publicado mas marcador errado (ex: `v2` em vez de `v1`)

- Claude posta com `<!-- code-review-bot:v2 -->`.
- `fetch_bot_comments` (filtra por `v1`) não detecta.
- `runned=0`, log normal.
- Comentário fica no PR como "publicação fantasma" (existe, mas sistema não sabe).
- Próximo tick — `needs_review` retorna False (porque a linha `runned=0` já existe). NÃO retenta.

**Sintoma típico**: dev vê comentário no PR, mas Datasette mostra `runned=0`. Diagnóstico: comparar marcador da string `MARKER` no env com o que o prompt está usando.

---

## Logs como ferramenta primária

Tudo loga em:
- `~/.claude/heartbeat/logs/heartbeat.log` — completo, com timestamp.
- stdout do cron — vai pra `/var/log/syslog` se cron redirecionar (depende da config).

Níveis usados:
- `INFO` — fluxo normal (tick start/end, "processando X", "revisando #N").
- `WARNING` — falha não-fatal de `gh` (`fetch_bot_comments` falhou).
- `ERROR` — falha do binário (`claude rc=N`), pré-requisitos.
- Sem `DEBUG` (heartbeat.py não usa).

Comandos úteis:
```bash
# Tail em tempo real
tail -f ~/.claude/heartbeat/logs/heartbeat.log

# Erros recentes
grep ERROR ~/.claude/heartbeat/logs/heartbeat.log | tail -20

# Ticks que abortaram por lock
grep "outro tick em progresso" ~/.claude/heartbeat/logs/heartbeat.log | tail -10
```

## Pra onde isto NÃO escala

Tudo descrito é single-machine, single-process. Múltiplas máquinas processando os mesmos repos: hoje, ambas insiriam linhas em `code_reviews` para o mesmo `head_sha` antes da consulta `needs_review`. Race condition real. Solução requer lock global externo (Redis, Postgres) — fora do escopo do MVP.
