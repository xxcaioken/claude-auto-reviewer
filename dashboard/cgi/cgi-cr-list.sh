#!/bin/bash
# CGI: retorna últimos N reviews do code_reviews em JSON, junto com
# lista de repos e autores únicos pros selects do filtro.
# Query string: ?limit=200&repo=&author=&status=
set -u

DB="${HEARTBEAT_DIR:-/home/npu/.claude/heartbeat}/state.db"

# parse query string mínima — espera que NGINX já tenha passado
qs="${QUERY_STRING:-}"
limit=200; repo=""; author=""; status=""
IFS='&' read -ra pairs <<< "$qs"
for p in "${pairs[@]}"; do
  k="${p%%=*}"; v="${p#*=}"
  v="${v//+/ }"
  v=$(printf '%b' "${v//%/\\x}")
  case "$k" in
    limit)  [[ "$v" =~ ^[0-9]+$ ]] && limit="$v" ;;
    repo)   repo="$v" ;;
    author) author="$v" ;;
    status) status="$v" ;;
  esac
done
# clamp
if [ "$limit" -gt 500 ]; then limit=500; fi

printf 'Content-Type: application/json; charset=utf-8\r\n'
printf 'Cache-Control: no-store\r\n'
printf '\r\n'

DB="$DB" LIMIT="$limit" REPO="$repo" AUTHOR="$author" STATUS="$status" python3 - <<'PY'
import json
import os
import sqlite3

db = os.environ["DB"]
limit = int(os.environ["LIMIT"])
repo = os.environ.get("REPO", "")
author = os.environ.get("AUTHOR", "")
status = os.environ.get("STATUS", "")

conn = sqlite3.connect(db, timeout=30)
conn.execute("PRAGMA busy_timeout=30000")

where, params = [], []
if repo:
    where.append("repo = ?"); params.append(repo)
if author:
    where.append("pr_creator = ?"); params.append(author)
if status == "ok":
    where.append("runned = 1")
elif status == "failed":
    where.append("runned = 0")
where_sql = ("WHERE " + " AND ".join(where)) if where else ""

reviews = []
for row in conn.execute(f"""
    SELECT id, runned_at, repo, pr_number, pr_name, pr_creator, pr_url,
           head_sha, comment_id, runned, pr_state,
           substr(cr_description, 1, 200) AS cr_preview,
           length(cr_description) AS cr_len
      FROM code_reviews
      {where_sql}
      ORDER BY runned_at DESC
      LIMIT ?
""", params + [limit]):
    reviews.append({
        "id": row[0], "runned_at": row[1], "repo": row[2],
        "pr_number": row[3], "pr_name": row[4], "pr_creator": row[5],
        "pr_url": row[6], "head_sha": row[7], "comment_id": row[8],
        "runned": bool(row[9]), "pr_state": row[10],
        "cr_preview": row[11] or "", "cr_len": row[12] or 0,
    })

repos = [r[0] for r in conn.execute("SELECT DISTINCT repo FROM code_reviews ORDER BY repo")]
authors = [r[0] for r in conn.execute("SELECT DISTINCT pr_creator FROM code_reviews ORDER BY pr_creator")]
total = conn.execute("SELECT COUNT(*) FROM code_reviews").fetchone()[0]
conn.close()

print(json.dumps({
    "reviews": reviews,
    "repos": repos,
    "authors": authors,
    "total_in_db": total,
    "returned": len(reviews),
}))
PY
