# CLAUDE.md — claude-auto-reviewer

Code review automático em PRs do GitHub. Cron Python invoca o Claude CLI a cada 5 min; o Claude lê o diff via `gh`, gera revisão, e posta como comentário no PR. Estado persiste em SQLite local.

## Comandos

```bash
# Bootstrap (1x)
./install.sh

# Tick manual (testar sem esperar cron)
python3 ~/.claude/heartbeat/heartbeat.py

# Tail de log
tail -f ~/.claude/heartbeat/logs/heartbeat.log

# Últimas revisões
sqlite3 ~/.claude/heartbeat/state.db \
  "SELECT runned_at, repo, pr_number, runned, pr_creator FROM code_reviews ORDER BY id DESC LIMIT 10;"

# Update (symlinks → git pull propaga)
git pull

# Validar drift entre código e vault (skill local)
# /knowledge-sync-code-reviewer            (checks 1-7 — vault local apenas)
# /knowledge-sync-code-reviewer --check-targets  (adiciona check 8 — read-only nos 6 NPU)

# Pausar / re-armar cron
crontab -l | sed 's|^\(\*/5.*heartbeat.py.*\)$|# \1|' | crontab -    # pausa
crontab -l | sed 's|^# \(\*/5.*heartbeat.py.*\)$|\1|' | crontab -    # re-arma

# Matar tick travado
pkill -f heartbeat.py; pkill -f "claude -p /code-review"
```

## Arquitetura

```
.
├── heartbeat/
│   ├── heartbeat.py        # cron entrypoint, ~380 linhas stdlib-only
│   └── repos.txt.example   # template — copie pra ~/.claude/heartbeat/repos.txt
├── commands/
│   └── code-review.md      # prompt do reviewer (~300 linhas) — coração do sistema
├── systemd/
│   └── datasette-heartbeat.service  # opcional, web UI read-only
├── install.sh              # cria symlinks, valida pré-reqs, bootstrap
├── .env.example            # env vars opcionais
└── Claude/                 # vault Obsidian — knowledge base do projeto
```

**Fluxo a cada tick (5min)**:
1. `gh pr list` em cada repo de `repos.txt`.
2. Filtra: draft / label `skip-code-review` / `(repo, pr_number, head_sha)` já em `code_reviews`.
3. Pra cada PR não revisado: snapshot comments → `claude -p '/code-review <url> publique'` → snapshot de novo → detecta comment novo via marcador HTML → INSERT em `code_reviews`.

## Gotchas (causam erro se não souber)

1. **Marcador HTML é contrato** — o comentário publicado **DEVE** começar com `<!-- code-review-bot:v1 -->`. Sem isso, `fetch_bot_comments` não detecta → `runned=0` falso. Não mude `MARKER` em produção.
2. **`bypassPermissions` obrigatório** — sem `--permission-mode bypassPermissions`, Claude trava pedindo aprovação interativa pra `gh`. Cron sem TTY → timeout 600s → `runned=0`.
3. **`CLAUDE_CWD=$HOME` (default)** — invocar Claude num cwd que tenha `.claude/commands/code-review.md` local faz o comando local vencer o global. Quebra a arquitetura.
4. **`runned=0` é sobrecarregado**: pode ser falha real (timeout/erro) OU filtro do prompt funcionando (diff só docs). Distinguir inspecionando coluna `log`.
5. **`runned=0` bloqueia retry automático**: `needs_review` consulta por `(repo, pr_number, head_sha)`, não por `runned`. Pra retentar mesmo commit, deletar a linha do SQLite.
6. **Símbolos do install.sh são absolutos** — mover o repo de pasta quebra os symlinks. Rodar `./install.sh` de novo.
7. **Lock fcntl global** — só 1 tick por vez. Lote longo (20 PRs × 5min = ~100 min) aborta ticks intermediários do cron. **Não é bug** — é design.

## Regras de Negócio

Centralizado em [[Claude/regras-negocio]]. 10 regras críticas — leitura obrigatória antes de mudar código. Resumo dos invariantes:

- Idempotência por `(repo, pr_number, head_sha)` — não re-revisa mesmo commit.
- `code_reviews` é append-only (1 linha por execução, nunca UPDATE).
- `pr_state` é UPSERT (cache do último estado).
- Append-only em `code_reviews`, UPSERT em `pr_state`.
- Filtros de "não publicar" vivem no prompt, não no código.

## Integrações

- **GitHub via `gh` CLI**: scopes `repo` + `workflow`. Chamadas: `gh pr list`, `gh api .../comments`, e (pelo Claude) `gh pr comment`, `gh pr view`, `gh pr diff`.
- **Claude Code CLI**: `claude --permission-mode bypassPermissions -p '...'`. Versão precisa suportar `-p` modo não-interativo.
- **SQLite**: WAL mode, `busy_timeout=30000`. 2 tabelas: `pr_state` (UPSERT), `code_reviews` (APPEND-ONLY).
- **Vault Obsidian do repo-alvo (opcional)**: se `<REPO_PATH>/Claude/` existe, o prompt lê `regras-negocio.md`, `bugs-conhecidos.md`, `ADR-*.md` antes da análise pra contextualizar o review. Graceful degradation total quando ausente — repos sem vault recebem review genérico stack-agnostic. Decisão em `Claude/ADR-006-leitura-vault-repo-alvo.md`.

Detalhes em `Claude/arquitetura.md`, `Claude/arquitetura-banco.md`, `Claude/dependencias.md`.

## Bugs Conhecidos

| ID | Severidade | Item | Doc |
|---|---|---|---|
| B-001 | 🟡 | Symlink quebra se repo é movido | `Claude/bugs-conhecidos.md` §B-001 |
| B-002 | 🟡 | Mudar `MARKER` invisibiliza histórico | §B-002 |
| B-003 | 🟡 | Revisão parcial sem flag estruturada | §B-003 |
| B-004 | 🟢 | `claude --help` cosmético no install | §B-004 |
| B-005 | 🟢 | `gh auth status` não valida scopes | §B-005 |

Tech debt em `Claude/tech-debt.md` (TD-001 a TD-009).

## Obsidian Vault — Tiers de Leitura

Este repo tem um vault Obsidian em `Claude/` (33 notas + 5 templates). Não é integrado a `knowledge-sync` (repo independente). Leitura tiered por escopo:

| Tier | Quando ler | Notas | Tokens estimados |
|---|---|---|---|
| **T1** | Sempre que tocar no código | `arquitetura.md`, `regras-negocio.md`, `bugs-conhecidos.md`, `tech-debt.md`, `dependencias.md`, `glossario.md` | ~6K |
| **T2** | Tarefa específica em área | `arquitetura-banco.md`, `regras-prompt-review.md`, `error-handling.md`, `deploy.md`, `infra-testes.md`, `env-setup.md`, `modulo-heartbeat.md` | ~12K |
| **T3** | Decisão arquitetural ou runbook | ADRs (`ADR-001` a `ADR-005`), runbooks (`runbook-*`) | ~15K |

**MOCs (landing pages)** — leitura mínima ao entrar no projeto:
- `_MOC Onboarding.md` — sequência de leitura recomendada.
- `_MOC Auto-Reviewer.md` — visão técnica.
- `_MOC Operacao.md` — runbooks e operação.
- `_MOC Bugs.md` — débitos e bugs.
- `_MOC ADRs.md` — decisões arquiteturais.

Se for mexer:
- **No `heartbeat.py`** → ler T1 + `modulo-heartbeat.md` + `arquitetura-banco.md`.
- **No `commands/code-review.md`** → ler T1 + `regras-prompt-review.md` + `runbook-atualizar-prompt.md`.
- **No `install.sh`** → ler T1 + `ADR-003-symlinks-no-install.md` + `deploy.md`.

## Anti-overrides

- **Não mexer no install.sh sem checar `Claude/ADR-003-symlinks-no-install.md`** — symlinks são a base do modelo de update.
- **Não mudar `MARKER` em produção** — quebra `fetch_bot_comments` ([[Claude/bugs-conhecidos]] §B-002).
- **Não adicionar deps externas** — projeto é stdlib-only por design ([[Claude/dependencias]]).
