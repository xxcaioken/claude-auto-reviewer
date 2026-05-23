---
title: Dependências externas e internas
type: dependencies
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
  - "[[env-setup]]"
  - "[[deploy]]"
tier: 1
---

# Dependências

Toda dependência externa do sistema, versão mínima e o que quebra sem ela.

## Runtime obrigatórias

### Python ≥ 3.10

**Onde usado**: tudo em `heartbeat/heartbeat.py`.

**Por quê 3.10**: usa `str | None` em vez de `Optional[str]` em alguns lugares (PEP 604 type hints), e parâmetros keyword-only em `save_review` (`*`, body=...). Funcional em 3.9 com pequenos ajustes, mas não testado.

**Quebra**: `SyntaxError` no import.

**Módulos stdlib usados**: `datetime`, `fcntl`, `json`, `logging`, `os`, `pathlib`, `shutil`, `sqlite3`, `subprocess`, `sys`.

### Claude Code CLI (`claude`)

**Onde usado**: `invoke_claude` (heartbeat.py:241) — `subprocess.run([CLAUDE_BIN, "--permission-mode", "bypassPermissions", "-p", ...])`.

**Versão mínima**: precisa suportar `--permission-mode bypassPermissions` + `-p <prompt>` modo não-interativo. Versões 2024+ ok.

**Quebra**: `check_prerequisites` (heartbeat.py:330) aborta com `claude não encontrado em <path>`.

**Detecção**: `which claude` → `~/.local/bin/claude` (fallback). Sobrescrever via `CLAUDE_BIN`.

### GitHub CLI (`gh`)

**Onde usado**: 
- `gh_pr_list` (heartbeat.py:158): `gh pr list --json ...`
- `fetch_bot_comments` (heartbeat.py:179): `gh api repos/.../issues/<n>/comments --jq ...`
- Pelo próprio Claude dentro do `code-review.md`: `gh pr comment`, `gh pr view`, `gh pr diff`.

**Versão mínima**: precisa de `--paginate`, `--jq`, `--json`. `gh` 2.0+ ok.

**Quebra**: `check_prerequisites` aborta. `gh auth status` precisa retornar 0 (`gh auth login` resolvido).

**Scopes GitHub necessários**: `repo` + `workflow`. Documentado no README.

### SQLite (via stdlib `sqlite3`)

**Onde usado**: `open_db`, `init_db`, `save_review`, `needs_review`, `update_pr_state`, `process_pr`.

**Versão mínima**: SQLite 3.7+ pra WAL mode. Default em qualquer distro moderna.

**Configs**: `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=30000` (heartbeat.py:121-122). Ver [[arquitetura-banco]].

### cron (system)

**Onde usado**: dispara o `heartbeat.py` a cada 5 min. Linha sugerida pelo `install.sh`.

**Alternativa equivalente**: `systemd timer`, mas não tem template no repo. Cron é o default.

**Quebra**: heartbeat só roda quando alguém invoca manualmente. Sem reviews automáticos.

### POSIX `fcntl`

**Onde usado**: `main()` (heartbeat.py:351-356) — lock global de tick.

**Quebra em Windows**: `import fcntl` → ImportError. Repo declara Linux/macOS only.

---

## Runtime opcionais

### datasette

**Onde usado**: visualizador web read-only do `state.db`.

**Como instalar**: `install.sh` pergunta. Faz `pip install --user --break-system-packages datasette`.

**Service**: `systemd/datasette-heartbeat.service` → roda em `:8001`.

**Sem ele**: nada quebra. Consultas via `sqlite3 cli` ou Python script (README §Operação tem exemplos).

### `systemd --user`

**Onde usado**: roda o `datasette` como service.

**Sem ele**: dá pra rodar `datasette serve` manualmente. Quebra de cosmético (não persiste reboot sem `loginctl enable-linger`).

### `loginctl enable-linger`

**Onde usado**: pra `systemd --user` rodar mesmo sem login.

**Sem ele**: datasette só roda enquanto o user está logado.

---

## Build-time / dev (nenhuma)

- Sem `requirements.txt`, `pyproject.toml`, `Pipfile`. Decisão consciente — só stdlib.
- Sem `package.json`, `Makefile`, `pre-commit`. Sem CI.
- Sem deps de teste (porque sem testes, ver [[tech-debt]] §TD-001).

---

## Grafo textual de imports/chamadas

```
heartbeat.py
├── stdlib (fcntl, sqlite3, subprocess, json, logging, pathlib, datetime, shutil, os, sys)
├── subprocess.run([CLAUDE_BIN, ...]) ──► claude CLI ──► gh CLI ──► GitHub API
│                                              ↓
│                                       commands/code-review.md (instalado via symlink)
└── subprocess.run([GH_BIN, ...]) ──► gh CLI ──► GitHub API

install.sh
├── command -v claude/gh/python3 (validação)
├── ln -sf ──► symlinks em ~/.claude/heartbeat/ e ~/.claude/commands/
├── importlib.util.spec_from_file_location ──► invoca init_db do heartbeat
├── pip install --user datasette (opcional)
└── systemctl --user enable datasette-heartbeat (opcional)

systemd/datasette-heartbeat.service
└── ExecStart=%h/.local/bin/datasette serve %h/.claude/heartbeat/state.db ...
```

## Regras e Invariantes

- **Stdlib only no `heartbeat.py`** — adicionar dep externa requer ADR. Razão histórica: simplicidade radical, sem supply-chain risk, install trivial.
- **Versões mínimas declaradas são contratos** — Python ≥3.10, gh ≥2.0, SQLite ≥3.7 (WAL). Subir mínimo requer atualizar `install.sh` e documentação.
- **CLIs externos (`claude`, `gh`) são pré-requisitos do user** — heartbeat não os instala, só valida via `check_prerequisites`.
- **Opcionais (datasette, systemd, loginctl) podem faltar sem quebrar nada** — separação rígida entre runtime essencial e nice-to-have.

## Anomalias / pontos de atenção

- **Claude e gh são CLIs externos** — não há mock pra teste unitário fácil. Ver [[tech-debt]] §TD-001.
- **`subprocess.run` com `capture_output=True` em PRs gigantes**: stdout do Claude pode passar de MB. Hoje é truncado pra 5000 chars antes de salvar em `log` (heartbeat.py:288). Sem limite no buffer em si — risco teórico de OOM em PR enorme + prompt verbose.
- **`gh api ... --paginate`** em PRs com 100+ comentários do bot: ok hoje (`jq` filtra na origem). Se algum repo bizarro tiver 10k comentários do bot, vira lento. Não vai acontecer.
- **`--break-system-packages`** no `install.sh` pra datasette: necessário em distros novas (Debian 12+, Ubuntu 23.04+) por PEP 668. Aceitável porque é install opcional escopado a `--user`.
