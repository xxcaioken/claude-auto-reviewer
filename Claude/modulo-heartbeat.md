---
title: Módulo heartbeat.py — anatomia
type: anatomy
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
  - "[[arquitetura-banco]]"
  - "[[regras-negocio]]"
  - "[[error-handling]]"
tier: 2
---

# `heartbeat.py` — anatomia funcional

Single-file. Stdlib only. ~380 linhas. Sem classes — só funções puras + `main()` orquestrador.

## Layout do arquivo

| Linhas | Bloco |
|---|---|
| 1-34 | Docstring com a arquitetura completa |
| 35-44 | Imports (stdlib only: datetime, fcntl, json, logging, os, shutil, sqlite3, subprocess, sys, pathlib) |
| 46-67 | Configuração via env vars (com defaults sensatos) |
| 69-81 | Setup de logging (FileHandler + StreamHandler) |
| 84-115 | SCHEMA SQL (string com 2 CREATE TABLE + 2 CREATE INDEX) |
| 118-123 | `open_db` |
| 126-136 | `init_db` (DDL + migrations) |
| 139-155 | `load_repos` |
| 158-176 | `gh_pr_list` |
| 179-201 | `fetch_bot_comments` |
| 204-219 | `needs_review` |
| 222-238 | `update_pr_state` |
| 241-257 | `invoke_claude` |
| 260-279 | `save_review` |
| 282-307 | `process_pr` |
| 310-326 | `process_repo` |
| 329-345 | `check_prerequisites` |
| 348-375 | `main` (lock + check + init + loop) |
| 378-379 | `if __name__ == "__main__": main()` |

## Funções (em ordem de chamada no fluxo)

### `main()` (heartbeat.py:348)

Orquestrador. Sequência:
1. Log `=== tick start ===`.
2. Abre lockfile + `fcntl.flock(LOCK_EX | LOCK_NB)`. Se falha → `log.info("outro tick em progresso, abortando")` e retorna (sem erro).
3. `check_prerequisites()`. Se False → `sys.exit(1)`.
4. `open_db()` + `init_db(conn)`.
5. `load_repos()` → loop em `process_repo(conn, name, github_repo)`. Try/except por repo (erro não derruba o tick).
6. `conn.close()` em `finally`.
7. Log `=== tick end ===`.

**Lock**: garantido EXCLUSIVE e NON-BLOCKING. Próximo tick que tentar pegar recebe `BlockingIOError` imediato.

### `check_prerequisites()` (heartbeat.py:329)

Validações:
- `Path(CLAUDE_BIN).exists()` 
- `Path(GH_BIN).exists()`
- `subprocess.run([gh, "auth", "status"], timeout=10)` rc=0
- `REPOS_FILE.exists()`

Todas devem passar. Falha → log.error + return False (sem exception).

### `load_repos()` (heartbeat.py:139)

Lê `repos.txt`. Filtra:
- Linha vazia ou começando com `#` → pula.
- Menos de 3 pipes → log.warning + pula.
- `enabled=0` (4º campo) → pula.

Retorna `list[tuple[str, str, str]]`: `(name, path, github_repo)`.

Default `enabled` se ausente: `"1"` (incluído).

### `open_db()` (heartbeat.py:118)

`sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT)` + PRAGMAs:
- `journal_mode=WAL`
- `busy_timeout=30000` (ms)

Retorna conn. Detalhes em [[arquitetura-banco]].

### `init_db(conn)` (heartbeat.py:126)

`conn.executescript(SCHEMA)` (idempotente — CREATE IF NOT EXISTS).

Depois, migrations defensivas:
- Lê `PRAGMA table_info(code_reviews)`.
- Se faltar `log` → ALTER TABLE ADD COLUMN.
- Se faltar `runned` → ALTER TABLE ADD COLUMN.

Pra adicionar coluna nova: adicionar `CREATE TABLE` no SCHEMA + bloco `if "nova_col" not in cols` aqui.

### `process_repo(conn, repo_name, github_repo)` (heartbeat.py:310)

Loop principal por repo:
1. `gh_pr_list(github_repo)` → lista de PRs.
2. Pra cada PR:
   - `update_pr_state(conn, repo_name, pr)` (sempre — atualiza cache).
   - Se não `needs_review` → `continue`.
   - Log "→ Revisando #N (titulo) sha=xxxxx".
   - `process_pr(conn, repo_name, github_repo, pr)` com try/except.

### `gh_pr_list(github_repo)` (heartbeat.py:158)

```bash
gh pr list --repo <r> --state open \
  --json number,headRefOid,isDraft,title,url,author,labels,state
```

Retorna list[dict] do JSON. Em qualquer erro (CalledProcessError, TimeoutExpired, JSONDecodeError) → log + retorna `[]`. Sem retry.

### `needs_review(conn, repo_name, pr)` (heartbeat.py:204)

Decide se PR deve ser revisado **agora**.

Pula se:
- `pr["isDraft"]` truthy.
- `SKIP_LABEL` está em `[l["name"] for l in pr["labels"]]`.
- Existe linha em `code_reviews` com `(repo_name, pr["number"], pr["headRefOid"])`.

Caso contrário → True.

**Importante**: a 3ª condição não filtra por `runned`. Linha com `runned=0` BLOQUEIA retry. Pra retry manual, deletar a linha. Ver [[regras-negocio]] §1 e [[runbook-debugar-revisao-falhada]].

### `update_pr_state(conn, repo_name, pr)` (heartbeat.py:222)

UPSERT em `pr_state` por `(repo, pr_number)`. Sempre executa, mesmo se `needs_review` vai retornar False.

Campos: `head_sha`, `is_draft` (0/1), `state` (OPEN/MERGED/CLOSED), `last_seen_at` (CURRENT_TIMESTAMP).

### `process_pr(conn, repo_name, github_repo, pr)` (heartbeat.py:282)

Coração do fluxo de revisão.

1. **Snapshot before**: `before_ids = {c["id"] for c in fetch_bot_comments(...)}`.
2. **Invocar Claude**: `rc, stdout, stderr = invoke_claude(pr["url"])`.
3. **Construir log_text** com rc + stdout truncado em 5000 chars + stderr truncado em 2000.
4. Se `rc != 0`: log.error + `save_review(runned=False, log_text)` + return.
5. **Snapshot after**: `after = fetch_bot_comments(...)`.
6. **Diff**: `new_comments = [c for c in after if c["id"] not in before_ids]`.
7. Se `new_comments`:
   - Ordena por `created_at`, pega o último.
   - log.info "✓ publicado pelo claude: comment_id=X"
   - `save_review(body=new["body"], comment_id=str(new["id"]), runned=True)`.
8. Senão:
   - log.info "⊘ claude rodou mas não publicou comentário"
   - `save_review(runned=False, log_text)`.

**Por que pega o último comentário (não único)**: se Claude postou mais de 1 (improvável mas possível), o mais recente é o oficial. Os anteriores seriam ruído.

### `fetch_bot_comments(github_repo, pr_number)` (heartbeat.py:179)

```bash
gh api repos/<r>/issues/<n>/comments --paginate \
  --jq '.[] | select(.body | startswith("<MARKER>")) | {id, body, created_at}'
```

Retorna `list[dict]` com chaves `id`, `body`, `created_at`. Erros → warning + `[]`.

`--paginate`: handle PRs com 100+ comentários do bot (improvável, mas defensivo).

`--jq`: filtra na origem. `MARKER` é interpolado na string Python (cuidado: se MARKER tivesse aspas duplas, quebraria — não acontece com default).

### `invoke_claude(pr_url)` (heartbeat.py:241)

```bash
claude --permission-mode bypassPermissions -p "/code-review <url> publique"
```

Com `cwd=CLAUDE_CWD` (default `$HOME`).

Retorna `(rc, stdout, stderr)`. Timeout → retorna `(-1, "", "TIMEOUT após Ns: ...")`.

**Não captura exceções não-timeout** — propagariam pra `process_pr` que tem `try/except Exception` no `process_repo`.

### `save_review(conn, repo_name, pr, *, body, comment_id, log_text, runned)` (heartbeat.py:260)

INSERT em `code_reviews`. Sempre.

Parâmetros keyword-only depois de `pr` — proteção contra chamadas ambíguas.

Valores extraídos do `pr`:
- `pr["number"]`, `pr["url"]`, `pr["headRefOid"]`
- `pr.get("title", "")` → `pr_name`
- `(pr.get("author") or {}).get("login", "unknown")` → `pr_creator` (defensivo, autor pode ser null em PR de bot deletado)
- `pr.get("state", "OPEN")` → `pr_state`

**Sem RETURNING ou last_insert_rowid** — quem chama não precisa do id.

## Variáveis globais (config)

Todas em scope de módulo. Lidas uma vez no import.

```python
HEARTBEAT_DIR = Path(os.environ.get("HEARTBEAT_DIR", ...))
DB_PATH       = HEARTBEAT_DIR / "state.db"
REPOS_FILE    = HEARTBEAT_DIR / "repos.txt"
LOCKFILE      = HEARTBEAT_DIR / "heartbeat.lock"
LOGS_DIR      = HEARTBEAT_DIR / "logs"

CLAUDE_BIN     = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or ...
GH_BIN         = os.environ.get("GH_BIN")     or shutil.which("gh")     or "/usr/bin/gh"
CLAUDE_CWD     = os.environ.get("CLAUDE_CWD", str(Path.home()))

MARKER         = os.environ.get("MARKER", "<!-- code-review-bot:v1 -->")
SKIP_LABEL     = os.environ.get("SKIP_LABEL", "skip-code-review")
CLAUDE_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "600"))
GH_TIMEOUT     = int(os.environ.get("GH_TIMEOUT", "60"))
SQLITE_TIMEOUT = int(os.environ.get("SQLITE_TIMEOUT", "30"))
```

**Side effect no import**: `HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)` e `LOGS_DIR.mkdir(exist_ok=True)`. Importar o módulo cria os diretórios. Usado pelo `install.sh` (`importlib`).

## Padrões usados

- **Pure functions com `conn` injetado**: facilita futuro teste (passar `:memory:` conn). Ver [[infra-testes]].
- **Defensivo em parsing**: `.get(...)` com defaults, `(... or {}).get(...)` pra null.
- **Truncamento defensivo**: stdout em 5000 chars, stderr em 2000. Protege contra PR com diff gigante explodindo o `log_text`.
- **Logging por handler duplo**: file + stdout. Cron captura stdout (`>/dev/null` no exemplo, mas redirecionável). File é a fonte da verdade.

## Anti-patterns evitados

- **Sem retry interno**: deixa pro próximo tick do cron. Simplifica lógica.
- **Sem state em memória entre ticks**: tudo persistente em SQLite. Crash do processo não perde estado.
- **Sem subprocess.Popen com pipes manuais**: usa `subprocess.run` com `capture_output=True` (mais simples, com timeout).

## Regras e Invariantes

- **Side effect no import**: `HEARTBEAT_DIR.mkdir(...)` + `LOGS_DIR.mkdir(...)`. Importar o módulo cria diretórios. Usado pelo `install.sh` via `importlib`.
- **`SCHEMA` constant é fonte da verdade do schema** — toda migration ALTER TABLE em `init_db` precisa de bloco `if "col" not in cols`.
- **`save_review` keyword-only depois de `pr`** — `*` no sig protege contra chamadas posicionais ambíguas. Não relaxar.
- **Stdout truncado em 5000 chars, stderr em 2000** no `process_pr` — protege contra `log` gigante em PRs anormais. Aumentar requer revisar tamanho típico do `state.db`.
- **`process_pr` e `process_repo` têm `try/except Exception`** — erros isolados por PR/repo, nunca derrubam o tick. Remover quebra fail-soft.
- **Funções aceitam `conn` injetado** — facilita testes futuros (`sqlite3.connect(':memory:')`). Não usar conexão global.

## Pontos de mudança previstos

Quando implementar [[tech-debt]] §TD-002 (retry/distinguir causas de `runned=0`):

(testes ver [[infra-testes]])
- Nova coluna `failure_reason` em `code_reviews`.
- `save_review` ganha parâmetro `failure_reason`.
- `process_pr` distingue rc != 0, timeout, sem-comment-publicado, e seta o reason.

Quando implementar §TD-003 (`--edit-last`):
- `process_pr` precisa saber o `comment_id` da revisão anterior. Vem de `SELECT comment_id FROM code_reviews WHERE repo=? AND pr_number=? ORDER BY id DESC LIMIT 1`.
- `invoke_claude` ganha parâmetro `existing_comment_id` → passa pro prompt.
- Prompt usa `gh api PATCH /repos/.../issues/comments/<id>` em vez de `gh pr comment`.
