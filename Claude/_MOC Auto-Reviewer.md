---
title: _MOC — Auto-Reviewer (visão técnica)
type: moc
status: active
tags:
  - moc
  - backend
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[_MOC Onboarding]]"
  - "[[_MOC Operacao]]"
  - "[[_MOC Bugs]]"
  - "[[_MOC ADRs]]"
tier: 1
---

# _MOC — Auto-Reviewer (visão técnica)

Mapa por **componente do sistema**. Pra cada peça: qual nota descreve, qual ADR fundamenta.

## Arquitetura geral

- [[arquitetura]] — overview + diagrama de fluxo.
- [[dependencias]] — runtime externo (Python, Claude CLI, gh, SQLite, cron, fcntl).

## Camada de execução (heartbeat)

- [[modulo-heartbeat]] — anatomia funcional do `heartbeat.py`.
- [[regras-negocio]] — invariantes operacionais (idempotência, lock fcntl, fail-soft).
- [[error-handling]] — todos os erros possíveis + comportamento esperado.

Decisões relacionadas:
- [[ADR-001-cron-vs-webhook]] — por que polling em vez de webhook.
- [[ADR-004-dedup-head-sha]] — chave de idempotência por `head_sha`.

## Camada de prompt (Claude)

- [[regras-prompt-review]] — análise do `commands/code-review.md`.

Decisões relacionadas:
- [[ADR-005-claude-cli-stdin]] — Claude posta direto, heartbeat detecta via snapshot.
- [[ADR-006-leitura-vault-repo-alvo]] — prompt lê `<REPO_PATH>/Claude/` quando existe pra contextualizar review.

## Camada de persistência (SQLite)

- [[arquitetura-banco]] — schema, queries comuns, configs WAL.

Decisões relacionadas:
- [[ADR-002-sqlite-append-only]] — `code_reviews` é append-only.

## Camada de empacotamento (install + deploy)

- [[deploy]] — bootstrap, updates, datasette.
- [[env-setup]] — env vars + validação.

Decisões relacionadas:
- [[ADR-003-symlinks-no-install]] — symlinks em vez de cópia.

## Camada de qualidade

- [[bugs-conhecidos]] — bugs ativos.
- [[tech-debt]] — débitos por prioridade.
- [[infra-testes]] — estado dos testes (zero atualmente).
- post-mortems/ — incidentes resolvidos (vazia hoje).

## Mapa de invariantes críticas

| Invariante | Onde mora | Quebra se... |
|---|---|---|
| Marcador HTML = primeira linha do comentário | `code-review.md` + `MARKER` env | Detecção falha → `runned=0` falso |
| Chave única `(repo, pr_number, head_sha)` em `code_reviews` | `needs_review` | Re-revisão custosa do mesmo commit |
| Lock fcntl global | `main` (heartbeat.py:351) | Ticks paralelos duplicam trabalho |
| `cwd=$HOME` na invocação do Claude | `CLAUDE_CWD` default | Comando local sobrescreve global |
| `bypassPermissions` na invocação | `invoke_claude` | Claude trava pedindo aprovação |
| `code_reviews` append-only | Política, não constraint formal | Perde histórico de retries |

Ver [[regras-negocio]] pra justificativa de cada uma.

## Navegação por MOC

- [[_MOC Onboarding]] — caminho de entrada no projeto.
- [[_MOC Operacao]] — runbooks e operação dia-a-dia.
- [[_MOC Bugs]] — débitos e bugs conhecidos.
- [[_MOC ADRs]] — decisões arquiteturais.
