#!/usr/bin/env python3
"""
Heartbeat — disparador automático de Code Review por PR.

Roda via cron (default: a cada 5 min). Pra cada repo em `repos.txt`:
  1. Lista PRs abertos via `gh pr list`.
  2. Pula draft, label `skip-code-review`, ou head_sha já revisado/tentado.
  3. Pra cada PR a revisar:
     a. Snapshot de comentários do bot existentes no PR.
     b. Invoca `claude --permission-mode bypassPermissions -p '/code-review <url> publique'`.
        Claude usa `gh` ele mesmo pra postar o comentário diretamente no PR.
     c. Detecta comentário novo do bot (com marcador HTML) e arquiva no SQLite.
     d. Se não postou nada, ainda registra a tentativa (runned=0) pra evitar retry
        no mesmo head_sha.

Estado, logs, repos.txt e lockfile vivem em $HEARTBEAT_DIR
(default: ~/.claude/heartbeat).

Schema da tabela append-only `code_reviews`:
  pr_name, runned_at, cr_description, pr_creator (centrais)
  + log, runned (status da execução)
  + colunas operacionais (repo, pr_number, pr_url, head_sha, comment_id, pr_state).

Configuração via env vars (todas opcionais):
  HEARTBEAT_DIR       — diretório de dados (default: ~/.claude/heartbeat)
  CLAUDE_BIN          — path do binário claude (default: which claude)
  GH_BIN              — path do binário gh (default: which gh)
  CLAUDE_CWD          — cwd onde claude é invocado (default: $HOME)
  MARKER              — marcador HTML do comentário (default: <!-- code-review-bot:v1 -->)
  SKIP_LABEL          — label que pula revisão (default: skip-code-review)
  CLAUDE_TIMEOUT      — segundos por revisão (default: 600)
  GH_TIMEOUT          — segundos por chamada gh (default: 60)
  SQLITE_TIMEOUT      — segundos pra connect SQLite (default: 30)
"""
import datetime
import fcntl
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

# --- Configuração via env vars (com defaults sensatos) ---

HEARTBEAT_DIR = Path(os.environ.get("HEARTBEAT_DIR",
                                    Path.home() / ".claude" / "heartbeat"))
DB_PATH = HEARTBEAT_DIR / "state.db"
REPOS_FILE = HEARTBEAT_DIR / "repos.txt"
LOCKFILE = HEARTBEAT_DIR / "heartbeat.lock"
LOGS_DIR = HEARTBEAT_DIR / "logs"

CLAUDE_BIN = (os.environ.get("CLAUDE_BIN")
              or shutil.which("claude")
              or str(Path.home() / ".local" / "bin" / "claude"))
GH_BIN = (os.environ.get("GH_BIN")
          or shutil.which("gh")
          or "/usr/bin/gh")
CLAUDE_CWD = os.environ.get("CLAUDE_CWD", str(Path.home()))

MARKER = os.environ.get("MARKER", "<!-- code-review-bot:v1 -->")
SKIP_LABEL = os.environ.get("SKIP_LABEL", "skip-code-review")
CLAUDE_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "600"))
GH_TIMEOUT = int(os.environ.get("GH_TIMEOUT", "60"))
SQLITE_TIMEOUT = int(os.environ.get("SQLITE_TIMEOUT", "30"))

# --- Setup de logging ---

HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "heartbeat.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("heartbeat")


# --- Schema SQLite ---

SCHEMA = """
CREATE TABLE IF NOT EXISTS pr_state (
  repo TEXT NOT NULL,
  pr_number INTEGER NOT NULL,
  head_sha TEXT NOT NULL,
  is_draft INTEGER NOT NULL,
  state TEXT NOT NULL,
  last_seen_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
  PRIMARY KEY (repo, pr_number)
);

CREATE TABLE IF NOT EXISTS code_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repo TEXT NOT NULL,
  pr_number INTEGER NOT NULL,
  pr_name TEXT NOT NULL,
  pr_creator TEXT NOT NULL,
  pr_url TEXT NOT NULL,
  head_sha TEXT NOT NULL,
  cr_description TEXT NOT NULL DEFAULT '',
  pr_state TEXT NOT NULL,
  comment_id TEXT,
  log TEXT,
  runned INTEGER NOT NULL DEFAULT 0,
  runned_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE INDEX IF NOT EXISTS idx_cr_pr_time ON code_reviews(repo, pr_number, runned_at DESC);
CREATE INDEX IF NOT EXISTS idx_cr_pr_sha ON code_reviews(repo, pr_number, head_sha);
"""


def open_db():
    """sqlite3.connect com WAL + timeout (resolve 'database is locked')."""
    conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(conn):
    """DDL idempotente + migrations pra DBs criados antes do schema atual."""
    conn.executescript(SCHEMA)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(code_reviews)")}
    if "log" not in cols:
        log.info("migrating: ADD COLUMN log")
        conn.execute("ALTER TABLE code_reviews ADD COLUMN log TEXT")
    if "runned" not in cols:
        log.info("migrating: ADD COLUMN runned")
        conn.execute("ALTER TABLE code_reviews ADD COLUMN runned INTEGER NOT NULL DEFAULT 0")
    conn.commit()


def load_repos():
    repos = []
    with REPOS_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) < 3:
                log.warning("Linha mal-formada em repos.txt: %r", line)
                continue
            name, path, github_repo = parts[0], parts[1], parts[2]
            enabled = parts[3] if len(parts) > 3 else "1"
            if enabled.strip() == "0":
                continue
            repos.append((name, path, github_repo))
    return repos


def gh_pr_list(github_repo):
    try:
        result = subprocess.run(
            [GH_BIN, "pr", "list",
             "--repo", github_repo,
             "--state", "open",
             "--json", "number,headRefOid,isDraft,title,url,author,labels,state"],
            capture_output=True, text=True, timeout=GH_TIMEOUT, check=True,
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        log.error("gh pr list falhou em %s: %s", github_repo, e.stderr[:500])
        return []
    except subprocess.TimeoutExpired:
        log.error("gh pr list timeout em %s", github_repo)
        return []
    except json.JSONDecodeError as e:
        log.error("JSON inválido de gh pr list (%s): %s", github_repo, e)
        return []


def fetch_bot_comments(github_repo, pr_number):
    """Retorna lista de comentários do PR cujo body começa com o marcador HTML."""
    try:
        result = subprocess.run(
            [GH_BIN, "api", f"repos/{github_repo}/issues/{pr_number}/comments",
             "--paginate",
             "--jq", f'.[] | select(.body | startswith("{MARKER}")) | {{id: .id, body: .body, created_at: .created_at}}'],
            capture_output=True, text=True, timeout=GH_TIMEOUT, check=True,
        )
        comments = []
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                try:
                    comments.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return comments
    except subprocess.CalledProcessError as e:
        log.warning("  fetch_bot_comments(#%d) falhou: %s", pr_number, e.stderr[:200])
        return []
    except subprocess.TimeoutExpired:
        log.warning("  fetch_bot_comments(#%d) timeout", pr_number)
        return []


def needs_review(conn, repo_name, pr):
    """Pula draft, skip-label, ou (repo, pr, head_sha) já registrado em code_reviews."""
    pr_number = pr["number"]
    head_sha = pr["headRefOid"]

    if pr.get("isDraft"):
        return False
    labels = [l.get("name", "") for l in pr.get("labels", []) or []]
    if SKIP_LABEL in labels:
        return False

    row = conn.execute(
        "SELECT 1 FROM code_reviews WHERE repo=? AND pr_number=? AND head_sha=? LIMIT 1",
        (repo_name, pr_number, head_sha),
    ).fetchone()
    return row is None


def update_pr_state(conn, repo_name, pr):
    conn.execute("""
        INSERT INTO pr_state (repo, pr_number, head_sha, is_draft, state, last_seen_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(repo, pr_number) DO UPDATE SET
            head_sha = excluded.head_sha,
            is_draft = excluded.is_draft,
            state = excluded.state,
            last_seen_at = CURRENT_TIMESTAMP
    """, (
        repo_name,
        pr["number"],
        pr["headRefOid"],
        1 if pr.get("isDraft") else 0,
        pr.get("state", "OPEN"),
    ))
    conn.commit()


def invoke_claude(pr_url):
    """Roda claude bypassPermissions -p '/code-review <url> publique'.
    Retorna (rc, stdout, stderr)."""
    cmd = [CLAUDE_BIN,
           "--permission-mode", "bypassPermissions",
           "-p", f"/code-review {pr_url} publique"]
    log.info("  $ %s (cwd=%s)", " ".join(cmd), CLAUDE_CWD)
    try:
        result = subprocess.run(
            cmd,
            cwd=CLAUDE_CWD,
            capture_output=True, text=True,
            timeout=CLAUDE_TIMEOUT,
        )
        return (result.returncode, result.stdout, result.stderr)
    except subprocess.TimeoutExpired as e:
        return (-1, "", f"TIMEOUT após {CLAUDE_TIMEOUT}s: {e}")


def save_review(conn, repo_name, pr, *, body="", comment_id=None, log_text="", runned=False):
    conn.execute("""
        INSERT INTO code_reviews (
            repo, pr_number, pr_name, pr_creator, pr_url,
            head_sha, cr_description, pr_state, comment_id, log, runned
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        repo_name,
        pr["number"],
        pr.get("title", ""),
        (pr.get("author") or {}).get("login", "unknown"),
        pr["url"],
        pr["headRefOid"],
        body or "",
        pr.get("state", "OPEN"),
        comment_id,
        log_text,
        1 if runned else 0,
    ))
    conn.commit()


def process_pr(conn, repo_name, github_repo, pr):
    """Executa CR no PR: snapshot → claude → detecta novo comment → salva."""
    pr_number = pr["number"]

    before_ids = {c["id"] for c in fetch_bot_comments(github_repo, pr_number)}
    rc, stdout, stderr = invoke_claude(pr["url"])
    log_text = f"rc={rc}\n--- stdout ---\n{stdout[:5000]}\n--- stderr ---\n{stderr[:2000]}"

    if rc != 0:
        log.error("  claude rc=%d", rc)
        save_review(conn, repo_name, pr, log_text=log_text, runned=False)
        return

    after = fetch_bot_comments(github_repo, pr_number)
    new_comments = [c for c in after if c["id"] not in before_ids]

    if new_comments:
        new_comments.sort(key=lambda c: c["created_at"])
        new = new_comments[-1]
        log.info("  ✓ publicado pelo claude: comment_id=%s", new["id"])
        save_review(conn, repo_name, pr,
                    body=new["body"], comment_id=str(new["id"]),
                    log_text=log_text, runned=True)
    else:
        log.info("  ⊘ claude rodou mas não publicou comentário")
        save_review(conn, repo_name, pr, log_text=log_text, runned=False)


def process_repo(conn, repo_name, github_repo):
    log.info("Processando %s (%s)", repo_name, github_repo)
    prs = gh_pr_list(github_repo)
    log.info("  %d PR(s) aberto(s)", len(prs))

    for pr in prs:
        update_pr_state(conn, repo_name, pr)

        if not needs_review(conn, repo_name, pr):
            continue

        log.info("  → Revisando #%d (%s) sha=%s",
                 pr["number"], pr.get("title", "")[:60], pr["headRefOid"][:8])
        try:
            process_pr(conn, repo_name, github_repo, pr)
        except Exception:
            log.exception("  erro processando PR #%d", pr["number"])


def check_prerequisites():
    if not Path(CLAUDE_BIN).exists():
        log.error("claude não encontrado em %s (set CLAUDE_BIN ou instale claude CLI)", CLAUDE_BIN)
        return False
    if not Path(GH_BIN).exists():
        log.error("gh não encontrado em %s (set GH_BIN ou instale gh CLI)", GH_BIN)
        return False
    try:
        subprocess.run([GH_BIN, "auth", "status"],
                       capture_output=True, check=True, timeout=10)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.error("gh não autenticado (rode `gh auth login`): %s", e)
        return False
    if not REPOS_FILE.exists():
        log.error("repos.txt não existe em %s (copie repos.txt.example e edite)", REPOS_FILE)
        return False
    return True


def main():
    log.info("=== tick start ===")

    lockfile = open(LOCKFILE, "w")
    try:
        fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.info("outro tick em progresso, abortando este (sem erro)")
        return

    if not check_prerequisites():
        log.error("pré-requisitos falharam, abortando")
        sys.exit(1)

    conn = open_db()
    try:
        init_db(conn)
        repos = load_repos()
        log.info("monitorando %d repo(s)", len(repos))
        for name, path, github_repo in repos:
            try:
                process_repo(conn, name, github_repo)
            except Exception:
                log.exception("erro processando %s", name)
    finally:
        conn.close()

    log.info("=== tick end ===")


if __name__ == "__main__":
    main()
