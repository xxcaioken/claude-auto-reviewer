---
title: ADR-002 — SQLite append-only para code_reviews
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
  - "[[arquitetura-banco]]"
  - "[[regras-negocio]]"
  - "[[ADR-004-dedup-head-sha]]"
tier: 3
---

# ADR-002 — Tabela `code_reviews` como append-only

## Contexto

Cada revisão tem dados que mudam ao longo da vida de um PR (status, comentário, log). Modelos possíveis pra persistir isso:

- **Append-only**: 1 linha por tentativa. Nunca UPDATE.
- **UPSERT por PR**: 1 linha por `(repo, pr_number)`, atualizada a cada nova revisão.
- **UPSERT por commit**: 1 linha por `(repo, pr_number, head_sha)`.

## Decisão

**Append-only**: tabela `code_reviews` recebe só INSERT. Cada invocação do Claude gera 1 linha, independente de sucesso ou falha. Mesma combinação `(repo, pr_number, head_sha)` pode ter múltiplas linhas em retry manual.

Tabela secundária `pr_state` faz UPSERT por `(repo, pr_number)` — guarda **só o último estado** observado do PR (cache não-autoritativo).

## Consequências

### Positivas

- **Auditoria barata e completa**: cada revisão fica registrada com timestamp. Inclui as que falharam. Cruzando `id` × `runned_at`, dá pra reconstruir todo o histórico de tentativas.
- **Cálculo de custo direto**: `SELECT COUNT(*) FROM code_reviews` ≈ número de invocações do Claude. Com filtro `runned=1` → publicações reais. Diferença → falhas/filtros.
- **Análise de evolução do prompt**: depois de mudar `code-review.md`, dá pra comparar revisões antes/depois pra mesmo PR (se houve retry).
- **Tolerância a corrupção parcial**: append-only é mais robusto a falha de mid-write em SQLite. UPDATE em row existente pode corromper a row se WAL morre no meio.
- **Modelo mental simples**: "linha = evento". Sem confusão de "essa linha tem dados do tick atual ou anterior?".

### Negativas

- **DB cresce linearmente** com número de invocações. ~50KB/linha (markdown grande). 1000 linhas = 50MB. Aceitável muito além do uso atual. Plano de TTL em [[tech-debt]] §TD-007.
- **Consulta "estado atual" é mais complexa**: requer `ORDER BY runned_at DESC LIMIT 1` ou subquery. Mitigado pela tabela auxiliar `pr_state` (cache).
- **Retry manual requer DELETE** (não UPDATE): cliente que quer forçar nova tentativa precisa apagar a linha. Documentado em [[runbook-debugar-revisao-falhada]].

### Neutras

- Não impede `pr_state` de existir paralelo — modelo híbrido OK.

## Alternativas consideradas

### A. UPSERT por `(repo, pr_number)`

```sql
INSERT INTO code_reviews (...) VALUES (...)
ON CONFLICT(repo, pr_number) DO UPDATE SET ...
```

- **Pró**: DB compacto. Sempre N linhas onde N = PRs únicos.
- **Contra**: perde histórico de retries. Não dá pra contar custo real.
- **Contra**: perde rastreio de evolução (revisão antes/depois do prompt mudar pro mesmo PR).
- **Contra**: se Claude falha hoje e funciona amanhã (mesmo head_sha), o UPDATE mascara a falha original.
- **Veredicto**: economia de espaço não justifica perda de auditoria.

### B. UPSERT por `(repo, pr_number, head_sha)`

- **Pró**: cabe entre A e append-only.
- **Contra**: ainda perde retries no mesmo commit. Cenário real: bug transitório do Claude → retry manual → mesma linha sobrescrita.
- **Veredicto**: mistura comportamento "1 linha por commit" com "retry sobrescreve" — confuso.

### C. Tabela separada `code_reviews_log` só pra histórico

- 2 tabelas: `code_reviews` (1 linha por PR) + `code_reviews_log` (append-only, FK pra a primeira).
- **Pró**: queries "estado atual" simples + histórico preservado.
- **Contra**: complexidade de manter consistência entre as 2 tabelas. Cada INSERT em código se torna 2 statements + transaction.
- **Veredicto**: rejeitado por sobre-engenharia pro MVP. `pr_state` faz o trabalho de "cache de estado atual" sem precisar de FK.

## Quando reabrir

- **TTL implementado** (TD-007): se queries de cleanup ficam complexas, considerar refatorar pra modelo C com pivô claro entre "ativo" e "histórico".
- **Volume real** ultrapassar 10K linhas e consultas ad-hoc ficarem lentas: índices adicionais antes de mudar de modelo.
- **Necessidade de "qual a revisão atual deste PR"**: ainda dá pra resolver com índice `idx_cr_pr_time` + LIMIT 1. Só se virar bottleneck, considerar materialized view ou trigger.
