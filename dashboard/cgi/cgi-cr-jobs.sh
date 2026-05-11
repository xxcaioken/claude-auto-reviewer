#!/bin/bash
# CGI: retorna jobs ativos (forced/*.json) + finalizados recentemente
# (forced/done/*.json modificados nos últimos 30s). Detecta órfãos.
set -u

FORCED="${HEARTBEAT_DIR:-/home/npu/.claude/heartbeat}/forced"
DONE="$FORCED/done"

printf 'Content-Type: application/json; charset=utf-8\r\n'
printf 'Cache-Control: no-store\r\n'
printf '\r\n'

FORCED="$FORCED" DONE="$DONE" python3 - <<'PY'
import json, os, time
from pathlib import Path

forced = Path(os.environ["FORCED"])
done = Path(os.environ["DONE"])
forced.mkdir(parents=True, exist_ok=True)
done.mkdir(parents=True, exist_ok=True)

CLAUDE_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "600"))
ORPHAN_AFTER = CLAUDE_TIMEOUT + 60  # segundos
now = time.time()

def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False

active = []
for p in sorted(forced.glob("*.json"), key=lambda x: x.stat().st_mtime):
    try:
        j = json.loads(p.read_text())
    except Exception:
        continue
    pid = j.get("pid")
    started = j.get("started_at", "")
    # idade aproximada via mtime
    age = now - p.stat().st_mtime
    is_orphan = (pid and not pid_alive(pid)) and age > ORPHAN_AFTER
    if is_orphan:
        j["status"] = "orphaned"
        j["finished_at"] = j.get("finished_at") or ""
        try:
            (done / p.name).write_text(json.dumps(j, indent=2))
            p.unlink()
        except Exception:
            pass
        continue
    j["elapsed_sec"] = int(age)
    active.append(j)

recently_done = []
for p in sorted(done.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
    age = now - p.stat().st_mtime
    if age > 30:
        break  # estão ordenados desc por mtime, então fim da lista útil
    try:
        recently_done.append(json.loads(p.read_text()))
    except Exception:
        continue

print(json.dumps({"jobs": active, "recently_done": recently_done}))
PY
