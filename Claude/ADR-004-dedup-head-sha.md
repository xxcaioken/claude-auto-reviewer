---
title: ADR-004 — Dedup de revisão por head_sha
type: adr
status: active
tags:
  - adr
  - backend
  - pattern
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[regras-negocio]]"
  - "[[arquitetura-banco]]"
  - "[[ADR-002-sqlite-append-only]]"
tier: 3
---

# ADR-004 — Idempotência da revisão por `head_sha`

## Contexto

A cada tick do cron, o heartbeat lista PRs abertos e precisa decidir: revisar este PR de novo ou não? Sem dedup, cada tick (5 min) re-revisaria todos os PRs abertos — explosão de custo e ruído no PR.

A chave de dedup determina **quando o sistema revisa de novo**:
- Por `pr_number` apenas → 1 revisão por PR pra sempre. Push novo nunca é revisto.
- Por `head_sha` → revisão por commit. Push novo → revisão nova.
- Por timestamp (ex: "revisar de novo se >24h") → revisão periódica.
- Por hash do diff → revisão se conteúdo do diff muda (mesmo que sha mude por rebase sem mudança).

## Decisão

**Chave de dedup: `(repo, pr_number, head_sha)`.** Persistida na tabela `code_reviews` (append-only — ver [[ADR-002-sqlite-append-only]]).

Implementação em `needs_review` (heartbeat.py:204):
```python
row = conn.execute(
    "SELECT 1 FROM code_reviews WHERE repo=? AND pr_number=? AND head_sha=? LIMIT 1",
    (repo_name, pr_number, head_sha),
).fetchone()
return row is None
```

Se há linha (de qualquer `runned`), pula. Push novo → `head_sha` muda → linha nova → next tick revisa.

## Consequências

### Positivas

- **Revisão por iteração do PR**: dev faz push, revisão nova chega em ≤5 min. Ciclo natural de feedback.
- **Custo previsível**: N PRs com M pushes cada = N×M revisões total. Sem inflação por re-revisão espontânea.
- **Tolerante a rebases interativos**: rebase muda os shas mesmo se conteúdo é o mesmo → re-revisão acontece. Aceitável (rebase é raro e custa pouco).
- **Sem timer global**: não precisa rastrear "última revisão deste PR foi quando?". Dedup é puramente baseado em estado persistente do PR no GitHub.

### Negativas

- **Falha do Claude com `runned=0` BLOQUEIA retry** automático. Linha existe → `needs_review` retorna False. Pra retry, deletar a linha (documentado em [[runbook-debugar-revisao-falhada]]) ou aguardar push novo.
  - **Justificativa**: evita loop de falha (Claude consistentemente fail no mesmo commit gera custo infinito). Operador decide se vale retentar.
  - **Trade-off conhecido**: bug transitório de rede mata revisão até alguém intervir. Tech debt em [[tech-debt]] §TD-002.
- **Não re-revisa após mudança no prompt** sem push novo. Se `code-review.md` muda de regras, PRs já revisados não recebem revisão nova com as novas regras automaticamente. Aceitável (não queremos comentar de novo em PRs já analisados; o próximo push do dev cobre).

### Neutras

- Em conjunto com append-only ([[ADR-002-sqlite-append-only]]), gera múltiplas linhas com diferentes head_shas pro mesmo PR — exatamente o histórico desejado.

## Alternativas consideradas

### A. Dedup por `(repo, pr_number)` apenas

- **Pró**: simplíssimo. 1 revisão por PR pra sempre.
- **Contra**: dev manda push corretivo, sistema ignora. Defeats purpose.
- **Veredicto**: rejeitado por contradizer requisito básico.

### B. Dedup por hash do diff (não por sha)

- **Pró**: rebase sem mudança real não causaria revisão nova.
- **Contra**: requer baixar e hashear o diff a cada tick (custo de I/O e CPU). Hoje só consultamos SQLite.
- **Contra**: rebase é raro. Otimização pra caso pouco comum, prejudica caso comum (push novo).
- **Veredicto**: rejeitado por custo > benefício.

### C. Time-based retry (revisar de novo após X horas)

- **Pró**: cobre bugs transitórios automaticamente.
- **Contra**: revisão dupla em mesmo conteúdo gera ruído no PR (sem `--edit-last`).
- **Contra**: requer timer em cada decisão, não puramente estado-driven.
- **Veredicto**: rejeitado. Se quisermos retry automático, é melhor distinguir tipo de falha (TD-002) do que retry-everything-after-N-hours.

### D. Híbrido: dedup por sha + retry de `runned=0` após N ticks

- **Pró**: cobre o gap do (B negativo de A) sem mudar a fundação.
- **Contra**: complexidade — `needs_review` precisa de `OR (runned=0 AND last_attempt_at < now() - INTERVAL N)`.
- **Veredicto**: candidato pra implementação futura ([[tech-debt]] §TD-002). Não no MVP.

## Quando reabrir

- **TD-002 implementado**: passa a fazer sentido distinguir "falha real" (retry automático) de "filtro do prompt" (não retentar).
- **Volume de PRs alto e Claude flaky**: se >5% das revisões falham por bug transitório, o overhead operacional de retry manual fica caro.
- **`--edit-last` implementado**: muda o cálculo — retry sem `--edit-last` polui PR; com `--edit-last`, retry é gratuito visualmente.
