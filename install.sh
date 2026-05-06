#!/usr/bin/env bash
# claude-auto-reviewer — bootstrap em 1 comando.
# Cria symlinks pros arquivos do repo, instala datasette opcional, prepara cron.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HEARTBEAT_DIR="${HEARTBEAT_DIR:-$HOME/.claude/heartbeat}"
COMMANDS_DIR="$HOME/.claude/commands"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m⚠\033[0m %s\n' "$1"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$1"; }

bold "→ claude-auto-reviewer install"
echo "  REPO_DIR:      $REPO_DIR"
echo "  HEARTBEAT_DIR: $HEARTBEAT_DIR"
echo "  COMMANDS_DIR:  $COMMANDS_DIR"
echo

bold "Verificando pré-requisitos..."
command -v claude >/dev/null || { err "Claude Code CLI não encontrado. Instale: https://docs.claude.com/en/docs/claude-code/setup"; exit 1; }
ok "claude: $(command -v claude)"
command -v gh >/dev/null || { err "gh CLI não encontrado. Instale: https://cli.github.com"; exit 1; }
ok "gh: $(command -v gh)"
command -v python3 >/dev/null || { err "python3 não encontrado"; exit 1; }
ok "python3: $(command -v python3) ($(python3 --version))"
gh auth status >/dev/null 2>&1 || { err "gh não autenticado. Rode: gh auth login"; exit 1; }
ok "gh autenticado"
echo

bold "Criando diretórios..."
mkdir -p "$HEARTBEAT_DIR/logs" "$COMMANDS_DIR" "$SYSTEMD_USER_DIR"
ok "$HEARTBEAT_DIR"
ok "$COMMANDS_DIR"
ok "$SYSTEMD_USER_DIR"
echo

bold "Criando symlinks..."
ln -sf "$REPO_DIR/heartbeat/heartbeat.py" "$HEARTBEAT_DIR/heartbeat.py"
ok "$HEARTBEAT_DIR/heartbeat.py → $REPO_DIR/heartbeat/heartbeat.py"
ln -sf "$REPO_DIR/commands/code-review.md" "$COMMANDS_DIR/code-review.md"
ok "$COMMANDS_DIR/code-review.md → $REPO_DIR/commands/code-review.md"
echo

bold "Configurando repos.txt..."
if [ -f "$HEARTBEAT_DIR/repos.txt" ]; then
  warn "$HEARTBEAT_DIR/repos.txt já existe — preservando"
else
  cp "$REPO_DIR/heartbeat/repos.txt.example" "$HEARTBEAT_DIR/repos.txt"
  ok "$HEARTBEAT_DIR/repos.txt criado a partir do .example"
  warn "EDITE $HEARTBEAT_DIR/repos.txt pra incluir os repos que quer monitorar"
fi
echo

bold "Inicializando SQLite (cria tabelas se não existirem)..."
python3 "$HEARTBEAT_DIR/heartbeat.py" --help >/dev/null 2>&1 || true
HEARTBEAT_DIR="$HEARTBEAT_DIR" python3 -c "
import os, sys, importlib.util
spec = importlib.util.spec_from_file_location('hb', '$REPO_DIR/heartbeat/heartbeat.py')
hb = importlib.util.module_from_spec(spec); spec.loader.exec_module(hb)
conn = hb.open_db(); hb.init_db(conn); conn.close()
print('  ✓ tabelas criadas em', hb.DB_PATH)
"
echo

bold "Datasette (opcional — visualizador web do SQLite)..."
read -r -p "  Instalar e habilitar datasette? [Y/n] " yn
yn=${yn:-Y}
if [[ "$yn" =~ ^[Yy]$ ]]; then
  if ! command -v "$HOME/.local/bin/datasette" >/dev/null 2>&1; then
    python3 -m pip install --user --break-system-packages datasette 2>&1 | tail -3 || {
      err "pip install falhou. Pode ser preciso instalar python3-pip primeiro: sudo apt install python3-pip"
    }
  fi
  if [ -f "$HOME/.local/bin/datasette" ]; then
    cp "$REPO_DIR/systemd/datasette-heartbeat.service" "$SYSTEMD_USER_DIR/"
    ok "service copiado pra $SYSTEMD_USER_DIR/"
    systemctl --user daemon-reload
    systemctl --user enable --now datasette-heartbeat
    ok "datasette-heartbeat enabled + iniciado"
    echo
    warn "Pra rodar mesmo sem você logado, execute:  sudo loginctl enable-linger $USER"
    echo "  Acesse: http://localhost:8001 (ou http://<host>.local:8001 da LAN)"
  fi
else
  ok "pulado"
fi
echo

bold "Cron (linha sugerida)..."
echo "  Adicione ao seu crontab pra rodar a cada 5 min:"
echo
echo "    */5 * * * * /usr/bin/python3 $HEARTBEAT_DIR/heartbeat.py >/dev/null 2>&1"
echo
echo "  Edite com:  crontab -e"
echo
echo "  Ou em 1 comando idempotente:"
echo
echo "    (crontab -l 2>/dev/null | grep -v 'heartbeat.py'; echo \"*/5 * * * * /usr/bin/python3 $HEARTBEAT_DIR/heartbeat.py >/dev/null 2>&1\") | crontab -"
echo

bold "Tudo pronto."
echo
echo "Pra testar manualmente agora:"
echo "  python3 $HEARTBEAT_DIR/heartbeat.py"
echo
echo "Acompanhar logs:"
echo "  tail -f $HEARTBEAT_DIR/logs/heartbeat.log"
