---
title: Setup de ambiente e variáveis
type: reference
status: active
tags:
  - backend
  - onboarding
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[deploy]]"
  - "[[dependencias]]"
  - "[[runbook-testar-localmente]]"
tier: 2
---

# Setup de ambiente

Tudo configurável via env vars. Todas têm default sensato — geralmente o user só edita `~/.claude/heartbeat/repos.txt`.

## Variáveis disponíveis

### Paths

| Var | Default | Quando mudar |
|---|---|---|
| `HEARTBEAT_DIR` | `~/.claude/heartbeat` | Mover dados pra outro disco (SSD dedicado, NFS) |
| `CLAUDE_BIN` | `which claude` → `~/.local/bin/claude` | Claude instalado em path custom |
| `GH_BIN` | `which gh` → `/usr/bin/gh` | gh instalado em path custom |
| `CLAUDE_CWD` | `$HOME` | **Cuidado**: deve ser um diretório SEM `.claude/commands/code-review.md` local (senão comando local vence global). Ver [[regras-negocio]] §3 |

### Comportamento

| Var | Default | Quando mudar |
|---|---|---|
| `MARKER` | `<!-- code-review-bot:v1 -->` | **Nunca mude em produção** — quebra detecção histórica ([[bugs-conhecidos]] §B-002) |
| `SKIP_LABEL` | `skip-code-review` | Renomear se conflito com label existente do org |

### Timeouts (segundos)

| Var | Default | Quando mudar |
|---|---|---|
| `CLAUDE_TIMEOUT` | `600` (10min) | PRs gigantes consistentemente dando timeout |
| `GH_TIMEOUT` | `60` | Conexão lenta com GitHub |
| `SQLITE_TIMEOUT` | `30` | Concorrência alta no DB (ex: rodando datasette pesado) |

## Como aplicar env vars

### Pra um teste manual ad-hoc
```bash
CLAUDE_TIMEOUT=1200 python3 ~/.claude/heartbeat/heartbeat.py
```

### Pro cron (persistente)
Crontab respeita env vars na linha:
```cron
*/5 * * * * CLAUDE_TIMEOUT=1200 /usr/bin/python3 ~/.claude/heartbeat/heartbeat.py >/dev/null 2>&1
```

Ou via `.env` + wrapper:
```bash
# wrapper.sh
#!/bin/bash
set -a; source ~/.claude/heartbeat/.env; set +a
python3 ~/.claude/heartbeat/heartbeat.py
```

```cron
*/5 * * * * /home/user/.claude/heartbeat/wrapper.sh >/dev/null 2>&1
```

### Pro datasette (systemd)
Editar `~/.config/systemd/user/datasette-heartbeat.service` e adicionar:
```ini
[Service]
Environment="HEARTBEAT_DIR=/custom/path"
ExecStart=...
```
Depois `systemctl --user daemon-reload && systemctl --user restart datasette-heartbeat`.

## `.env.example` (versionado)

O `.env.example` no root do repo documenta todas as vars. Cópia local:
```bash
cp .env.example .env
nano .env   # descomentar e editar
```

Note: `.env` está no `.gitignore`. Nunca commitar.

## Validação pós-setup

Após instalar, antes de armar o cron:

```bash
# 1. Verificar binários
which claude && which gh && python3 --version

# 2. Verificar autenticação
gh auth status

# 3. Verificar repos.txt
cat ~/.claude/heartbeat/repos.txt | grep -v '^#' | grep -v '^$'

# 4. Tick manual (não vai postar nada se não houver PR novo)
python3 ~/.claude/heartbeat/heartbeat.py

# 5. Inspecionar log
tail -30 ~/.claude/heartbeat/logs/heartbeat.log
```

Esperado no log:
```
=== tick start ===
monitorando N repo(s)
Processando <nome> (<owner>/<repo>)
  K PR(s) aberto(s)
=== tick end ===
```

Se aparecer `ERROR` na primeira execução, problema de setup. Cruzar com [[error-handling]] pra diagnosticar.

## Multi-instância no mesmo host

Possível, mas:
- Cada instância precisa `HEARTBEAT_DIR` diferente (state.db, logs, lockfile não podem colidir).
- `repos.txt` separados.
- Linhas de cron separadas (apontando pros wrappers diferentes).
- Datasette: portas diferentes (`--port 8002`, etc.).

Caso de uso real: separar revisão de repos de orgs diferentes (`MARKER` diferente, diferenciando comentários). Pouco testado — improvise com cuidado.
