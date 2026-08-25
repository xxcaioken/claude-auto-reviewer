# Code Review Dashboard + Force-Run — Design

**Data**: 2026-05-11
**Autor**: brainstorm conjunto (npu + Claude Opus 4.7)
**Servidor**: `hinc-wiki` (`192.168.15.97`)

## 1. Contexto

O servidor `hinc-wiki` já roda o **Heartbeat** — um cron a cada 5 min que dispara `claude -p '/code-review <url> publique'` em todo PR aberto dos repos Hinc e arquiva resultado num SQLite (`~/.claude/heartbeat/state.db`). Ver `SERVIDOR.md` §12.

Hoje a visualização desse SQLite é via **Datasette** em `http://hinc-wiki.local:8001` — bom pra query ad-hoc, ruim pra triagem dia-a-dia. E não existe forma de **forçar** uma revisão de um PR específico ignorando o filtro de deduplicação (`needs_review`) — quem quer re-revisar precisa hackear a DB ou pausar o cron e rodar `claude` manualmente.

## 2. Objetivo

Adicionar **sem quebrar nada do que existe**:

1. Dashboard web estilizado em `http://hinc-wiki.local/completo/code-reviews/` mostrando reviews recentes do `state.db` com filtros e drill-down.
2. Endpoint para forçar `/code-review` numa URL de PR específica, bypassando o filtro do heartbeat. Custo: paga API call. Cada execução leva 5-10 min.

**Não-objetivos**: substituir o Datasette, mudar o heartbeat, autenticar usuários, suportar repos fora do `repos.txt`.

## 3. Arquitetura

```
┌──────────────────────────────────────────────────────────────────┐
│  Browser (LAN)                                                   │
│  http://hinc-wiki.local/completo/code-reviews/                   │
│    UI: tabela + filtros + força-run                              │
└──────────────┬─────────────────────────────────────┬─────────────┘
               │ GET /api/code-review/{list,jobs}   │ POST .../force
               │ (polling 3s pros jobs ativos)      │
┌──────────────▼─────────────────────────────────────▼─────────────┐
│  nginx — locations restritas à LAN 192.168.15.0/24               │
│    /api/code-review/list   → fcgiwrap → cgi-cr-list.sh           │
│    /api/code-review/jobs   → fcgiwrap → cgi-cr-jobs.sh           │
│    /api/code-review/force  → fcgiwrap → cgi-cr-force.sh          │
└──────────────┬─────────────────────────────────────┬─────────────┘
               │ python3 (lê SQLite)                 │ nohup setsid
               │                                     │
┌──────────────▼────────────┐    ┌──────────────────▼──────────────┐
│  state.db (SQLite)        │    │  run-forced-cr.py               │
│  ~/.claude/heartbeat/     │◄───┤  importa heartbeat.py:          │
│   - code_reviews          │    │   open_db, init_db,             │
│   - pr_state              │    │   fetch_bot_comments,           │
└──────────────▲────────────┘    │   invoke_claude, save_review    │
               │                 │  Compartilha heartbeat.lock     │
               │                 └─────────────────┬───────────────┘
               │                                   │
               └───────── heartbeat.py ◄───────────┘
                       (cron 5min — não alterado)

  ~/.claude/heartbeat/forced/<job_id>.json   ← jobs ativos
  ~/.claude/heartbeat/forced/done/<id>.json  ← histórico (últimos 50)
```

**Princípios**:

- `heartbeat.py` é **importado**, nunca alterado. O cron continua exatamente como hoje.
- Lockfile compartilhado (`~/.claude/heartbeat/heartbeat.lock`) impede tick e force-run paralelos.
- Estado de jobs em vôo é arquivo JSON em `forced/`, não tabela nova no SQLite (não compete com writes do heartbeat).
- **Repo como fonte de verdade**: o projeto vive em `/home/npu/repos/claude-auto-reviewer/` (público em `github.com/xxcaioken/claude-auto-reviewer`). Hoje `~/.claude/heartbeat/heartbeat.py` e `~/.claude/commands/code-review.md` já são symlinks pro repo, gerenciados por `install.sh`. **Esta feature segue o mesmo padrão**: código novo nasce no repo; deploy é via symlink ou cópia idempotente; `install.sh` ganha etapas opcionais pro dashboard.

## 4. Componentes

### 4.1. Frontend

**Arquivo**: `/home/npu/repos/hinc-docs-wiki/completo/code-reviews/index.html`

Página única HTML+CSS+JS inline, padrão do `/completo/monitor/`. Reusa `marked.min.js` (já em `/assets/vendor/`) para renderizar `cr_description`.

Layout:

- Topo: card "Force-run" com input URL + botão `↻ Rodar CR`
- Banner de jobs em vôo (visível só quando `/api/code-review/jobs` retorna pelo menos 1)
- Filtros: select repo, select autor, select status (`✓ ok` / `✗ falhou` / `todos`), input busca (filtra por título)
- Tabela: hora, repo, PR#, título, autor, OK, link comment GitHub, botão `↻` (re-revisar)
- Linha expandível ao click: mostra `cr_description` renderizado + `log` truncado
- Auto-refresh: lista a cada 30 s; jobs a cada 3 s enquanto houver job ativo, senão 30 s

### 4.2. CGI scripts

Em `/home/npu/bin/`, executável, dono `npu`. Cada um devolve `application/json`.

| Script | Método | Função |
|---|---|---|
| `cgi-cr-list.sh` | GET | `?limit=200&repo=&author=&status=` → JSON `{reviews, repos, authors}` lendo `code_reviews` via `python3 -c "import sqlite3..."` |
| `cgi-cr-jobs.sh` | GET | Lê `~/.claude/heartbeat/forced/*.json` + `forced/done/*.json` modificados nos últimos 30 s → JSON `{jobs, recently_done}` |
| `cgi-cr-force.sh` | POST | `?url=...` → valida regex, valida repo na whitelist (`repos.txt`), checa lockfile livre, rate-limit, gera `job_id`, dispara runner em background, retorna `202 {job_id, status:"pending"}` |

### 4.3. Force-run runner

**Arquivo**: `/home/npu/bin/run-forced-cr.py`, ~80 linhas, executável.

Importa de `~/.claude/heartbeat/heartbeat`: `open_db, init_db, fetch_bot_comments, invoke_claude, save_review`. (Adiciona `~/.claude/heartbeat` ao `sys.path`.)

Fluxo:

1. Adquire `heartbeat.lock` com `flock(LOCK_EX)`, timeout 60 s. Se falha, marca job `failed` com motivo "lock timeout".
2. Escreve `forced/<job_id>.json` com `{status: "running", pid, url, started_at}`.
3. `gh pr view <url> --json number,headRefOid,isDraft,title,author,state,url` → monta dict no formato que `heartbeat.save_review` espera.
4. `before_ids = fetch_bot_comments(...)`.
5. `rc, stdout, stderr = invoke_claude(url)` — bloqueia 5-10 min.
6. `after = fetch_bot_comments(...)`. Detecta novo comment do bot.
7. `save_review(...)` na DB com `runned=1` (publicou) ou `runned=0` (rodou mas não publicou, ou rc≠0).
8. Atualiza `forced/<job_id>.json` → `status="done"` ou `"failed"`, `finished_at`, `comment_id`, `runned`, `rc`.
9. Move arquivo pra `forced/done/<job_id>.json`. Poda `forced/done/` mantendo só os últimos 50.
10. Libera lock.

### 4.4. Arquivos de estado

Diretório `~/.claude/heartbeat/forced/` (criado pelo runner se não existir).

JSON shape:

```json
{
  "job_id": "20260511-141500-a3f9",
  "url": "https://github.com/nec-plus-ultra/hinc-dashboards/pull/1431",
  "repo": "hinc-dashboards",
  "pr_number": 1431,
  "status": "running",
  "pid": 14572,
  "started_at": "2026-05-11T14:15:00Z",
  "finished_at": null,
  "comment_id": null,
  "runned": null,
  "rc": null,
  "log_tail": ""
}
```

Permissões: `0600`, dono `npu`.

### 4.5. Nginx

Adicionar 3 locations em `/etc/nginx/sites-available/hinc-docs-wiki`, padrão do `/api/monitor/*`:

```nginx
location = /api/code-review/list {
    allow 127.0.0.1; allow ::1; allow 192.168.15.0/24; deny all;
    include /etc/nginx/fastcgi_params;
    fastcgi_param SCRIPT_FILENAME /home/npu/bin/cgi-cr-list.sh;
    fastcgi_pass unix:/run/fcgiwrap.socket;
    fastcgi_read_timeout 10s;
}
# idem pros outros 2 — só muda SCRIPT_FILENAME
```

Sem mudança em nada existente. `/api/code-review/force` tem `fastcgi_read_timeout 5s` (só enfileira; não espera o claude).

## 5. Fluxo de dados

### 5.1. Listar reviews (carregamento da página)

```
1. Browser carrega /completo/code-reviews/
2. JS chama em paralelo:
   - GET /api/code-review/list?limit=200
     → cgi-cr-list.sh roda python3 + sqlite3 → JSON
   - GET /api/code-review/jobs
     → cgi-cr-jobs.sh varre forced/*.json
3. Popula selects de filtro (repos, authors únicos do JSON), tabela, banner de jobs (se houver)
4. setInterval:
   - lista: 30 s
   - jobs:  3 s se há job ativo, senão 30 s
```

### 5.2. Force-run (caminho feliz)

```
T+0    User clica ↻ ou submete URL.
       JS: confirm("Disparar CR em <url>? Custa API call.")
       fetch POST /api/code-review/force?url=...

T+0    cgi-cr-force.sh:
       ├─ Valida regex github.com/owner/repo/pull/N
       ├─ Valida repo está em repos.txt enabled=1
       ├─ flock --nonblock no heartbeat.lock → se segurando, 423
       ├─ Rate-limit: <5 force-runs em 60 s (mtime de forced/*.json + forced/done/*.json)
       ├─ job_id = "20260511-141500-a3f9"
       ├─ Cria forced/<job_id>.json com status="pending"
       ├─ nohup setsid python3 /home/npu/bin/run-forced-cr.py <url> <job_id> </dev/null >/dev/null 2>&1 &
       └─ 202 { job_id, status: "pending" }

T+0    Browser:
       ├─ Adiciona banner "⏳ rodando CR em PR #N (00:00)"
       └─ Polling agressivo (3 s) em /api/code-review/jobs

T+0 → T+~7m
       run-forced-cr.py (bg, spawned em T+0):
       ├─ flock exclusivo (espera até 60 s se tick rolar)
       ├─ Atualiza json → running, pid
       ├─ gh pr view → dict
       ├─ snapshot bot comments
       ├─ invoke_claude (5-10 min)         ← maior parte do tempo
       ├─ detecta novo comment
       ├─ save_review na DB (comment_id passado só quando publicou)
       ├─ atualiza json → done/failed
       └─ move pra done/

T+~7m  Próximo poll do browser:
       ├─ /api/code-review/jobs retorna recently_done com o resultado
       ├─ Banner verde: "✓ PR #N revisado — comment 4421… [x]"
       ├─ Trigger 1 refresh extra da lista
       └─ Polling volta pra 30 s
```

## 6. Tratamento de erros

| Cenário | Detecção | Resposta |
|---|---|---|
| URL inválida | regex em `cgi-cr-force.sh` | 400 "URL inválida — esperado `https://github.com/.../pull/N`" |
| Repo fora da whitelist | check contra `repos.txt` | 403 "Repo não monitorado pelo heartbeat" |
| Tick em andamento | `flock --nonblock` falha | 423 "Heartbeat tick em andamento, tente em instantes" |
| Rate limit (≥5/60 s) | mtime dos JSONs em `forced/` | 429 "Muitos force-runs recentes" |
| `claude` rc ≠ 0 | runner | grava `code_reviews.runned=0`, job `failed`, log preservado |
| `claude` rodou mas não publicou | runner (after − before vazio) | grava `code_reviews.runned=0`, job `done` mas com `runned=false` |
| Runner crasha mid-run | `cgi-cr-jobs.sh` heurística | se `kill -0 pid` falha E (`now − started_at > CLAUDE_TIMEOUT+60s`), marca `orphaned` e move pra `done/`. **Não** grava em `code_reviews` (sem snapshot anterior pra comparar) |
| Browser fecha mid-run | sem impacto | runner continua em bg; próximo refresh do dashboard mostra |
| Duplo-clique no `↻` | runner reusa lockfile | 2º clique espera 60 s, depois cai como "lock timeout" |
| SQLite locked | `open_db()` do heartbeat já configura WAL+busy_timeout=30000 | espera transparente |

### Segurança

- `job_id` gerado server-side (timestamp + 4 hex random); jamais aceito do cliente
- URL passa pra `subprocess.run` como **argumento de lista**, não shell string
- `claude` e `gh` chamados via argv array (igual heartbeat)
- LAN-only no nginx (`192.168.15.0/24`)
- Runner roda como user `npu` (mesmo do fcgiwrap); sem `sudo`
- Arquivos em `forced/` com `0600`

## 7. Testes

Não há suíte automatizada (o heartbeat também não tem). Estratégia: **smoke test manual roteirizado** após implementação.

### 7.1. Endpoints básicos

- `curl http://hinc-wiki.local/api/code-review/list` → JSON, schema correto
- `curl http://hinc-wiki.local/api/code-review/jobs` → `{jobs: [], recently_done: []}`
- `curl -X POST '/api/code-review/force?url=invalido'` → 400
- `curl -X POST '/api/code-review/force?url=https://github.com/foo/bar/pull/1'` → 403 (não está em `repos.txt`)

### 7.2. UI

- Carrega `/completo/code-reviews/`, mostra ≤200 reviews recentes
- Filtros (repo, autor, status, busca) diminuem a tabela como esperado
- Click numa linha expande, mostra body renderizado + log
- Click `↻` numa linha abre confirm; OK dispara

### 7.3. End-to-end (1× em PR real)

- Disparar force-run em PR já revisado pelo heartbeat (vai gerar 2ª revisão duplicada — esse é o teste)
- Banner exibe "running" com elapsed
- Em paralelo: se cron tick disparar, `tail -f logs/heartbeat.log` mostra "outro tick em progresso, abortando"
- Após 5-10 min: banner verde, comment novo aparece no PR no GitHub, linha nova na tabela
- `code_reviews` ganhou 1 row com `runned=1` e `comment_id` correto

### 7.4. Não-regressão

- `crontab -l` ainda tem `*/5 * * * * heartbeat.py` intacto
- `systemctl --user status datasette-heartbeat` ainda ativo, responde em :8001
- `nginx -t` antes e depois do deploy; reload ok
- `tail logs/heartbeat.log` no próximo tick após o deploy: tick roda normalmente

### 7.5. Critério de rollback

Se durante deploy:

- `nginx -t` falhar → não recarregar, restaurar `.bak` do vhost
- Próximo tick do heartbeat falhar (verificar via `tail logs/heartbeat.log`) → reverter (mas como **não tocamos** em `heartbeat.py`, isso só aconteceria por algo externo)

## 8. Arquivos criados / modificados — duas camadas

A feature toca duas camadas: **(a)** o repo público `claude-auto-reviewer` (código + docs reutilizáveis por qualquer instalação) e **(b)** o servidor `hinc-wiki` (config nginx, integração com a wiki, doc operacional). O repo é o source of truth do código; o servidor usa symlinks ou cópias.

### 8.1. Arquivos no repo `claude-auto-reviewer` (commitados)

Nova pasta `dashboard/` agrupa toda a feature:

| Caminho relativo no repo | Função |
|---|---|
| `dashboard/web/index.html` | UI single-page (igual ao `completo/code-reviews/index.html` deployado) |
| `dashboard/cgi/cgi-cr-list.sh` | CGI de listagem |
| `dashboard/cgi/cgi-cr-jobs.sh` | CGI de jobs em vôo |
| `dashboard/cgi/cgi-cr-force.sh` | CGI de force-run |
| `dashboard/runner/run-forced-cr.py` | Runner em background |
| `dashboard/nginx/code-review-locations.conf.example` | Snippet de exemplo das 3 locations (LAN-only) pra incluir no vhost do usuário |
| `docs/specs/2026-05-11-code-review-dashboard-design.md` | **Cópia deste spec** versionada com o código |
| `README.md` | +seção "Dashboard (opcional)" documentando a feature, pré-requisitos (nginx + fcgiwrap) e onde achar os exemplos |
| `install.sh` | +modo opcional `--with-dashboard` (ou pergunta interativa, padrão do script): cria symlinks de `dashboard/cgi/*.sh` e `dashboard/runner/*.py` pra `$BIN_DIR` (padrão `~/.local/bin/` ou `~/bin/`) |

### 8.2. Arquivos no servidor `hinc-wiki` (alguns são symlinks pro repo)

| Caminho | Origem | Modificação |
|---|---|---|
| `/home/npu/bin/cgi-cr-list.sh` | **Symlink** → `<repo>/dashboard/cgi/cgi-cr-list.sh` | Padrão dos outros symlinks do heartbeat |
| `/home/npu/bin/cgi-cr-jobs.sh` | **Symlink** → `<repo>/dashboard/cgi/cgi-cr-jobs.sh` | idem |
| `/home/npu/bin/cgi-cr-force.sh` | **Symlink** → `<repo>/dashboard/cgi/cgi-cr-force.sh` | idem |
| `/home/npu/bin/run-forced-cr.py` | **Symlink** → `<repo>/dashboard/runner/run-forced-cr.py` | idem |
| `/home/npu/repos/hinc-docs-wiki/completo/code-reviews/index.html` | **Cópia** de `<repo>/dashboard/web/index.html` | A wiki é um repo separado; não dá pra symlinkar cross-repo de forma limpa. Cópia idempotente (rsync ou cp) no `install.sh` se rodado nesse servidor |
| `/home/npu/.claude/heartbeat/forced/` | Criado em runtime | Diretório de jobs |
| `/home/npu/.claude/heartbeat/logs/forced-cr.log` | Criado em runtime | Log do runner |
| `/etc/nginx/sites-available/hinc-docs-wiki` | Modificado manualmente | +3 locations (consultar `<repo>/dashboard/nginx/...example` pra pattern) |
| `/home/npu/repos/hinc-docs-wiki/index.html` | Modificado | Link "Code Reviews" no rodapé do `/completo` |
| `/home/npu/SERVIDOR.md` | Modificado | Nova seção documentando o dashboard + referência ao repo |
| `/home/npu/.claude/heartbeat/heartbeat.py` | **Não alterado** (symlink intocado) | Apenas importado pelo runner |

### 8.3. Ordem de implementação (consequência da estratégia)

1. **Criar os arquivos no repo** primeiro (em branch novo).
2. **Symlinkar/copiar** pro servidor (manualmente via `ln -s` ou via `install.sh` atualizado).
3. **Editar config do servidor** que não cabe no repo (nginx vhost, link no `/completo`, `SERVIDOR.md`).
4. **Commit + push no repo** (PR ou direto pro main, conforme política do repo).
5. **Smoke test** dos endpoints e UI.

## 9. Decisões abertas (nenhuma neste momento)

Tudo o que veio à tona no brainstorming foi resolvido. O Plan da próxima skill detalha steps de implementação.
