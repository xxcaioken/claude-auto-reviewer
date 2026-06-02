---
title: Arquitetura — claude-auto-reviewer
type: architecture
status: active
tags:
  - backend
  - pattern
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[arquitetura-banco]]"
  - "[[regras-negocio]]"
  - "[[regras-prompt-review]]"
  - "[[modulo-heartbeat]]"
  - "[[dependencias]]"
tier: 1
---

# Arquitetura — claude-auto-reviewer

Sistema MVP de **code review automático em PRs do GitHub** via Claude Code CLI. Single-process, single-machine, sem servidor próprio. Cron dispara um Python a cada 5 min; o Python chama o `claude` CLI; o `claude` posta o comentário no PR usando `gh`. Estado persiste em SQLite local.

## Diagrama de fluxo

```
┌─────────┐  */5min   ┌──────────────┐  gh pr list   ┌────────┐
│  cron   │ ────────► │ heartbeat.py │ ────────────► │ GitHub │
└─────────┘           └──────┬───────┘               └────────┘
                             │ pra cada PR não revisado
                             ▼
                    ┌──────────────────┐
                    │ claude -p        │  gh pr comment
                    │ /code-review     │ ────────────►  PR (comment)
                    │ <url> publique   │
                    └────────┬─────────┘
                             │ snapshot before/after detecta novo comment
                             ▼
                    ┌──────────────────┐
                    │ state.db (SQLite)│
                    │ append-only      │
                    └──────────────────┘
```

## Componentes (na ordem do fluxo)

### 1. Cron (externo)
- Linha sugerida pelo `install.sh`: `*/5 * * * * /usr/bin/python3 ~/.claude/heartbeat/heartbeat.py >/dev/null 2>&1`
- Sem retry interno — se um tick falha, o próximo (5 min depois) reprocessa.
- Lock `fcntl` global garante que ticks paralelos abortem em vez de duplicar (ver [[regras-negocio]] §Idempotência).

### 2. `heartbeat/heartbeat.py` (entrypoint)
Single-file, só stdlib. ~380 linhas. Estruturado em funções puras + `main()` orquestrador. Sem classes. Sem deps externas.

**Funções principais** (linha aproximada):
| Função | Linha | Responsabilidade |
|---|---|---|
| `open_db` / `init_db` | 118 / 126 | Conexão SQLite WAL + DDL idempotente + migrations ALTER TABLE |
| `load_repos` | 139 | Parse pipe-separated de `repos.txt` (`name|path|owner/repo|enabled`) |
| `gh_pr_list` | 158 | `gh pr list --json` → lista de dicts; engole erro e retorna `[]` |
| `fetch_bot_comments` | 179 | `gh api ... | jq` filtra por marcador HTML (snapshot before/after) |
| `needs_review` | 204 | Pula draft / `skip-code-review` label / `head_sha` já registrado |
| `update_pr_state` | 222 | UPSERT em `pr_state` (último estado conhecido por PR) |
| `invoke_claude` | 241 | `subprocess.run([claude, --permission-mode bypassPermissions, -p, ...])` |
| `save_review` | 260 | INSERT append-only em `code_reviews` |
| `process_pr` | 282 | snapshot → invoke → diff de comments → save |
| `process_repo` | 310 | itera PRs do repo, chama `process_pr` pra cada |
| `check_prerequisites` | 329 | Valida claude/gh/auth/repos.txt antes do `main` loop |
| `main` | 348 | Lock + check + init_db + itera repos |

Ver detalhes em [[modulo-heartbeat]].

### 3. `commands/code-review.md` (prompt do reviewer)
- ~300 linhas. É o **coração** do sistema — toda inteligência de review vive aqui.
- Instalado via symlink em `~/.claude/commands/code-review.md` (comando global do Claude Code).
- Detecta modo (`heartbeat` se argumentos têm "publique"; `interativo` caso contrário).
- Em modo heartbeat: posta direto via `gh pr comment ... --body-file -`. Não retorna o markdown.
- Saída assinada pelo marcador HTML `<!-- code-review-bot:v1 -->` (contrato com `fetch_bot_comments`).
- Ver [[regras-prompt-review]] pra as regras estritas que o prompt impõe.

### 4. `state.db` (SQLite)
- **WAL mode** + `busy_timeout=30000` ms.
- 2 tabelas: `pr_state` (UPSERT, último estado) e `code_reviews` (APPEND-ONLY, 1 linha por execução).
- Schema completo + invariantes em [[arquitetura-banco]].

### 5. Datasette (opcional, fora do hot path)
- Service systemd `datasette-heartbeat.service` — read-only browser pro `state.db`.
- Rodando em `:8001`. Não interfere no heartbeat (read-only não bloqueia WAL).
- Instalado opcionalmente pelo `install.sh`.

## Padrões usados

- **Snapshot before/after** pra detectar novo comentário do bot. Não confia no `stdout` do `claude`, confia no GitHub. Trade-off: 2 chamadas `gh api` por PR.
- **Append-only**: 1 linha por execução de CR. Nunca UPDATE em `code_reviews`. Push novo no PR → nova linha (mesmo `pr_number`, `head_sha` diferente). Ver [[arquitetura-banco]].
- **Idempotência por `(repo, pr_number, head_sha)`**: filtro em `needs_review`. Re-revisa se commit muda; nunca duplica no mesmo commit.
- **Fail-soft**: erros de `gh` → log warning + `[]`. Erros de `claude` → `runned=0` + log. Tick segue pro próximo PR/repo.
- **Lock fcntl global**: `LOCK_EX | LOCK_NB`. Só 1 tick rodando por vez; ticks que chocariam abortam silenciosamente.
- **Symlinks pra deploy**: `install.sh` linka `heartbeat.py` e `code-review.md` do repo. `git pull` propaga mudanças sem reinstalar.

## Stack

- **Python 3.10+** stdlib (sqlite3, fcntl, subprocess, json, logging, pathlib, datetime, shutil, os, sys).
- **Claude Code CLI** (modelo Claude — Opus/Sonnet).
- **gh CLI** com scopes `repo` + `workflow`.
- **SQLite 3** com WAL.
- **cron** (Linux/macOS). Windows não suportado (depende de `fcntl`).
- **Opcional**: `datasette` (web UI read-only), `systemd --user` (rodar o datasette).

Ver [[dependencias]] pra a árvore completa.

## Regras e Invariantes

- **1 tick por vez na mesma máquina** — garantido por lock fcntl global em `heartbeat.py:351`. Ticks concorrentes abortam silenciosamente. Sem isso, revisões duplicariam.
- **Idempotência por `(repo, pr_number, head_sha)`** — chave do `needs_review`. Mudar essa chave muda toda a semântica de retry. Ver [[ADR-004-dedup-head-sha]].
- **Snapshot before/after é a fonte da verdade**, não o stdout do Claude. Se essa premissa cair, `process_pr` precisa ser re-arquitetado.
- **Heartbeat é orquestrador burro**, Claude é cérebro. Toda inteligência de review vive em `commands/code-review.md`. Mover lógica de filtro pro `heartbeat.py` viola o contrato de [[ADR-005-claude-cli-stdin]].
- **Sem deps externas em runtime do heartbeat** — só stdlib + CLIs (`claude`, `gh`). Quebra o "instalar é só copiar".
- **Symlinks no install.sh** são a base do modelo de update. Trocar por cópia exige refazer fluxo de update ([[ADR-003-symlinks-no-install]]).

## O que NÃO faz (escopo declarado)

- Não tem servidor próprio (sem HTTP, sem webhook).
- Não suporta paralelismo entre PRs (1 PR por vez por design — ver [[tech-debt]]).
- Não tem retry interno em falha do Claude (próximo tick reprocessa).
- Não edita comentários antigos (`--edit-last`) — sempre cria novo (ver [[ADR-001-cron-vs-webhook]]).
- Não tem testes automatizados ainda (ver [[tech-debt]]).
