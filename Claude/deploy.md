---
title: Deploy e operação contínua
type: flow
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
  - "[[runbook-testar-localmente]]"
  - "[[dependencias]]"
tier: 2
---

# Deploy e operação

Não há "deploy" no sentido cloud. Tudo roda na máquina do usuário. "Deploy" aqui = `install.sh` + cron line.

## Modelo de execução

| Componente | Lifecycle | Onde |
|---|---|---|
| `heartbeat.py` | Disparado pelo cron a cada 5 min. Vive ~segundos a ~horas (PRs em fila). Single-process, single-tick. | `~/.claude/heartbeat/heartbeat.py` (symlink) |
| `code-review.md` | Lido pelo Claude CLI a cada invocação. | `~/.claude/commands/code-review.md` (symlink) |
| `state.db` | Arquivo persistente. Aberto/fechado por tick. | `~/.claude/heartbeat/state.db` |
| `datasette` (opt) | Long-running. Service systemd. | `~/.local/bin/datasette` + service em `~/.config/systemd/user/` |

## Bootstrap inicial

```bash
git clone https://github.com/<seu-org>/claude-auto-reviewer.git
cd claude-auto-reviewer
./install.sh
```

`install.sh` (script de 4.2KB, ver fonte) faz:

1. **Validação** de pré-requisitos (claude, gh, python3, gh auth).
2. **Cria diretórios**: `~/.claude/heartbeat/{,logs}`, `~/.claude/commands`, `~/.config/systemd/user`.
3. **Cria symlinks**:
   - `~/.claude/heartbeat/heartbeat.py` → `<REPO>/heartbeat/heartbeat.py`
   - `~/.claude/commands/code-review.md` → `<REPO>/commands/code-review.md`
4. **Copia `repos.txt.example` → `repos.txt`** se não existir (preserva se existir).
5. **Inicializa SQLite** (CREATE TABLE IF NOT EXISTS via `init_db`).
6. **Pergunta sobre datasette** — instala via pip + cria systemd service se sim.
7. **Imprime a linha de cron** sugerida pro user adicionar manualmente.

**Por quê symlinks**: `git pull` no repo atualiza heartbeat.py e code-review.md sem reinstalar. Decisão arquitetural — ver [[ADR-003-symlinks-no-install]].

**Por quê não auto-adiciona ao crontab**: idempotência. Auto-edição de crontab pode duplicar linhas ou conflitar com outras entradas do user. Linha sugerida + comando idempotente printado:

```
(crontab -l 2>/dev/null | grep -v 'heartbeat.py'; echo "*/5 * * * * /usr/bin/python3 ~/.claude/heartbeat/heartbeat.py >/dev/null 2>&1") | crontab -
```

## Atualizações

```bash
cd <REPO>
git pull
```

**Só isso.** Symlinks fazem o resto:
- Mudança em `heartbeat.py` → próximo tick usa nova versão.
- Mudança em `code-review.md` → próxima invocação do Claude usa novo prompt.

**Quando `install.sh` precisa rodar de novo**:
- Movi o repo de pasta → symlinks ficam quebrados. Rodar `./install.sh` de novo.
- Adicionei nova entrada em `~/.claude/heartbeat/` (ex: novo script auxiliar) → rodar pra criar symlink novo.
- Quer instalar/reinstalar datasette.

Nada no `install.sh` é destrutivo — re-rodar é seguro (idempotente, exceto repos.txt que é preservado).

## Operação no dia-a-dia

### Acompanhar atividade
```bash
tail -f ~/.claude/heartbeat/logs/heartbeat.log
```

### Ver últimas revisões
```bash
python3 -c "
import sqlite3, os
c = sqlite3.connect(os.path.expanduser('~/.claude/heartbeat/state.db'))
for r in c.execute('SELECT runned_at, repo, pr_number, runned, pr_creator, substr(pr_name,1,50) FROM code_reviews ORDER BY runned_at DESC LIMIT 20'):
    s = 'OK ' if r[3]==1 else 'NOPE'
    print(r[0], s, r[1], '#'+str(r[2]), r[4], r[5])
"
```

Ou via Datasette: <http://localhost:8001>.

### Pausar / re-armar cron sem desinstalar
```bash
# Pausar
crontab -l | sed 's|^\(\*/5.*heartbeat.py.*\)$|# \1|' | crontab -

# Re-armar
crontab -l | sed 's|^# \(\*/5.*heartbeat.py.*\)$|\1|' | crontab -
```

### Matar tick em andamento (lote longo)
```bash
pkill -f heartbeat.py
pkill -f "claude -p /code-review"
```

Lock fcntl é liberado pelo OS quando processo morre. Próximo tick segue normal.

### Desativar 1 repo específico
Editar `~/.claude/heartbeat/repos.txt`, trocar último campo `|1` por `|0`. Sem restart — próximo tick já ignora.

## Datasette (visualizador web opcional)

Service systemd em `systemd/datasette-heartbeat.service`:

```ini
[Unit]
Description=Datasette — visualizador web do Heartbeat SQLite
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/datasette serve %h/.claude/heartbeat/state.db \
    --host 0.0.0.0 --port 8001 \
    --setting truncate_cells_html 200 \
    --setting sql_time_limit_ms 5000 \
    --setting default_page_size 25
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Pontos:
- `%h` → resolvido pelo systemd como `$HOME` do user.
- `0.0.0.0` → acessível da LAN. Se quiser localhost-only, mudar pra `127.0.0.1`.
- `truncate_cells_html=200` → cells grandes (markdown completo do `cr_description`) ficam navegáveis sem travar o browser.
- Read-only por padrão do datasette — não interfere no heartbeat escrevendo (WAL).

Comandos comuns:
```bash
systemctl --user status datasette-heartbeat
systemctl --user restart datasette-heartbeat
systemctl --user stop datasette-heartbeat
journalctl --user -u datasette-heartbeat -f

# Pra rodar mesmo sem login:
sudo loginctl enable-linger $USER
```

## Capacidade conhecida

| Métrica | Valor observado | Limite arquitetural |
|---|---|---|
| Concorrência | 1 PR/vez | Lock fcntl global (heartbeat.py:353) |
| Timeout por PR | 600s default | Configurável via `CLAUDE_TIMEOUT` |
| Throughput | 6-12 PRs/h | Custo: 1 invocação Claude por PR |
| Custo estimado | ~$0.10-0.50 por revisão (Opus) | Depende do tamanho do diff |

**Bottleneck**: tempo do `claude -p`. Cada revisão é uma sessão multi-step do Claude (lê, analisa, posta). Pra paralelizar precisaria refatorar lock + workers (ver [[tech-debt]] §TD-006).

## Migrações de versão

Hoje só schema do SQLite tem migration (`init_db` com ALTER TABLE). Mudanças de comportamento do `heartbeat.py` que precisem de dados velhos:

- **Adicionar coluna nova**: bloco `if "col" not in cols` em `init_db`, default sensato.
- **Renomear coluna**: hoje requer ALTER TABLE RENAME (SQLite 3.25+). Documentar migration na ADR.
- **Remover coluna**: SQLite 3.35+ tem DROP COLUMN. Antes disso requer recriar tabela.

Mudanças no formato de `repos.txt`: backwards-compatible sempre. `load_repos` (heartbeat.py:139) já é defensivo (extra fields ignorados, faltantes logam warning).

Mudanças no `code-review.md`: zero migration — Claude lê na hora. Risco é só semântico (mudou regra, comentários novos podem ter formato diferente dos antigos).

## Backup e recuperação

Não há backup automático ([[tech-debt]] §TD-004). Manual:

```bash
# Backup seguro (WAL-aware)
sqlite3 ~/.claude/heartbeat/state.db \
  ".backup ~/backups/state-$(date +%F).db"

# Restore: parar heartbeat, substituir, limpar WAL órfão
crontab -l | grep -v heartbeat.py | crontab -        # pausa cron
pkill -f heartbeat.py
cp ~/backups/state-2026-05-22.db ~/.claude/heartbeat/state.db
rm -f ~/.claude/heartbeat/state.db-shm ~/.claude/heartbeat/state.db-wal
# re-armar cron
```

## Regras e Invariantes

- **`install.sh` é idempotente** — re-rodar é seguro, exceto `repos.txt` que é preservado se existir.
- **Symlinks são absolutos** — propósito documentado em [[ADR-003-symlinks-no-install]]. Mover repo quebra (ver [[bugs-conhecidos]] §B-001).
- **Cron é gerenciado pelo user**, não pelo `install.sh` — o script imprime a linha, não auto-edita. Decisão consciente pra evitar bagunça em crontabs alheios.
- **`update = git pull`** — sem build, sem reinstall. Symlinks propagam imediatamente.
- **Backup automático NÃO existe** — operador é responsável até [[tech-debt]] §TD-004.
- **Datasette opera read-only por design** — WAL permite concorrência com heartbeat escrevendo.

## Desinstalação

```bash
# Remover cron
crontab -l | grep -v heartbeat.py | crontab -

# Parar datasette
systemctl --user disable --now datasette-heartbeat
rm ~/.config/systemd/user/datasette-heartbeat.service
systemctl --user daemon-reload

# Remover symlinks
rm ~/.claude/heartbeat/heartbeat.py
rm ~/.claude/commands/code-review.md

# Limpar estado (CUIDADO: perde histórico)
rm -rf ~/.claude/heartbeat/

# Remover o repo
cd .. && rm -rf claude-auto-reviewer/
```
