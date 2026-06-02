---
title: Runbook — usar a skill knowledge-sync-code-reviewer
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
  - "[[_MOC Operacao]]"
  - "[[regras-prompt-review]]"
  - "[[ADR-006-leitura-vault-repo-alvo]]"
tier: 3
---

# Runbook — `/knowledge-sync-code-reviewer`

Skill local que valida drift entre código e vault deste repo. Independente do `/knowledge-sync` genérico do NPU-Brain.

## Quando usar

- Após qualquer mudança em `heartbeat/heartbeat.py`, `commands/code-review.md`, `install.sh`, `.env.example`, ou notas do `Claude/`.
- Antes de commitar mudanças significativas.
- Periodicamente, mesmo sem diff (validação preventiva).

## Pré-requisito

Cwd deve ser a raiz deste repo. Skill aborta se `Claude/` ou `heartbeat/heartbeat.py` não estão no `pwd`.

## Invocações

```
/knowledge-sync-code-reviewer
```
Roda checks 1-7 (validação local apenas).

```
/knowledge-sync-code-reviewer --check-targets
```
Adiciona check 8 (verifica estrutura dos 6 vaults NPU em `~/code/<repo>/Claude/`). Read-only.

## O que cada check faz

Detalhamento em `.claude/skills/knowledge-sync-code-reviewer/SKILL.md` (neste repo). Resumo:

1. **Diagnóstico do diff** — decide MODE (rápido vs completo) baseado em mudanças recentes.
2. **Line numbers** — funções em `heartbeat.py` batem com tabela em `arquitetura.md` e `modulo-heartbeat.md`?
3. **Cobertura "Regras e Invariantes"** — T1 substantivas (6) + T2 grandes (4) cobertas. MOCs intencionalmente fora.
4. **Sync matrix** — mudança em código foi acompanhada de mudança na nota correspondente?
5. **ADRs pendentes** — mudança estrutural (>50 LOC em heartbeat, >30 em prompt) sem novo ADR?
6. **Validação básica** — contagem, ilhas, frontmatter, broken links.
7. **Áreas universais** — `regras-negocio`, `glossario`, `arquitetura` existem com ≥3 inbound cada.
8. **Targets check** (opt-in) — vaults dos 6 NPU têm os arquivos que `code-review.md` espera ler?

## Output esperado (estado limpo)

> **Nota:** valores abaixo são snapshot de 2026-05-23. Contagens reais variam à medida que o vault evolui — confiar no output da skill, não nestes números.

```
## Knowledge Sync Code-Reviewer Report — 2026-05-23 17:42

### Modo
validação rápida (sem mudanças recentes em código)

### Diff desde último sync
- 0 arquivos mudados

### Line numbers (heartbeat.py)
- ✅ Todas as 13 funções batem

### Cobertura "Regras e Invariantes"
- T1 substantivas: 6/6 ✅
- T2 grandes (>200): 4/4 ✅
- MOCs: 0/5 (intencional)

### Validação básica
- 29 notas + 5 templates
- 344 wikilinks
- 0 ilhas, 0 sem FM, 0 broken (placeholders ignorados)

### Áreas universais
- ✅ regras-negocio: 18 inbound
- ✅ glossario: 3 inbound
- ✅ arquitetura: 20 inbound

### Gaps acionáveis
(nenhum)
```

## Troubleshooting

| Sintoma | Causa provável | Fix |
|---|---|---|
| "vault ausente" no check 8 | Repo em `targets.txt` não está em `~/code/` | Editar `targets.txt` ou clonar o repo |
| Check 2 reporta drift de N linhas | Editou `heartbeat.py` sem atualizar nota | Atualizar `arquitetura.md` ou `modulo-heartbeat.md` |
| Check 4 flag "vault drift suspeito" | Mudou código sem atualizar nota correspondente | Atualizar nota da matriz, OU justificar (ex: refactor sem mudança semântica) |
| Check 5 ⚠️ "sem novo ADR" | Mudança grande sem ADR | Criar ADR se realmente é decisão estrutural; ignorar se é refactor puro |

## Limites conhecidos

- Skill é manual (sem hook `Stop` automático).
- Heurísticas (>50 LOC, >30 LOC) podem gerar falsos positivos.
- Check 8 é read-only — não corrige drift nos 6 vaults NPU.

## Notas relacionadas
- [[ADR-006-leitura-vault-repo-alvo]] — feature que esta skill protege.
- [[regras-prompt-review]] — análise do `code-review.md` que esta skill ajuda a manter coerente.
- [[_MOC Operacao]] — outros runbooks operacionais.
