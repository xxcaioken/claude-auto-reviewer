# claude-auto-reviewer

Code review automático em PRs do GitHub usando o **Claude Code CLI**.

Um cron monitora seus repos a cada 5 min: quando detecta um PR novo (ou push novo num PR existente), dispara o Claude com um prompt customizado de revisão. O Claude lê o diff via `gh`, analisa, e posta um comentário estruturado no PR. Tudo é arquivado em SQLite — append-only, com histórico de cada revisão por `head_sha`.

```
┌──────┐    cron */5min    ┌────────────┐   gh pr list   ┌────────┐
│ cron │ ─────────────────►│ heartbeat  │ ──────────────►│ GitHub │
└──────┘                   │   .py      │                └────────┘
                           └─────┬──────┘
                                 │ pra cada PR não revisado
                                 ▼
                        ┌─────────────────┐
                        │  claude -p      │
                        │ /code-review    │ ── posta comment ──► PR
                        │ <url> publique  │
                        └────────┬────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │  state.db       │ ── histórico append-only
                        │  (SQLite)       │
                        └─────────────────┘
```

## Pré-requisitos

- **Claude Code CLI** instalado e autenticado: <https://docs.claude.com/en/docs/claude-code/setup>
- **GitHub CLI (`gh`)** instalado e autenticado (`gh auth login`) com scopes `repo` e `workflow`.
- **Python 3.10+** (usa só stdlib, sem deps).
- **Linux/macOS** com `cron` e `fcntl` (Windows não testado).
- Opcional: `datasette` (visualizador web do SQLite) — instalável via `install.sh`.

## Instalação rápida

```bash
git clone https://github.com/xxcaioken/claude-auto-reviewer.git
cd claude-auto-reviewer
./install.sh
```

O `install.sh`:
1. Valida pré-requisitos (claude, gh, python3, gh auth).
2. Cria `~/.claude/heartbeat/` (estado + logs).
3. **Symlinks** pros arquivos do repo (`heartbeat.py`, `code-review.md`) — assim `git pull` atualiza tudo.
4. Copia `repos.txt.example` → `repos.txt` se não existir.
5. Inicializa o SQLite (cria tabelas).
6. Pergunta se quer instalar datasette + systemd service.
7. Mostra a linha de cron pra você adicionar.

Depois:
```bash
# 1. Edite a lista de repos:
nano ~/.claude/heartbeat/repos.txt

# 2. Teste manualmente:
python3 ~/.claude/heartbeat/heartbeat.py

# 3. Adicione ao crontab (linha que install.sh mostrou):
crontab -e
```

## Como funciona

### 1. Discovery
A cada tick, pra cada repo em `repos.txt`:
- `gh pr list --repo <owner>/<repo> --state open --json number,headRefOid,isDraft,title,url,author,labels,state`

### 2. Filtros
PR é **pulado** se:
- `isDraft: true`
- Tem label `skip-code-review`
- Já existe linha em `code_reviews` com mesmo `(repo, pr_number, head_sha)` (idempotência por commit).

### 3. Revisão
Pra cada PR a revisar:
- **Snapshot**: lista comentários do bot (com marcador HTML) já no PR.
- Invoca: `claude --permission-mode bypassPermissions -p '/code-review <pr_url> publique'`
  - O `bypassPermissions` é necessário porque o cron não pode aprovar prompts interativos.
  - O cwd é `$HOME` (ou `CLAUDE_CWD`) — sem `.claude/commands/code-review.md` local que sobrescreva o global.
- Claude lê o diff (`gh pr diff`), analisa, e posta o comentário ele mesmo via `gh pr comment`.
- **Detecção**: snapshot novamente. Se há comment novo do bot (com marcador), arquiva no SQLite com `runned=1`. Se não há, arquiva com `runned=0` + log do `stdout/stderr` pra debug.

### 4. Idempotência
- Lock fcntl global em `heartbeat.lock` — só 1 tick rodando por vez (lote longo de 20+ PRs pode atravessar vários intervalos do cron; ticks que pegariam o lock simplesmente abortam logando "outro tick em progresso").
- Re-revisão acontece quando `head_sha` muda (push novo). Adiciona linha nova em `code_reviews` E novo comentário no PR (não usa `--edit-last`).

## Configuração

Tudo via env vars opcionais. Veja [`.env.example`](.env.example) pra a lista completa. Defaults sensatos são detectados automaticamente — geralmente você só precisa editar `repos.txt`.

| Var | Default | Quando mexer |
|---|---|---|
| `HEARTBEAT_DIR` | `~/.claude/heartbeat` | Mover dados pra outro disco/partição |
| `CLAUDE_BIN` | `which claude` | Claude instalado em path não-padrão |
| `GH_BIN` | `which gh` | gh instalado em path não-padrão |
| `CLAUDE_CWD` | `$HOME` | Forçar outro diretório |
| `MARKER` | `<!-- code-review-bot:v1 -->` | Versionar o marcador (raro) |
| `SKIP_LABEL` | `skip-code-review` | Renomear a label |
| `CLAUDE_TIMEOUT` | `600` | PRs gigantes que estão dando timeout |
| `GH_TIMEOUT` | `60` | Conexão lenta com GitHub |
| `SQLITE_TIMEOUT` | `30` | Concorrência alta no DB |

## Schema SQLite

Auto-criado pelo `init_db()` na primeira execução (CREATE TABLE IF NOT EXISTS + ALTER TABLE pra migrations futuras).

```sql
-- Estado atual de cada PR conhecido (UPSERT por (repo, pr_number))
CREATE TABLE pr_state (
  repo TEXT NOT NULL,
  pr_number INTEGER NOT NULL,
  head_sha TEXT NOT NULL,
  is_draft INTEGER NOT NULL,
  state TEXT NOT NULL,
  last_seen_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
  PRIMARY KEY (repo, pr_number)
);

-- Append-only: 1 linha por execução do CR. Re-execução em mesmo head_sha é
-- bloqueada por needs_review (idempotência). Push novo no PR → nova linha.
CREATE TABLE code_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repo TEXT NOT NULL,                       -- nome local
  pr_number INTEGER NOT NULL,
  pr_name TEXT NOT NULL,                    -- título do PR
  pr_creator TEXT NOT NULL,                 -- @login do autor
  pr_url TEXT NOT NULL,
  head_sha TEXT NOT NULL,                   -- sha que foi revisado
  cr_description TEXT NOT NULL DEFAULT '',  -- texto COMPLETO da revisão (markdown), NÃO descrição do PR
  pr_state TEXT NOT NULL,                   -- estado do PR no momento (OPEN/MERGED/CLOSED)
  comment_id TEXT,                          -- id do comment no GitHub (NULL se runned=0)
  log TEXT,                                 -- stdout/stderr do claude (debug)
  runned INTEGER NOT NULL DEFAULT 0,        -- 1=publicou comment, 0=tentou e não publicou
  runned_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
```

Conexão usa **WAL mode** + `busy_timeout=30000` pra não dar "database is locked" em ticks paralelos ou WAL órfão de SIGTERM.

## Operação

```bash
# Acompanhar em tempo real
tail -f ~/.claude/heartbeat/logs/heartbeat.log

# Listar revisões salvas (com status)
python3 -c "
import sqlite3, os
c = sqlite3.connect(os.path.expanduser('~/.claude/heartbeat/state.db'))
for r in c.execute('SELECT runned_at, repo, pr_number, runned, pr_creator, substr(pr_name,1,50) FROM code_reviews ORDER BY runned_at DESC LIMIT 20'):
    s = 'OK ' if r[3]==1 else 'NOPE'
    print(r[0], s, r[1], '#'+str(r[2]), r[4], r[5])
"

# Investigar revisão que falhou (runned=0)
python3 -c "
import sqlite3, os
c = sqlite3.connect(os.path.expanduser('~/.claude/heartbeat/state.db'))
for r in c.execute('SELECT id, repo, pr_number, log FROM code_reviews WHERE runned=0 ORDER BY runned_at DESC LIMIT 3'):
    print(f'=== {r[1]} #{r[2]} (id={r[0]}) ==='); print(r[3][:1500])
"

# Pausar cron sem desinstalar
crontab -l | sed 's|^\(\*/5.*heartbeat.py.*\)$|# \1|' | crontab -

# Re-armar
crontab -l | sed 's|^# \(\*/5.*heartbeat.py.*\)$|\1|' | crontab -

# Matar emergencial durante um tick
pkill -f heartbeat.py; pkill -f "claude -p /code-review"

# Desativar 1 repo específico: editar repos.txt, trocar último |1 por |0
```

## Visualizador web (Datasette)

Se você instalou via `install.sh`:
- Local: <http://localhost:8001>
- LAN: <http://your-host.local:8001>

Comandos:
```bash
systemctl --user status datasette-heartbeat
systemctl --user restart datasette-heartbeat
systemctl --user stop datasette-heartbeat
journalctl --user -u datasette-heartbeat -f
```

Pra rodar mesmo sem login do user:
```bash
sudo loginctl enable-linger $USER
```

## Dashboard estilizado (opcional)

Além do Datasette (visualizador SQL genérico), o repo provê um **dashboard estilizado** com tabela cronológica, filtros e botão pra **forçar code-review** em PR específico bypassando o filtro de deduplicação do heartbeat.

Acesso típico (depois do deploy): `http://your-host.local/completo/code-reviews/` ou outro path no seu nginx.

### Componentes (em `dashboard/`)

| Arquivo | Função |
|---|---|
| `dashboard/web/index.html` | UI single-page (HTML/CSS/JS inline) |
| `dashboard/cgi/cgi-cr-list.sh` | CGI lê `code_reviews` do SQLite → JSON |
| `dashboard/cgi/cgi-cr-jobs.sh` | CGI lista jobs em vôo (`forced/*.json`) |
| `dashboard/cgi/cgi-cr-force.sh` | CGI valida URL, enfileira, dispara runner em bg |
| `dashboard/runner/run-forced-cr.py` | Runner Python — importa do `heartbeat.py`, compartilha lockfile |
| `dashboard/nginx/code-review-locations.conf.example` | Snippet exemplo de nginx locations |

### Pré-requisitos extras

- **nginx** + **fcgiwrap** instalados e rodando (mesmo padrão de qualquer site CGI clássico)
- Wiki/site servido pelo nginx onde o `index.html` do dashboard será colocado
- O endpoint `/api/code-review/*` no nginx aponta pros CGIs via fcgiwrap (ver snippet `dashboard/nginx/...example`)
- A página HTML faz `<script src="/assets/vendor/marked.min.js">` — você precisa servir `marked.min.js` (~38 KB) nesse path ou ajustar o `<script src>`

### Instalação manual

1. Symlinkar os CGI e runner:
   ```bash
   ln -sf $(pwd)/dashboard/cgi/cgi-cr-list.sh   ~/bin/cgi-cr-list.sh
   ln -sf $(pwd)/dashboard/cgi/cgi-cr-jobs.sh   ~/bin/cgi-cr-jobs.sh
   ln -sf $(pwd)/dashboard/cgi/cgi-cr-force.sh  ~/bin/cgi-cr-force.sh
   ln -sf $(pwd)/dashboard/runner/run-forced-cr.py ~/bin/run-forced-cr.py
   ```
2. Copiar o HTML pro DocumentRoot do nginx:
   ```bash
   cp dashboard/web/index.html /var/www/seu-site/completo/code-reviews/index.html
   ```
3. Incluir o snippet `dashboard/nginx/code-review-locations.conf.example` no vhost (ajustar IPs e paths) e rodar `sudo nginx -t && sudo systemctl reload nginx`.

### Segurança

- IP allowlist no nginx restringe ao LAN local
- CGI valida URL com regex `^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[0-9]+$` antes de qualquer chamada
- Repo da URL é validado contra `repos.txt` enabled=1 — só PRs de repos monitorados podem ser forçados
- Rate-limit: 5 force-runs em 60 s
- Lockfile compartilhado com heartbeat impede execuções concorrentes de `claude`
- Runner roda como o user do fcgiwrap (sem `sudo`)
- Arquivos de estado em `~/.claude/heartbeat/forced/` com `0600`

### Spec completa

`docs/specs/2026-05-11-code-review-dashboard-design.md` — arquitetura, fluxos de dados, tratamento de erros.

## Capacidade & limites

| Métrica | Valor |
|---|---|
| Concorrência interna | 1 PR por vez (sequencial, lock fcntl global) |
| Timeout por PR | 600s (10min) — após isso, registra `runned=0` e segue |
| Throughput observado | ~6-12 PRs/hora (depende do tamanho do diff) |
| Custo estimado (Opus) | ~$0.10-0.50 por revisão |

**Bottleneck**: tempo do `claude -p` (cada revisão é 1 chamada multi-step). Pra paralelizar precisaria refatorar pra lock por-PR + workers paralelos.

## Tratamento de erros

| Erro | O que acontece |
|---|---|
| Claude timeout (>600s) | `runned=0` + log com TIMEOUT |
| Claude rc != 0 | `runned=0` + log com stderr |
| Claude rodou mas não publicou | `runned=0` + log com stdout (prompt filtrou — diff só docs, etc.) |
| `gh` falha | log warning; tick segue pro próximo repo |
| Database is locked | aguarda até `SQLITE_TIMEOUT` segundos (default 30) |
| Tick paralelo | aborta com `outro tick em progresso (sem erro)` — não é falha |

## Troubleshooting

**`claude` não encontrado**: instale o Claude Code CLI ou setar `CLAUDE_BIN` no env.

**`gh: command not found`**: `sudo apt install gh` (Linux) ou `brew install gh` (macOS).

**`gh auth status` falha**: rode `gh auth login` (escolha HTTPS + Login with a web browser).

**Cron não dispara**: verifique `crontab -l` e logs do cron (`/var/log/syslog | grep CRON` em Ubuntu).

**Comentário não aparece no PR**: olhe `runned` no SQLite. Se `runned=0`, leia `log` pra ver porquê. Se `runned=1` mas não vê o comment, pode ter sido apagado.

**Lote bootstrap demorando**: ticks longos são esperados (20+ PRs * ~5min cada = ~2h). Pra cortar: `pkill -f heartbeat.py` + pause cron.

**Bot está postando no formato antigo**: o symlink garante a versão do repo — confira: `readlink ~/.claude/commands/code-review.md`.

## Estrutura do repo

```
.
├── README.md                         # você está aqui
├── LICENSE                           # MIT
├── .gitignore
├── .env.example                      # vars opcionais documentadas
├── install.sh                        # bootstrap em 1 comando
├── commands/
│   └── code-review.md                # prompt/template do CR (vai pra ~/.claude/commands/)
├── heartbeat/
│   ├── heartbeat.py                  # entrypoint do cron
│   └── repos.txt.example             # template — copie pra ~/.claude/heartbeat/repos.txt
└── systemd/
    └── datasette-heartbeat.service   # service opcional pro visualizador web
```

## Roadmap (não prometido)

- **Métricas**: script diário com snapshot de PRs revisados, latência, falhas.
- **Backup automático** do `state.db` (cron + `sqlite3 .backup`).
- **Paralelismo**: lock por-PR + N workers (pra >12 PRs/h sustentado).
- **`--edit-last`** em vez de novo comentário a cada push.
- **Retenção**: TTL pra revisões antigas de PRs já merged.

## Licença

MIT — veja [LICENSE](LICENSE).
