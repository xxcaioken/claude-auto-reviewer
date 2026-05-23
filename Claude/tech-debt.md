---
title: Tech debt e roadmap
type: tech-debt
status: active
tags:
  - debt/alta
  - debt/media
  - debt/baixa
  - backend
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[arquitetura]]"
  - "[[bugs-conhecidos]]"
  - "[[dependencias]]"
tier: 1
---

# Tech debt e roadmap

Débitos técnicos por severidade. Itens do README "Roadmap (não prometido)" estão aqui com contexto adicional.

## 🔴 Alta

### TD-001: Zero testes automatizados

**Onde**: o repo inteiro. Sem `tests/`, sem `pytest.ini`, sem CI.

**Por quê é alto**: o `heartbeat.py` tem lógica subtil (snapshot before/after, dedup por `head_sha`, lock fcntl, parsing de `repos.txt`). Toda mudança hoje depende de teste manual em PR real. Fica mais arriscado a cada feature.

**Impacto**: regressões silenciosas. Refatoração inibida.

**Plano**: começar por testes unitários puros (não precisam mockar `gh`):
- `load_repos()` com vários formatos de `repos.txt`.
- `needs_review()` cobrindo as 3 condições de skip (draft, label, head_sha).
- Schema migrations (`init_db()` em DB com schema antigo).
- Integração de `process_pr` com `subprocess.run` mockado (verificar comando exato).

Stack sugerida: `pytest` + `pytest-mock`. Sem deps de produção.

**Estimativa**: 1–2 dias.

---

### TD-002: Sem retry com backoff em falha transitória do `gh`

**Onde**: `gh_pr_list` (heartbeat.py:158), `fetch_bot_comments` (179).

**Por quê é alto**: falha de rede → `runned=0` → como `needs_review` consulta por `head_sha` (não por `runned`), o PR fica **sem retry automático**. Operador precisa intervir.

**Plano**: ou (a) retry com backoff exponencial nas chamadas `gh` (`tenacity` ou loop manual com `time.sleep`), ou (b) mudar `needs_review` pra reconsiderar PRs com `runned=0` após N ticks (ex: 6 ticks = 30 min).

Opção (b) é mais segura (não retentaria CR caro do Claude, só a checagem `gh`). Requer um critério pra distinguir falha de `gh` (warning no log) vs falha de filtro do prompt (`rc=0`, sem comentário). Coluna `runned=0` hoje mistura os dois.

**Estimativa**: 4–8h pra opção (b) com nova coluna `failure_reason`.

---

## 🟡 Média

### TD-003: `--edit-last` em vez de comentário novo a cada push

**Onde**: `process_pr` (heartbeat.py:282-307) e `commands/code-review.md` §Postagem direta.

**Por quê**: PRs com muitas iterações ficam ruidosos. Hoje cada push = comentário novo. README §Roadmap menciona.

**Trade-off**: edição perde histórico no PR. Mantém no SQLite. Provavelmente quer **flag por-repo** em `repos.txt` (`enabled` ganha mais valores: `0` paused, `1` always-new, `2` edit-last).

**Plano**: 
- Adicionar coluna `last_comment_id` em `pr_state` (não em `code_reviews` que é append-only).
- Em `process_pr`, se modo `edit-last`, passar `--comment-id` (parâmetro novo) pro prompt. Prompt usa `gh api PATCH /repos/.../issues/comments/<id>` em vez de `gh pr comment`.

**Estimativa**: 1 dia (precisa testar interação com snapshot before/after — talvez precise mudar a detecção).

---

### TD-004: Falta backup automático do `state.db`

**Onde**: instalação não cria backup. Roadmap menciona `sqlite3 .backup`.

**Por quê**: histórico de revisões é o valor operacional do repo. Perdê-lo = perde análise de custo, evolução do prompt, audit trail.

**Plano**: linha cron diária `sqlite3 ~/.claude/heartbeat/state.db ".backup '~/.claude/heartbeat/backups/state-$(date +%F).db'"` + retenção de 30 dias. Documentar no `install.sh` opcional. Pasta `backups/` já está no `.gitignore`.

**Estimativa**: 1h.

---

### TD-005: `repos.txt` sem validação ou hot-reload

**Onde**: `load_repos()` (heartbeat.py:139).

**Sintomas**:
- Linha mal-formada (faltando `|`) loga warning e segue. Bom em CI, ruim pro user que digitou errado e não percebe.
- Editar `repos.txt` no meio de um tick longo: mudança só vale no próximo tick. Aceitável, mas não óbvio.
- Sem suporte a comentário inline (`# coisa` no fim de uma linha). Só linha começando com `#`.

**Plano**: tornar `load_repos` mais defensivo + comando `python3 heartbeat.py --validate-repos`. Mensagens de erro com número da linha.

**Estimativa**: 2h.

---

## 🟢 Baixa

### TD-006: Paralelismo entre PRs

**Onde**: `process_repo` (heartbeat.py:310) — loop sequencial.

**Por quê é baixo**: throughput de 6-12 PRs/h é suficiente pro caso atual. Paralelizar exige refatorar lock global → lock por-PR + workers (asyncio ou threads), cuidar de contenção no SQLite, e gerenciar custo (N invocações Claude paralelas).

**Quando vira alto**: se monitorar 5+ repos com >12 PRs/h sustentados.

---

### TD-007: TTL pra revisões antigas de PRs merged

**Onde**: `code_reviews` cresce sem limite.

**Impacto**: DB hoje (estimativa) cresce ~50KB por revisão (markdown grande no `cr_description`). 1000 revisões = 50MB. Não é problema agora. Será em 1 ano de uso intenso.

**Plano**: script periódico `DELETE FROM code_reviews WHERE pr_state IN ('MERGED','CLOSED') AND runned_at < datetime('now','-180 days')`. Com backup antes (TD-004).

---

### TD-008: Métricas operacionais

**Onde**: não existe.

**O que é**: script diário/semanal com snapshot:
- PRs revisados (totais e por repo).
- Latência média (commit push → comentário publicado).
- Taxa de falha (`runned=0` / total).
- Custo estimado por dia.

**Plano**: notebook Jupyter ou script Python que lê `state.db` e gera markdown report. Sem novo serviço.

---

### TD-009: `code-review.md` tem trecho em modo Interativo que cita `AskUserQuestion`

**Onde**: `commands/code-review.md:222-227`.

**Status**: funciona em modo interativo (CLI claude com TTY). É comportamento esperado, não é débito real. Listado aqui só pra registro: quando o prompt for refatorado, esse fluxo precisa testar humano-in-the-loop separadamente.

---

## Regras e Invariantes

- **Severidade prioriza débitos que aumentam risco operacional**, não os "mais fáceis de pagar". TD-001 (zero testes) é 🔴 porque amplifica risco de qualquer mudança.
- **Itens marcados "documentado, sem fix automático" são intencionais** — esperam intervenção humana, não automação.
- **Roadmap do README ≠ tech debt** — roadmap é "queremos fazer", débito é "deveríamos ter feito". A diferença importa pro planejamento.
- **Ao implementar débito grande, atualizar ADR correspondente OU criar nova** — não basta corrigir o código.

## Decisões adiadas (não são débitos)

- **Suporte Windows**: sem demanda.
- **GitHub Enterprise / repos privados de org externa**: requer `gh auth` mais elaborado. Sem demanda.
- **Multi-modelo**: hoje usa Claude default do CLI. Permitir Sonnet/Haiku por repo seria útil pra custo, mas requer CLI flag não-trivial.
