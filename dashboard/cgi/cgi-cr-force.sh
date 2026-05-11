#!/bin/bash
# CGI: valida URL, confere lockfile livre, rate-limit, dispara o runner
# em background. Retorna 202 { job_id, status: "pending" } se OK.
set -u

HEARTBEAT_DIR="${HEARTBEAT_DIR:-/home/npu/.claude/heartbeat}"
RUNNER="${RUNNER:-/home/npu/bin/run-forced-cr.py}"
LOCKFILE="$HEARTBEAT_DIR/heartbeat.lock"
FORCED="$HEARTBEAT_DIR/forced"
URL_RE='^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[0-9]+$'
RATE_LIMIT_MAX=5
RATE_LIMIT_WINDOW=60

reply_json() {
  local code="$1" ok="$2" msg="$3" extra="${4:-}"
  printf 'Status: %s\r\n' "$code"
  printf 'Content-Type: application/json; charset=utf-8\r\n'
  printf 'Cache-Control: no-store\r\n'
  printf '\r\n'
  python3 -c "
import json, sys
out = {'ok': bool($ok), 'message': '''$msg'''}
extra = '''$extra'''
if extra:
    out.update(json.loads(extra))
print(json.dumps(out))
"
}

# parse ?url=
qs="${QUERY_STRING:-}"
url=""
IFS='&' read -ra pairs <<< "$qs"
for p in "${pairs[@]}"; do
  k="${p%%=*}"; v="${p#*=}"
  if [ "$k" = "url" ]; then
    v="${v//+/ }"
    url=$(printf '%b' "${v//%/\\x}")
  fi
done

if [ -z "$url" ]; then
  reply_json "400 Bad Request" 0 "Parâmetro 'url' não informado."
  exit 0
fi
if ! [[ "$url" =~ $URL_RE ]]; then
  reply_json "400 Bad Request" 0 "URL inválida. Esperado: https://github.com/owner/repo/pull/N"
  exit 0
fi

# Extrai owner/repo da URL
github_repo=$(echo "$url" | sed -E 's#https://github\.com/([^/]+/[^/]+)/pull/[0-9]+$#\1#')

# Valida que o repo está em repos.txt enabled=1
in_repos=$(python3 -c "
import sys
github_repo = sys.argv[1]
try:
    with open('${HEARTBEAT_DIR}/repos.txt') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            parts = line.split('|')
            if len(parts) < 3: continue
            enabled = parts[3].strip() if len(parts) > 3 else '1'
            if parts[2] == github_repo and enabled != '0':
                print('yes'); sys.exit(0)
    print('no')
except Exception:
    print('no')
" "$github_repo")

if [ "$in_repos" != "yes" ]; then
  reply_json "403 Forbidden" 0 "Repo '$github_repo' não monitorado pelo heartbeat (não está em repos.txt enabled=1)."
  exit 0
fi

# Confere lock livre (não adquire — só checa)
if [ -f "$LOCKFILE" ]; then
  if ! python3 -c "
import fcntl, sys
try:
    f = open('$LOCKFILE', 'a')
    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    sys.exit(0)
except BlockingIOError:
    sys.exit(1)
"; then
    reply_json "423 Locked" 0 "Heartbeat tick em andamento, tente em instantes."
    exit 0
  fi
fi

# Rate-limit
mkdir -p "$FORCED" "$FORCED/done"
recent=$(find "$FORCED" "$FORCED/done" -maxdepth 1 -name '*.json' -newermt "-${RATE_LIMIT_WINDOW} seconds" 2>/dev/null | wc -l)
if [ "$recent" -ge "$RATE_LIMIT_MAX" ]; then
  reply_json "429 Too Many Requests" 0 "Limite de $RATE_LIMIT_MAX force-runs em ${RATE_LIMIT_WINDOW}s atingido."
  exit 0
fi

# Gera job_id
job_id=$(date -u +%Y%m%d-%H%M%S)-$(python3 -c "import secrets; print(secrets.token_hex(2))")
job_path="$FORCED/$job_id.json"

# Cria JSON pendente
python3 -c "
import json, os
state = {
    'job_id': '$job_id',
    'url': '$url',
    'repo': '$github_repo',
    'status': 'pending',
    'pid': None,
    'started_at': '$(date -u +%Y-%m-%dT%H:%M:%SZ)',
}
with open('$job_path', 'w') as f:
    json.dump(state, f)
os.chmod('$job_path', 0o600)
"

# Dispara o runner em background, totalmente desligado da sessão CGI
nohup setsid python3 "$RUNNER" "$url" "$job_id" </dev/null >/dev/null 2>&1 &
disown 2>/dev/null || true

reply_json "202 Accepted" 1 "Force-run agendado." "{\"job_id\":\"$job_id\",\"status\":\"pending\"}"
