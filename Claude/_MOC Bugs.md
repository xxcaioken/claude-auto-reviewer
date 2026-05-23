---
title: _MOC — Bugs e tech debt
type: moc
status: active
tags:
  - moc
  - bug
  - debt/alta
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[_MOC Onboarding]]"
  - "[[_MOC Auto-Reviewer]]"
  - "[[_MOC Operacao]]"
  - "[[_MOC ADRs]]"
tier: 1
---

# _MOC — Bugs e tech debt

Mapa por **dívida**. Categorizado por severidade e tipo.

## Notas guarda-chuva

- [[bugs-conhecidos]] — bugs e limitações com fix proposto.
- [[tech-debt]] — débitos não-fix (features ausentes, falta de teste, etc.).
- [[error-handling]] — fluxos de erro mapeados (não são bugs, são contratos).

## Por severidade

### 🔴 Alta

| ID | Item | Onde |
|---|---|---|
| TD-001 | Zero testes automatizados | [[tech-debt]] §TD-001 |
| TD-002 | Sem retry em falha transitória de `gh` | [[tech-debt]] §TD-002 |

### 🟡 Média

| ID | Item | Onde |
|---|---|---|
| B-001 | Symlink quebra se repo é movido | [[bugs-conhecidos]] §B-001 |
| B-002 | Mudar `MARKER` invisibiliza histórico | [[bugs-conhecidos]] §B-002 |
| B-003 | Revisão parcial não tem flag estruturada | [[bugs-conhecidos]] §B-003 |
| TD-003 | `--edit-last` (vs novo comentário a cada push) | [[tech-debt]] §TD-003 |
| TD-004 | Falta backup automático do `state.db` | [[tech-debt]] §TD-004 |
| TD-005 | `repos.txt` sem validação ou hot-reload | [[tech-debt]] §TD-005 |

### 🟢 Baixa

| ID | Item | Onde |
|---|---|---|
| B-004 | `claude --help` desnecessário no `install.sh` | [[bugs-conhecidos]] §B-004 |
| B-005 | `gh auth status` não valida scopes | [[bugs-conhecidos]] §B-005 |
| TD-006 | Paralelismo entre PRs | [[tech-debt]] §TD-006 |
| TD-007 | TTL pra revisões antigas | [[tech-debt]] §TD-007 |
| TD-008 | Métricas operacionais | [[tech-debt]] §TD-008 |

## Por tipo de problema

### Auditoria / observabilidade
- TD-001 (testes), TD-008 (métricas), B-003 (revisão parcial sem flag).

### Resiliência / retry
- TD-002 (retry de `gh`), B-001 (symlink quebrado), B-005 (scopes).

### Custos / escala
- TD-006 (paralelismo), TD-007 (TTL).

### UX / fluxo
- TD-003 (`--edit-last`), TD-005 (validação `repos.txt`), B-002 (MARKER), B-004 (cosmético).

### Backup / recovery
- TD-004 (backup automático).

## Post-mortems

Pasta `post-mortems/` está vazia. Quando houver incidente, criar usando [[_templates/post-mortem]].

## Limitações de design (não são bugs)

Documentadas em [[bugs-conhecidos]] §"Limitações de design":
- Sem Windows (depende de `fcntl`).
- 1 PR por vez (lock global).
- Latência mínima 5 min entre push e revisão (intervalo do cron).
- Sem `--edit-last` (cada push gera comentário novo).
- Sem retry programático (próximo tick reprocessa).

Estas são consequências aceitas das decisões em [[_MOC ADRs]].

## Navegação por MOC

- [[_MOC Onboarding]] — caminho de entrada no projeto.
- [[_MOC Auto-Reviewer]] — visão técnica do sistema.
- [[_MOC Operacao]] — runbooks e operação dia-a-dia.
- [[_MOC ADRs]] — decisões arquiteturais.
