---
title: Arquitetura do banco (SQLite)
type: architecture
status: active
tags:
  - backend
  - pattern
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[arquitetura]]"
  - "[[regras-negocio]]"
  - "[[modulo-heartbeat]]"
  - "[[runbook-rotacionar-state-db]]"
tier: 2
---

# Arquitetura do banco — `state.db`

SQLite local em `$HEARTBEAT_DIR/state.db` (default `~/.claude/heartbeat/state.db`). Auto-criado pelo `init_db` na primeira execução do heartbeat. Duas tabelas + dois índices. WAL mode.

## Configuração da conexão

`open_db()` (heartbeat.py:118-123):
```python
conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT)   # default 30s
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=30000")                  # 30s em ms
return conn
```

**Por quê WAL**: permite leituras simultâneas a uma escrita. Caso real: heartbeat escrevendo `code_reviews` + datasette servindo a web UI lendo a mesma DB. Sem WAL, datasette daria "database is locked" frequentemente.

**Por quê `busy_timeout=30000`**: se outro processo segura uma escrita por até 30s, sqlite espera em vez de erro imediato. Combina com `timeout=30` do connect.

**Arquivos auxiliares criados pelo WAL**: `state.db-shm` e `state.db-wal`. Ambos no `.gitignore`. Não copiar `state.db` sem incluir os auxiliares ou usar `sqlite3 .backup`.

---

## Tabela `pr_state`

**Propósito**: cache do último estado conhecido de cada PR. UPSERT por `(repo, pr_number)`.

```sql
CREATE TABLE pr_state (
  repo TEXT NOT NULL,
  pr_number INTEGER NOT NULL,
  head_sha TEXT NOT NULL,
  is_draft INTEGER NOT NULL,        -- 0 ou 1
  state TEXT NOT NULL,              -- OPEN / MERGED / CLOSED
  last_seen_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
  PRIMARY KEY (repo, pr_number)
);
```

**Invariantes**:
- 1 linha por `(repo, pr_number)`. Sempre o último estado.
- Atualizada **toda vez** que `update_pr_state` (heartbeat.py:222) é chamada — mesmo que `needs_review` retorne `False` depois (`process_repo` chama `update_pr_state` antes de `needs_review`).
- Não tem histórico — UPDATE perde estado anterior.

**Quando consultar**:
- "Quantos PRs abertos vejo agora?" → `SELECT COUNT(*) FROM pr_state WHERE state='OPEN'`.
- "Qual o último head_sha que vimos pra PR X?" → `SELECT head_sha FROM pr_state WHERE repo=? AND pr_number=?`.

**Quando NÃO consultar**: nunca pra decidir se revisa — quem decide é `code_reviews` (`needs_review`).

---

## Tabela `code_reviews` (append-only)

**Propósito**: histórico imutável de toda tentativa de CR.

```sql
CREATE TABLE code_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repo TEXT NOT NULL,                       -- nome local (de repos.txt)
  pr_number INTEGER NOT NULL,
  pr_name TEXT NOT NULL,                    -- título do PR
  pr_creator TEXT NOT NULL,                 -- @login do autor
  pr_url TEXT NOT NULL,
  head_sha TEXT NOT NULL,
  cr_description TEXT NOT NULL DEFAULT '',  -- markdown COMPLETO do comentário (ou '' se runned=0)
  pr_state TEXT NOT NULL,                   -- estado do PR no momento (snapshot)
  comment_id TEXT,                          -- id do comment no GitHub (NULL se runned=0)
  log TEXT,                                 -- stdout/stderr do claude truncado
  runned INTEGER NOT NULL DEFAULT 0,        -- 1=publicou comment detectado, 0=tentou e não publicou
  runned_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE INDEX idx_cr_pr_time ON code_reviews(repo, pr_number, runned_at DESC);
CREATE INDEX idx_cr_pr_sha  ON code_reviews(repo, pr_number, head_sha);
```

**Invariantes (sagradas)**:
1. **Nunca UPDATE.** Só INSERT via `save_review` (heartbeat.py:260).
2. **1 linha = 1 invocação do Claude.** Sucesso ou falha. Custo real ≈ contagem de linhas com `runned=1` × custo por revisão.
3. **`(repo, pr_number, head_sha)` é único POR INTENÇÃO** — `needs_review` consulta esta chave e pula se já existe (independente de `runned`). Não há UNIQUE constraint formal porque `runned=0` pode legitimamente coexistir com retry manual (ver §"Forçar retry" abaixo). Mas em operação normal, é único.
4. **`cr_description = ''` quando `runned=0`.** Sem comentário publicado, não há corpo. Verificação cruzada: se `runned=1` → `cr_description != ''` E `comment_id != NULL`.

**Índices**:
- `idx_cr_pr_time` (DESC em `runned_at`): consultas "últimas revisões deste PR".
- `idx_cr_pr_sha`: lookup do `needs_review` (heartbeat.py:215-218).

---

## Queries comuns

### Listar últimas 20 revisões
```sql
SELECT runned_at, repo, pr_number, runned, pr_creator, substr(pr_name, 1, 50)
FROM code_reviews
ORDER BY runned_at DESC
LIMIT 20;
```

### Revisões que falharam (runned=0) — investigação
```sql
SELECT id, repo, pr_number, runned_at, substr(log, 1, 500)
FROM code_reviews
WHERE runned = 0
ORDER BY runned_at DESC
LIMIT 10;
```

### Custo estimado (1 invocação = 1 linha)
```sql
SELECT
  DATE(runned_at) AS dia,
  COUNT(*) AS invocacoes,
  SUM(runned) AS publicadas,
  COUNT(*) - SUM(runned) AS falhas_ou_filtradas
FROM code_reviews
GROUP BY DATE(runned_at)
ORDER BY dia DESC
LIMIT 30;
```

### PRs com mais retries (head_sha mudou várias vezes)
```sql
SELECT repo, pr_number, COUNT(DISTINCT head_sha) AS shas, COUNT(*) AS tentativas
FROM code_reviews
GROUP BY repo, pr_number
HAVING shas > 1
ORDER BY tentativas DESC;
```

### Latência de revisão (push → comentário)
**Não dá pra calcular só com `state.db`**. Precisa do timestamp do commit (vem do GitHub). Roadmap em [[tech-debt]] §TD-008.

---

## Migrations

`init_db` (heartbeat.py:126-136) é o "migrator". Executa o `SCHEMA` (CREATE IF NOT EXISTS) e depois:

```python
cols = {row[1] for row in conn.execute("PRAGMA table_info(code_reviews)")}
if "log" not in cols:
    conn.execute("ALTER TABLE code_reviews ADD COLUMN log TEXT")
if "runned" not in cols:
    conn.execute("ALTER TABLE code_reviews ADD COLUMN runned INTEGER NOT NULL DEFAULT 0")
```

**Padrão**: adicionar coluna → adicionar bloco `if "coluna" not in cols`. Pra remover/renomear, precisaria de migration manual (SQLite tem `ALTER TABLE ... RENAME COLUMN` desde 3.25, mas tabelas devem ser recriadas pra DROP COLUMN < 3.35).

**Próxima migration prevista** ([[tech-debt]] §TD-005): `failure_reason TEXT` em `code_reviews`, diferenciando falha de `gh`/timeout/filtro do prompt.

---

## Forçar retry manual

Cenário: revisão deu `runned=0` por bug transitório do Claude, e o `head_sha` ainda é o mesmo. Como forçar nova tentativa?

```bash
# 1. Localizar a linha
sqlite3 ~/.claude/heartbeat/state.db \
  "SELECT id, repo, pr_number, head_sha, runned, substr(log,1,200)
   FROM code_reviews WHERE runned=0 ORDER BY id DESC LIMIT 5;"

# 2. Apagar a linha (DELETE no append-only — só pra retry consciente)
sqlite3 ~/.claude/heartbeat/state.db "DELETE FROM code_reviews WHERE id = ?;"

# 3. Próximo tick do cron vai re-revisar (needs_review volta a True).
```

Alternativamente, sem mexer no DB: aguardar push novo (muda `head_sha`).

Detalhes em [[runbook-debugar-revisao-falhada]].

---

## Backup

**Não há backup automático.** Roadmap em [[tech-debt]] §TD-004.

Backup manual seguro (não copiar `state.db` direto quando heartbeat está rodando — WAL pode estar inconsistente):

```bash
sqlite3 ~/.claude/heartbeat/state.db \
  ".backup '/tmp/state-backup-$(date +%F-%H%M).db'"
```

Pra restaurar: parar cron, substituir `state.db`, deletar `state.db-shm` e `state.db-wal`, reativar cron.

---

## Regras e Invariantes

- **`code_reviews` nunca recebe UPDATE** — só INSERT (ver [[ADR-002-sqlite-append-only]]). Quebrar isto destrói auditoria histórica.
- **`runned=1` → `comment_id != NULL` E `cr_description != ''`** — invariante implícita, validada em [[runbook-rotacionar-state-db]] §Validações pós-mudança.
- **`(repo, pr_number, head_sha)` é único POR INTENÇÃO** em `code_reviews`, sem UNIQUE constraint formal — `needs_review` consulta esta chave.
- **WAL mode obrigatório** — `PRAGMA journal_mode=WAL` em todo `open_db()`. Sem isto, datasette read concurrent quebra com "database is locked".
- **`busy_timeout=30000`** + `timeout=SQLITE_TIMEOUT` no connect — proteção dupla contra "database is locked" em ticks paralelos (que não acontecem por design, mas defesa em profundidade).
- **Migrations em `init_db` são idempotentes** — `CREATE IF NOT EXISTS` + checks `if "col" not in cols`. Adicionar coluna nova segue mesmo padrão.

## Tamanho esperado

Heurísticas:
- `pr_state`: ~200 bytes por PR. 100 PRs ativos = 20KB.
- `code_reviews`: ~50KB por linha (média, dominado por `cr_description` em markdown). 1000 revisões = 50MB.

Sem retenção (TD-007), DB cresce linearmente com `code_reviews`. 50MB/ano em uso médio (~1000 revisões/ano). Aceitável muito além disso.
