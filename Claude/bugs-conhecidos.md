---
title: Bugs conhecidos e limitações
type: bug
status: active
tags:
  - bug
  - backend
  - pending
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[arquitetura]]"
  - "[[regras-negocio]]"
  - "[[tech-debt]]"
  - "[[error-handling]]"
tier: 1
---

# Bugs conhecidos e limitações

Itens com risco operacional conhecido. Cada um tem severidade, onde, descrição e fix proposto.

## 🟡 Médios

### B-001: Symlink quebrado se repo é movido depois do `install.sh`

**Onde**: `~/.claude/heartbeat/heartbeat.py` e `~/.claude/commands/code-review.md` (symlinks criados em `install.sh:42-45`).

**Descrição**: o `install.sh` cria symlinks absolutos pro path do repo no momento da instalação (`ln -sf "$REPO_DIR/heartbeat/heartbeat.py" ...`). Se o user mover o clone (ex: `mv ~/code/claude-auto-reviewer ~/projects/`), os symlinks ficam apontando pro path antigo. Cron passa a falhar com `python3: can't open file`.

**Impacto**: heartbeat para silenciosamente (cron loga em `/var/log/syslog`, não no `heartbeat.log`). Detecta-se só quando alguém percebe que PRs não estão sendo revisados.

**Fix proposto**: rodar `./install.sh` de novo do novo path (sobrescreve symlinks). Documentar em runbook. A longo prazo, o `install.sh` poderia detectar e avisar (`readlink -f` no path atual vs path do repo).

**Status**: documentado. Sem fix automático.

---

### B-002: Mudança de `MARKER` invisibiliza histórico anterior

**Onde**: `heartbeat/heartbeat.py:63` (default) e `commands/code-review.md:40` (template).

**Descrição**: `fetch_bot_comments` filtra por `body | startswith("<!-- code-review-bot:v1 -->")`. Se mudar `MARKER` (ex: `v2`), comentários publicados com `v1` deixam de ser detectados. Não quebra revisões novas (snapshot fica consistente before/after com o novo marcador), mas:
- Análise histórica via Datasette mistura "antigos com v1" e "novos com v2" sem distinção.
- Se uma revisão antiga com `v1` ainda está no PR e o sistema revisa de novo o mesmo `head_sha` por algum motivo (delete manual da linha em `code_reviews`), ele NÃO vê a anterior → publica duplicado.

**Impacto**: baixo na operação, médio em análise.

**Fix proposto**: documentar versionamento de `MARKER`. Se for inevitável, escrever migration script que troca `<!-- code-review-bot:v1 -->` por `<!-- code-review-bot:v2 -->` nos comentários antigos via `gh api PATCH`.

**Status**: documentado. Recomendação: nunca mudar `MARKER` em produção.

---

### B-003: PRs muito grandes (>2000 linhas) podem ser truncados sem aviso explícito no SQLite

**Onde**: `commands/code-review.md:73-75` instrui o Claude a fazer revisão parcial dos top-15 arquivos.

**Descrição**: o prompt manda o Claude marcar PRs grandes com `> ⚠️ Revisão parcial: PR grande (X arquivos / Y linhas)`. Isso fica no corpo do comentário (e portanto na coluna `cr_description`), mas não há flag estruturada (boolean coluna `partial`) no SQLite. Consulta tipo "quais PRs foram parcialmente revisados" requer `LIKE '%Revisão parcial%'` em `cr_description`.

**Impacto**: dificulta análise quantitativa. Não afeta a revisão em si.

**Fix proposto**: adicionar coluna `is_partial INTEGER` em `code_reviews` + ALTER TABLE em `init_db`. Claude precisaria sinalizar de forma estruturada (não dá pra inferir só do comentário sem regex frágil).

**Status**: backlog.

---

## 🟢 Baixos

### B-004: `claude --help` no `install.sh` pode causar lag inicial

**Onde**: `install.sh:59` — `python3 "$HEARTBEAT_DIR/heartbeat.py" --help >/dev/null 2>&1 || true`.

**Descrição**: a linha invoca o heartbeat só pra inicializar o módulo, mas `heartbeat.py` não tem suporte a `--help` (argparse). Resulta em rodar o `main()` inteiro durante o `install.sh`, que tenta ler `repos.txt` (vazio) e loga "monitorando 0 repo(s)". O `|| true` engole o exit code, mas o tick roda à toa.

**Impacto**: install fica ~1s mais lento e cria `state.db` antes da linha seguinte (que tentaria fazê-lo via `importlib`). Funcional, mas estranho.

**Fix proposto**: trocar por `python3 -c "import sqlite3; ..."` ou remover (a linha seguinte já cobre via `importlib`).

**Status**: limpeza cosmética.

---

### B-005: `gh auth status` no `check_prerequisites` não valida scopes

**Onde**: `heartbeat.py:336-341`.

**Descrição**: `gh auth status` retorna 0 se o user tá logado, mas não verifica se os scopes `repo` + `workflow` estão presentes. Se o user logou só com `repo`, `gh pr comment` ainda funciona, mas algumas operações de PR (mudar label, etc., que o prompt poderia querer) falham.

**Impacto**: baixo enquanto o prompt só posta comentário. Aumenta se o prompt evoluir pra labels/checks.

**Fix proposto**: parsing do output de `gh auth status` pra checar scopes. Ou rodar `gh api user` que requer `repo` mínimo.

**Status**: backlog, baixa prioridade.

---

## Regras e Invariantes

- **Bugs aqui são triados, não "todos os possíveis"** — pequeno por design, mantido manualmente. Quando descobrir bug novo, adicionar B-NNN (próximo número).
- **B-002 é especialmente perigoso** — mudar `MARKER` em produção. Está marcado mas vale repetir aqui.
- **Severidade reflete impacto operacional**, não complexidade do fix. B-003 é 🟡 porque atrapalha análise (não derruba o sistema), mesmo sendo fácil de implementar.
- **Limitações de design ≠ bugs** — listadas separadamente. Não tentar "consertar" sem ADR ([[_MOC ADRs]]).

## ⚠️ Limitações de design (não são bugs)

- **Sem Windows**: depende de `fcntl` (POSIX only).
- **1 PR por vez**: lock global. Throughput ~6-12 PRs/h. Ver [[ADR-001-cron-vs-webhook]] §Alternativas.
- **Latência de 5 min** entre push e início da revisão (intervalo do cron).
- **Sem `--edit-last`**: cada push gera comentário novo. Roadmap.
- **Sem retry programático**: falha → próximo tick (5 min).
- **`repos.txt` é flat file**: sem hot-reload, sem validação de schema, sem suporte a multi-org via wildcards.

Ver [[tech-debt]] pro plano de evolução.
