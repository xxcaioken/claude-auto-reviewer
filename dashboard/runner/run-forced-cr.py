#!/usr/bin/env python3
"""
run-forced-cr.py — força um code-review num PR específico, ignorando o
filtro de deduplicação do heartbeat. Spawned em background pelo CGI.

Uso: run-forced-cr.py <pr_url> <job_id>
"""
import datetime
import fcntl
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Importa do heartbeat.py (mesmo dir do state.db por convenção do install.sh).
HEARTBEAT_DIR = Path(os.environ.get(
    "HEARTBEAT_DIR", Path.home() / ".claude" / "heartbeat"))
sys.path.insert(0, str(HEARTBEAT_DIR))
import heartbeat  # noqa: E402

FORCED_DIR = HEARTBEAT_DIR / "forced"
DONE_DIR = FORCED_DIR / "done"
LOG_FILE = HEARTBEAT_DIR / "logs" / "forced-cr.log"
LOCKFILE = HEARTBEAT_DIR / "heartbeat.lock"
LOCK_WAIT_SEC = 60
KEEP_DONE = 50

URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/pull/(?P<num>\d+)$"
)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def setup_logging():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stderr),
        ],
    )


def write_job(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def load_repos_map():
    """Mapeia github_repo (ex.: 'nec-plus-ultra/hinc-dashboards-backend')
    -> nome curto do repo (ex.: 'hinc-dashboards-backend'), pra cravar
    o campo `repo` na tabela igual o heartbeat faz."""
    out = {}
    for line in (HEARTBEAT_DIR / "repos.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) < 3:
            continue
        name, _path, github_repo = parts[0], parts[1], parts[2]
        enabled = parts[3].strip() if len(parts) > 3 else "1"
        if enabled == "0":
            continue
        out[github_repo] = name
    return out


def gh_pr_dict(url):
    """gh pr view <url> → dict no shape que heartbeat.save_review espera."""
    result = subprocess.run(
        [heartbeat.GH_BIN, "pr", "view", url,
         "--json", "number,headRefOid,isDraft,title,author,state,url"],
        capture_output=True, text=True, timeout=heartbeat.GH_TIMEOUT, check=True,
    )
    return json.loads(result.stdout)


def main():
    if len(sys.argv) != 3:
        print("usage: run-forced-cr.py <pr_url> <job_id>", file=sys.stderr)
        sys.exit(2)
    url, job_id = sys.argv[1], sys.argv[2]
    setup_logging()
    log = logging.getLogger("forced")

    m = URL_RE.match(url)
    if not m:
        log.error("job %s: URL inválida: %r", job_id, url)
        sys.exit(2)

    owner = m.group("owner")
    repo_short = m.group("repo")
    github_repo = f"{owner}/{repo_short}"
    pr_number = int(m.group("num"))

    FORCED_DIR.mkdir(parents=True, exist_ok=True)
    DONE_DIR.mkdir(parents=True, exist_ok=True)
    job_path = FORCED_DIR / f"{job_id}.json"
    done_path = DONE_DIR / f"{job_id}.json"

    state = {
        "job_id": job_id,
        "url": url,
        "repo": github_repo,
        "pr_number": pr_number,
        "status": "pending",
        "pid": os.getpid(),
        "started_at": now_iso(),
        "finished_at": None,
        "comment_id": None,
        "runned": None,
        "rc": None,
        "log_tail": "",
    }
    write_job(job_path, state)
    log.info("job %s: pending, pid=%d, url=%s", job_id, os.getpid(), url)

    # Resolve nome curto do repo (heartbeat usa esse formato em code_reviews.repo)
    repos_map = load_repos_map()
    if github_repo not in repos_map:
        log.error("job %s: repo %s não está em repos.txt enabled=1",
                  job_id, github_repo)
        state.update(status="failed", finished_at=now_iso(),
                     log_tail="repo not in repos.txt enabled=1")
        write_job(job_path, state)
        os.replace(job_path, done_path)
        sys.exit(3)
    repo_name = repos_map[github_repo]

    # Adquire o lock — bloqueia até LOCK_WAIT_SEC se tick rolar
    LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
    lock_fh = open(LOCKFILE, "w")
    try:
        # Espera não-bloqueante com timeout manual
        import time
        deadline = time.monotonic() + LOCK_WAIT_SEC
        while True:
            try:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    log.error("job %s: lock timeout após %ds", job_id, LOCK_WAIT_SEC)
                    state.update(status="failed", finished_at=now_iso(),
                                 log_tail="lock timeout (heartbeat tick em andamento)")
                    write_job(job_path, state)
                    os.replace(job_path, done_path)
                    sys.exit(4)
                time.sleep(1)

        state["status"] = "running"
        write_job(job_path, state)
        log.info("job %s: lock adquirido, status=running", job_id)

        # Busca dados do PR via gh
        try:
            pr = gh_pr_dict(url)
        except Exception as e:
            log.exception("job %s: gh pr view falhou", job_id)
            state.update(status="failed", finished_at=now_iso(),
                         log_tail=f"gh pr view error: {e}")
            write_job(job_path, state)
            os.replace(job_path, done_path)
            sys.exit(5)

        # Snapshot dos comentários do bot ANTES de chamar claude
        before_ids = {c["id"] for c in heartbeat.fetch_bot_comments(github_repo, pr_number)}

        # Invoca claude (5-10 min)
        rc, stdout, stderr = heartbeat.invoke_claude(url)
        state["rc"] = rc
        log_text = f"rc={rc}\n--- stdout ---\n{stdout[:5000]}\n--- stderr ---\n{stderr[:2000]}"
        state["log_tail"] = log_text[-2000:]

        # Detecta comment novo do bot
        after = heartbeat.fetch_bot_comments(github_repo, pr_number)
        new_comments = [c for c in after if c["id"] not in before_ids]

        # Conecta na DB e arquiva como o heartbeat faz
        conn = heartbeat.open_db()
        try:
            heartbeat.init_db(conn)
            if rc == 0 and new_comments:
                new_comments.sort(key=lambda c: c["created_at"])
                new = new_comments[-1]
                heartbeat.save_review(
                    conn, repo_name, pr,
                    body=new["body"], comment_id=str(new["id"]),
                    log_text=log_text, runned=True,
                )
                state.update(status="done", runned=True,
                             comment_id=str(new["id"]),
                             finished_at=now_iso())
                log.info("job %s: ✓ comment_id=%s", job_id, new["id"])
            else:
                heartbeat.save_review(
                    conn, repo_name, pr,
                    log_text=log_text, runned=False,
                )
                state.update(status="done" if rc == 0 else "failed",
                             runned=False, finished_at=now_iso())
                log.info("job %s: ⊘ rodou mas não publicou (rc=%d)", job_id, rc)
        finally:
            conn.close()

        write_job(job_path, state)

    finally:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        lock_fh.close()

    # Move pra done/ e poda
    os.replace(job_path, done_path)
    done_files = sorted(DONE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    for old in done_files[:-KEEP_DONE]:
        try:
            old.unlink()
        except OSError:
            pass

    log.info("job %s: finalizado, arquivado em %s", job_id, done_path)


if __name__ == "__main__":
    main()
