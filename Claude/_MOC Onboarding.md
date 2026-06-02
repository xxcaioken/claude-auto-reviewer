---
title: _MOC — Onboarding
type: moc
status: active
tags:
  - moc
  - onboarding
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[_MOC Auto-Reviewer]]"
  - "[[_MOC Operacao]]"
  - "[[_MOC Bugs]]"
  - "[[_MOC ADRs]]"
tier: 1
---

# _MOC — Onboarding

Landing page pra alguém entrando no projeto. **Leia nesta ordem.** Cada nota linka pras próximas — mas se preferir um caminho linear, este é o caminho.

## 1. O que é

O sistema em uma frase: **cron Python invoca o Claude CLI a cada 5 min pra revisar PRs abertos em N repos do GitHub.**

Para entender em ~10 min:
1. [[arquitetura]] — diagrama de fluxo + componentes principais.
2. [[glossario]] — termos específicos (heartbeat, tick, head_sha, marcador HTML, runned).

## 2. Como funciona

3. [[modulo-heartbeat]] — anatomia do `heartbeat.py` função por função.
4. [[arquitetura-banco]] — schema SQLite (2 tabelas) + invariantes.
5. [[regras-prompt-review]] — o que o prompt `code-review.md` faz e por quê.

## 3. As regras "não-óbvias"

6. [[regras-negocio]] — 10 regras que protegem invariantes operacionais (idempotência, marcador HTML, bypassPermissions, etc.). **Leitura obrigatória antes de mexer no código.**

## 4. Decisões e armadilhas

7. [[bugs-conhecidos]] — bugs/limitações ativas com severidade.
8. [[tech-debt]] — débitos por prioridade.
9. ADRs (decisões arquiteturais) — ver [[_MOC ADRs]].

## 5. Pra começar a operar

10. [[env-setup]] — vars de ambiente e validação pós-install.
11. [[deploy]] — bootstrap via `install.sh`, atualizações, datasette.
12. [[runbook-adicionar-repo]] — adicionar primeiro repo ao monitoramento.
13. [[runbook-testar-localmente]] — rodar tick manual pra validar.

## 6. Quando der ruim

14. [[error-handling]] — todos os erros possíveis e o que acontece.
15. [[runbook-debugar-revisao-falhada]] — investigar `runned=0`.

## 7. Pra mudar coisas

16. [[runbook-atualizar-prompt]] — fluxo pra mudar `commands/code-review.md`.
17. [[runbook-rotacionar-state-db]] — backup e cleanup.
18. [[infra-testes]] — estado dos testes (zero) e plano sugerido.

## Sequência mínima viável (TL;DR)

Se vai mexer **agora** com tempo curto:
- [[arquitetura]] (5 min) — pegar a forma geral.
- [[regras-negocio]] (5 min) — não quebrar coisas.
- [[runbook-debugar-revisao-falhada]] (skim) — saber onde olhar quando der ruim.

## Navegação por MOC

- [[_MOC Auto-Reviewer]] — visão técnica do sistema.
- [[_MOC Operacao]] — runbooks e operação dia-a-dia.
- [[_MOC Bugs]] — débitos e bugs conhecidos.
- [[_MOC ADRs]] — decisões arquiteturais.
