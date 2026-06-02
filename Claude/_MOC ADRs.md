---
title: _MOC — Decisões arquiteturais (ADRs)
type: moc
status: active
tags:
  - moc
  - adr
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[_MOC Onboarding]]"
  - "[[_MOC Auto-Reviewer]]"
  - "[[_MOC Operacao]]"
  - "[[_MOC Bugs]]"
tier: 1
---

# _MOC — Decisões arquiteturais (ADRs)

6 ADRs registradas. Cada uma documenta uma decisão estrutural com **Contexto / Decisão / Consequências / Alternativas / Quando reabrir**.

## Lista

| ADR | Decisão | Status |
|---|---|---|
| [[ADR-001-cron-vs-webhook]] | Polling via cron + heartbeat single-process | Ativa |
| [[ADR-002-sqlite-append-only]] | `code_reviews` é append-only (nunca UPDATE) | Ativa |
| [[ADR-003-symlinks-no-install]] | `install.sh` cria symlinks (não copia) | Ativa |
| [[ADR-004-dedup-head-sha]] | Idempotência por `(repo, pr_number, head_sha)` | Ativa |
| [[ADR-005-claude-cli-stdin]] | Claude posta direto via `gh pr comment`; heartbeat detecta via snapshot | Ativa |
| [[ADR-006-leitura-vault-repo-alvo]] | Prompt lê `<REPO_PATH>/Claude/` quando existe; graceful degradation senão | Ativa |

## Por tema

### Modelo de invocação
- [[ADR-001-cron-vs-webhook]] — polling.
- [[ADR-004-dedup-head-sha]] — chave de retry.
- [[ADR-005-claude-cli-stdin]] — quem posta.

### Modelo de contexto
- [[ADR-006-leitura-vault-repo-alvo]] — leitura do `Claude/` do repo-alvo durante review.

### Persistência
- [[ADR-002-sqlite-append-only]] — modelo de escrita.

### Deploy / distribuição
- [[ADR-003-symlinks-no-install]] — symlinks vs cópia.

## Como cada ADR afeta o código

| Decisão | Onde no código |
|---|---|
| [[ADR-001-cron-vs-webhook]] | linha de cron sugerida em `install.sh`; lock fcntl em `main()` (heartbeat.py:351-356) |
| [[ADR-002-sqlite-append-only]] | `save_review` sempre INSERT (heartbeat.py:260-279); schema `code_reviews` (SCHEMA constant); índices `idx_cr_pr_time`/`idx_cr_pr_sha` |
| [[ADR-003-symlinks-no-install]] | `ln -sf` em `install.sh:42-45` |
| [[ADR-004-dedup-head-sha]] | `needs_review` em heartbeat.py:204-219 |
| [[ADR-005-claude-cli-stdin]] | `invoke_claude` em heartbeat.py:241-257; snapshot before/after em `process_pr` (282-307); marcador HTML em `commands/code-review.md` |
| [[ADR-006-leitura-vault-repo-alvo]] | `commands/code-review.md` §"Contexto do repo via Obsidian vault" + regra estrita 7 |

## Decisões implícitas (sem ADR formal — backlog)

Estas são decisões reais mas que não chegaram a virar ADR. Candidatos pra documentar caso virem controversas:

- **Stdlib only, sem deps externas** — implícito em `dependencias.md`. Razão: zero supply-chain risk, install trivial.
- **Fail-soft em vez de fail-fast** — implícito em `error-handling.md`. Erros não derrubam tick.
- **Logs em arquivo + stdout** — handler duplo no `logging.basicConfig`. Permite tail-f manual + redirecionamento do cron.
- **`bypassPermissions` + `CLAUDE_CWD=$HOME` defaults** — duas decisões juntas em `invoke_claude`. Documentadas em [[regras-negocio]] §3 mas não tem ADR formal.
- **Não usar `gh auth` programaticamente** — depende do user ter rodado `gh auth login` previamente. Não tentamos fazer flow OAuth dentro do install.

Se algum destes virar tópico de debate, promover pra ADR completa.

## Quando criar uma nova ADR

Criar quando:
- Decisão tem **alternativas reais** que foram consideradas e rejeitadas.
- Decisão **restringe escolhas futuras** (ex: schema fundamental).
- Decisão **não é óbvia pelo código** (precisa de justificativa).

Usar [[_templates/adr]] como base.

Numeração: continuar a partir da última ADR (próxima = ADR-006).

## Navegação por MOC

- [[_MOC Onboarding]] — caminho de entrada no projeto.
- [[_MOC Auto-Reviewer]] — visão técnica do sistema.
- [[_MOC Operacao]] — runbooks e operação dia-a-dia.
- [[_MOC Bugs]] — débitos e bugs conhecidos.
