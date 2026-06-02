---
title: Runbook — backup e cleanup do state.db
type: runbook
status: active
tags:
  - runbook
  - backend
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[arquitetura-banco]]"
  - "[[deploy]]"
  - "[[tech-debt]]"
tier: 3
---

# Runbook — backup e cleanup do `state.db`

## Quando usar
- Backup periódico (defensivo).
- Antes de mudanças disruptivas (DELETE em massa, migration manual).
- DB ficou grande demais e precisa cleanup de revisões antigas.

## Backup

### Backup seguro (WAL-aware)

`state.db` está sendo escrito pelo heartbeat. Cópia simples (`cp`) pode pegar estado inconsistente do WAL. Use `.backup` do SQLite:

```bash
TIMESTAMP=$(date +%F-%H%M)
sqlite3 ~/.claude/heartbeat/state.db \
  ".backup ~/.claude/heartbeat/backups/state-${TIMESTAMP}.db"
```

Cria backup atômico mesmo com escritas concorrentes. Pasta `backups/` já está no `.gitignore`.

Verificar integridade:
```bash
sqlite3 ~/.claude/heartbeat/backups/state-${TIMESTAMP}.db \
  "PRAGMA integrity_check;"
```

Deve retornar `ok`.

### Backup automático recorrente (não implementado por default)

Adicionar ao crontab:
```cron
0 3 * * * sqlite3 ~/.claude/heartbeat/state.db ".backup ~/.claude/heartbeat/backups/state-$(date +\%F).db" && find ~/.claude/heartbeat/backups -name 'state-*.db' -mtime +30 -delete
```

- Backup diário às 3am.
- Retenção 30 dias (`find -mtime +30 -delete`).

Roadmap em [[tech-debt]] §TD-004.

## Restore

1. Parar cron (pra não escrever durante restore):
   ```bash
   crontab -l | grep -v heartbeat.py | crontab -
   ```

2. Matar tick em andamento (se houver):
   ```bash
   pkill -f heartbeat.py
   ```

3. Substituir o DB:
   ```bash
   cp ~/.claude/heartbeat/backups/state-<data>.db ~/.claude/heartbeat/state.db
   ```

4. Limpar arquivos auxiliares órfãos do WAL:
   ```bash
   rm -f ~/.claude/heartbeat/state.db-shm ~/.claude/heartbeat/state.db-wal
   ```

5. Re-armar cron:
   ```bash
   (crontab -l 2>/dev/null; echo "*/5 * * * * /usr/bin/python3 ~/.claude/heartbeat/heartbeat.py >/dev/null 2>&1") | crontab -
   ```

6. Validar tick manual:
   ```bash
   python3 ~/.claude/heartbeat/heartbeat.py
   ```

## Cleanup de revisões antigas

`code_reviews` cresce monotonicamente. Em algum ponto vale apagar revisões antigas de PRs já mergeados/fechados.

### Avaliar tamanho atual
```bash
sqlite3 ~/.claude/heartbeat/state.db <<'SQL'
SELECT
  COUNT(*) AS total_linhas,
  SUM(LENGTH(cr_description) + LENGTH(IFNULL(log, ''))) / 1024 / 1024 AS mb_aproximado
FROM code_reviews;
SQL
```

Tamanho em disco do arquivo:
```bash
du -h ~/.claude/heartbeat/state.db
```

### Backup ANTES de cleanup
(Sempre. Append-only é fácil de bagunçar.)

```bash
sqlite3 ~/.claude/heartbeat/state.db ".backup ~/.claude/heartbeat/backups/pre-cleanup-$(date +%F).db"
```

### Cleanup conservador: PRs MERGED/CLOSED com mais de 180 dias

```bash
sqlite3 ~/.claude/heartbeat/state.db <<'SQL'
-- 1. Quantas linhas seriam afetadas
SELECT COUNT(*) FROM code_reviews
WHERE pr_state IN ('MERGED', 'CLOSED')
  AND runned_at < datetime('now', '-180 days');

-- 2. Backup adicional só dos dados que vão ser apagados (opcional)
.output /tmp/code_reviews_old.csv
.mode csv
SELECT * FROM code_reviews
WHERE pr_state IN ('MERGED', 'CLOSED')
  AND runned_at < datetime('now', '-180 days');
.output stdout

-- 3. Deletar
DELETE FROM code_reviews
WHERE pr_state IN ('MERGED', 'CLOSED')
  AND runned_at < datetime('now', '-180 days');

-- 4. Reclaim disk space
VACUUM;
SQL
```

`VACUUM` reescreve o DB inteiro sem espaço livre interno. Pode demorar em DBs grandes; rodar quando não há cron rodando (pausar cron antes).

### Cleanup do `pr_state` de PRs fechados há muito tempo

`pr_state` é menor (200 bytes/linha), raramente precisa cleanup. Se quiser:

```bash
sqlite3 ~/.claude/heartbeat/state.db <<'SQL'
DELETE FROM pr_state
WHERE state IN ('MERGED', 'CLOSED')
  AND last_seen_at < datetime('now', '-30 days');
SQL
```

(Será re-populado pelo próximo tick se o PR aparecer de novo em `gh pr list` — mas se está MERGED/CLOSED, não aparece, então a linha fica deletada permanentemente.)

## Migração de schema manual

Caso edge: precisa rodar ALTER TABLE não-trivial fora do `init_db`.

Workflow:
1. Pausar cron.
2. Backup.
3. Conectar via `sqlite3` interativo.
4. Aplicar ALTER (lembrar: SQLite tem limitações — não dá DROP COLUMN < 3.35).
5. Re-rodar `init_db` manualmente pra confirmar idempotência:
   ```python
   python3 -c "
   import importlib.util
   spec = importlib.util.spec_from_file_location('hb', '$HOME/.claude/heartbeat/heartbeat.py')
   hb = importlib.util.module_from_spec(spec); spec.loader.exec_module(hb)
   conn = hb.open_db(); hb.init_db(conn); conn.close()
   "
   ```
6. Atualizar `heartbeat.py` (SCHEMA + bloco em `init_db`) e committar.
7. Re-armar cron.

## Validações pós-mudança

Sempre rodar após qualquer mudança no DB:

```bash
sqlite3 ~/.claude/heartbeat/state.db <<'SQL'
-- Integridade
PRAGMA integrity_check;

-- Schema atual
.schema code_reviews
.schema pr_state

-- Contagens sanity-check
SELECT COUNT(*) FROM code_reviews;
SELECT COUNT(*) FROM pr_state;

-- Sem rows com runned=1 sem comment_id (violação de invariante)
SELECT COUNT(*) FROM code_reviews WHERE runned=1 AND comment_id IS NULL;
SQL
```

A última query deve retornar 0 — `runned=1` implica comentário detectado.

## Notas relacionadas
- [[arquitetura-banco]] — schema e queries comuns.
- [[deploy]] §Backup — visão geral.
- [[tech-debt]] §TD-004 (backup automático) e §TD-007 (TTL).
