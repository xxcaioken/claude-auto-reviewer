---
title: ADR-001 — Cron + heartbeat vs GitHub webhook
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
  - "[[arquitetura]]"
  - "[[regras-negocio]]"
  - "[[tech-debt]]"
tier: 3
---

# ADR-001 — Cron + heartbeat polling vs GitHub webhook

## Contexto

O sistema precisa reagir a "PR novo" ou "push novo em PR existente" em N repos. Duas arquiteturas naturais:

1. **Polling**: cron periódico chama `gh pr list` em cada repo, compara com estado local.
2. **Push**: GitHub webhook envia evento `pull_request` pra um endpoint HTTP que dispara a revisão.

Esta é a decisão de qual usar pro MVP.

## Decisão

**Polling via cron + heartbeat single-process.** Sem HTTP server. Sem deploy de webhook receiver.

Implementação: `cron */5 * * * * heartbeat.py`. Cada tick lista PRs abertos via `gh pr list` e filtra por `head_sha` já processado (dedup em `code_reviews`).

## Consequências

### Positivas

- **Zero infraestrutura**: roda na máquina do dev/operador. Sem cloud, sem ngrok, sem reverse proxy, sem certificado TLS.
- **Sem secret de webhook**: GitHub webhook requer `X-Hub-Signature-256` validation, secret pra rotacionar, etc. Polling usa só `gh auth` (que o user já configurou).
- **Tolerância a downtime**: máquina desligada por 4 horas → ao voltar, o próximo tick lista PRs abertos e cobre todos os que faltaram. Webhook perdido = perda permanente sem replay.
- **Single source of truth pra "o que está aberto"**: `gh pr list` é autoritativo. Webhook obriga reconciliar contra GitHub mesmo assim pra evitar drift.
- **Mais simples de debugar**: comportamento totalmente síncrono. Sem fila de eventos, sem retry exponencial de webhook delivery.
- **Funciona em qualquer ambiente que tem cron e internet**: VPS pequena, Raspberry Pi, laptop.

### Negativas

- **Latência média de 2.5 min** entre push e início da revisão (intervalo de 5 min ÷ 2). Inaceitável pra CR em tempo real, aceitável pra automação.
- **Custo proporcional ao número de repos × frequência do cron**: cada tick faz N chamadas `gh pr list`. Com 10 repos: 10 × 12 ticks/h = 120 chamadas/h. Rate limit do GitHub (5000 req/h autenticado) cobre folgado.
- **Não escala pra dezenas de repos com PRs em alta cadência**: a 100 repos × 12 ticks/h = 1200 chamadas/h. Ainda cabe, mas começa a ser desperdício.
- **Lote longo pode atravessar ticks** (lock fcntl aborta os intermediários — ver [[regras-negocio]] §7). Webhook permitiria paralelismo natural por evento.

### Neutras

- Idempotência via `head_sha` é **igualmente necessária** nos dois modelos (webhooks têm at-least-once delivery).
- Persistência em SQLite serve aos dois.

## Alternativas consideradas

### A. GitHub Webhook → endpoint HTTP local (ngrok)

- **Pró**: latência <10s entre push e revisão.
- **Contra**: ngrok pago pra URL estável, ou cloudflared. Mais peças móveis.
- **Contra**: secret + signature validation. Mais código de segurança.
- **Contra**: durante downtime, eventos perdidos (GitHub redelivers só por 24h, manual).
- **Veredicto**: complexidade > benefício pro MVP. Considerar quando o uso justificar (>20 PRs/h sustentados ou requisito de latência).

### B. GitHub Webhook → SaaS event router (Zapier, Pipedream, Make)

- **Pró**: sem infra própria.
- **Contra**: vendor lock-in, custo recorrente, latência adicional do middleman.
- **Veredicto**: descartado — adiciona custo financeiro sem ganho funcional vs polling.

### C. GitHub Actions workflow no próprio repo monitorado

- **Pró**: dispara no `pull_request` event nativamente. Sem polling.
- **Contra**: requer commit em cada repo monitorado (custo de onboarding). Quebra "monitor a partir de fora".
- **Contra**: secrets do Claude API key em cada repo separadamente.
- **Veredicto**: descartado — quebra o modelo "instalar 1 vez, monitorar muitos".

### D. Daemon long-running (sem cron)

- **Pró**: latência configurável (sleep 30s entre polls).
- **Contra**: precisa gerenciar lifecycle (systemd service), restart em crash, lock contra duplicação.
- **Contra**: indistinguível operacionalmente de cron, mais código.
- **Veredicto**: cron faz lifecycle de graça. Daemon vira opção se intervalo < 1min for necessário.

## Quando reabrir

Sinais pra revisitar esta ADR:
- Latência <5min vira requisito do time.
- Throughput sustentado >20 PRs/h por instância.
- Múltiplas instâncias em produção (precisariam de lock global externo).
- Time tem stomach pra rodar 1 HTTP service permanente.

Provavelmente migra pra **webhook + queue local (SQLite-backed) + worker** com fallback polling pra reconciliar.
