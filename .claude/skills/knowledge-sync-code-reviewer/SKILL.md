---
name: knowledge-sync-code-reviewer
description: Use quando voltar a mexer no repo claude-auto-reviewer após mudanças no código (heartbeat.py, code-review.md, install.sh, schema SQL). Valida drift entre código e vault local, e opcionalmente verifica estrutura dos vaults dos 6 repos NPU monitorados. Read-only nos vaults remotos.
---

# Knowledge Sync — Code Reviewer

Skill local versionada no repo `claude-auto-reviewer`. Valida coerência entre código (`heartbeat/`, `commands/`, `install.sh`, `.env.example`) e vault Obsidian (`Claude/*.md`) deste repo. Opcionalmente verifica estrutura dos vaults dos 6 repos NPU monitorados (read-only).

**Independente do `/knowledge-sync` genérico do NPU-Brain** — sem `.knowledge-sync.yml`, sem sister vaults bidirecional, sem hooks automáticos.

## Quando usar

- Após qualquer mudança em `heartbeat/heartbeat.py`, `commands/code-review.md`, `install.sh`, `.env.example`, ou notas do `Claude/`.
- Antes de fazer commit de mudanças significativas no repo.
- Quando suspeitar que vault está stale (line numbers, regras desatualizadas).
- Periodicamente, mesmo sem mudança (validação preventiva).

## Pré-requisito

Rodar com `cwd` na raiz deste repo (`claude-auto-reviewer`). Validação inicial aborta se `Claude/` ou `heartbeat/heartbeat.py` não estão no `pwd`.

## Anti-patterns

Coisas que esta skill NUNCA faz:
- Modificar qualquer arquivo nos 6 vaults dos repos NPU (mesmo check 8 é read-only).
- Sobrescrever notas do vault local automaticamente.
- Forçar criação de ADR (heurística do check 5 é warning, não bloqueio).
- Carregar `.knowledge-sync.yml` (não tem aqui, por design).
- Integrar com `knowledge-sync-all` ou cross-repo sync.

## Checks na ordem

(seções a serem preenchidas nas próximas tasks)
