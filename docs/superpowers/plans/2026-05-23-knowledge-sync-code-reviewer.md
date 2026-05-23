# `knowledge-sync-code-reviewer` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Criar uma skill local em `.claude/skills/knowledge-sync-code-reviewer/` que valide drift código↔vault deste repo e opcionalmente verifique a estrutura dos vaults dos 6 repos NPU sem se acoplar ao mesh NPU-Brain.

**Architecture:** Skill markdown carregada pelo Claude Code via `Skill` tool. Cwd-aware: precisa rodar com cwd na raiz deste repo. Sem dependências externas além de bash/grep/find/git. Validação read-only (não modifica nada nos 6 hinc).

**Tech Stack:** Markdown (SKILL.md), bash, plain text (targets.txt). Sem Python, sem deps externas.

**Spec de referência:** `docs/superpowers/specs/2026-05-23-knowledge-sync-code-reviewer-design.md`

---

## File Structure

| Arquivo | Responsabilidade | Tamanho estimado |
|---|---|---|
| `.claude/skills/knowledge-sync-code-reviewer/SKILL.md` | Definição da skill: 8 checks + formato de relatório + anti-patterns | ~180 linhas |
| `.claude/skills/knowledge-sync-code-reviewer/targets.txt` | Lista dos 6 repos NPU monitorados (uma linha por repo) | ~12 linhas |
| `Claude/runbook-knowledge-sync-code-reviewer.md` | Documentação no vault: quando usar, exemplos de output, troubleshooting | ~80 linhas |
| `Claude/_MOC Operacao.md` (modificação) | Adicionar link pro novo runbook | +2 linhas |
| `CLAUDE.md` raiz (modificação) | Mencionar a skill na seção Comandos | +3 linhas |

**Decomposição justificativa:**
- `SKILL.md` é o coração. Mantido em 1 arquivo (não dividido por check) porque skills do Claude Code são lidas inteiras no carregamento — fragmentar prejudica clareza.
- `targets.txt` separado de `SKILL.md` permite editar a lista sem mexer na lógica da skill.
- `runbook-knowledge-sync-code-reviewer.md` no vault porque a skill é parte do conhecimento operacional do repo.

---

## Task 1: Criar `targets.txt`

**Files:**
- Create: `.claude/skills/knowledge-sync-code-reviewer/targets.txt`

- [ ] **Step 1: Criar diretório da skill**

```bash
mkdir -p .claude/skills/knowledge-sync-code-reviewer
ls -la .claude/skills/
```

Expected: diretório `knowledge-sync-code-reviewer/` listado.

- [ ] **Step 2: Criar `targets.txt` com os 6 repos NPU**

Conteúdo exato:
```
# Lista de repos NPU monitorados pelo check 8 (--check-targets).
# Path implícito: $HOME/code/<nome>/Claude/
# Linhas começando com # ou vazias são ignoradas.
# Para adicionar/remover repos: editar este arquivo, sem reload necessário.

hinc-backend
hinc-onepage
hinc-pda-frontend
hinc-dashboards
hinc-dashboards-backend
hinc-etl
```

- [ ] **Step 3: Verificar parsing**

```bash
grep -v '^#' .claude/skills/knowledge-sync-code-reviewer/targets.txt | grep -v '^$' | wc -l
```

Expected: `6`

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/knowledge-sync-code-reviewer/targets.txt
git commit -m "feat(skill): adicionar targets.txt com 6 repos NPU monitorados"
```

---

## Task 2: Criar SKILL.md com frontmatter e estrutura básica

**Files:**
- Create: `.claude/skills/knowledge-sync-code-reviewer/SKILL.md`

- [ ] **Step 1: Criar SKILL.md com frontmatter e seções vazias**

Conteúdo exato:
```markdown
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
```

- [ ] **Step 2: Verificar frontmatter válido**

```bash
head -5 .claude/skills/knowledge-sync-code-reviewer/SKILL.md
```

Expected: primeira linha `---`, seguida de `name:`, `description:`, e `---` na linha 4.

- [ ] **Step 3: Verificar que Claude Code reconhece a skill**

Manual check: rodar no Claude Code (cwd = raiz deste repo):
```
/knowledge-sync-code-reviewer
```

Expected: skill é localizada (carregamento da skill, mesmo sem conteúdo de checks ainda). Se não encontra, verificar path de `.claude/skills/`.

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/knowledge-sync-code-reviewer/SKILL.md
git commit -m "feat(skill): scaffold knowledge-sync-code-reviewer SKILL.md"
```

---

## Task 3: Implementar checks 1-3 (diff, line numbers, cobertura)

**Files:**
- Modify: `.claude/skills/knowledge-sync-code-reviewer/SKILL.md` (substituir linha "(seções a serem preenchidas...)" pelos checks)

- [ ] **Step 1: Adicionar Check 1 — Diagnóstico do diff**

Substituir `(seções a serem preenchidas nas próximas tasks)` por:

````markdown
### Check 1 — Diagnóstico do diff

Lista o que mudou desde os últimos 10 commits nos arquivos que vault precisa acompanhar.

```bash
git diff --stat HEAD~10..HEAD -- heartbeat/ commands/ install.sh .env.example .obsidian/ 2>/dev/null
```

Decisão de modo:
- **Zero mudanças** → reportar `MODE: validação rápida (sem mudanças recentes em código)` e pular checks 4 e 5.
- **>0 mudanças** → reportar `MODE: validação completa` e seguir todos os checks.

Output reportado:
```
### Diff desde último sync
- N arquivos mudados, M LOC adicionadas
- <arquivo1> (+X LOC)
- <arquivo2> (+Y LOC)
```

### Check 2 — Line numbers de `heartbeat.py`

Extrai linhas de cada função e compara com tabela em `Claude/arquitetura.md` (§"Componentes (na ordem do fluxo)") e `Claude/modulo-heartbeat.md` (§"Layout do arquivo").

```bash
# Extrair função → linha
grep -n "^def " heartbeat/heartbeat.py | awk -F: '{print $2": "$1}'
```

Comparar manualmente com a tabela em `Claude/arquitetura.md`. Pra cada função:
- Se linha bate → ✅
- Se difere → ⚠️ "função X listada em linha Y na nota, mas está em linha Z no código"

Não corrigir automaticamente — humano decide se o drift é trivial ou crítico.

Output:
```
### Line numbers (heartbeat.py)
- ✅ Todas as N funções batem com Claude/arquitetura.md
ou
- ⚠️ Claude/<nota>.md cita <funcao> em linha X mas está em Y (drift de N linhas)
```

### Check 3 — Cobertura "Regras e Invariantes"

T1 substantivas (não-MOC) e T2 grandes (>200 linhas) devem ter seção `## Regras e Invariantes`. MOCs intencionalmente fora (meta-navegação).

```bash
# T1 substantivas (excluir MOCs)
total_t1_sub=0; t1_sub_ok=0
for f in $(grep -rl "^tier: 1" Claude/ --include="*.md" 2>/dev/null); do
  bn=$(basename "$f" .md)
  [[ "$bn" == _MOC* ]] && continue
  total_t1_sub=$((total_t1_sub + 1))
  has=$(grep -c "^## Regras e Invariantes" "$f")
  [ "$has" -gt 0 ] && t1_sub_ok=$((t1_sub_ok + 1))
done
echo "T1 substantivas: $t1_sub_ok / $total_t1_sub"

# T2 grandes (>200 linhas)
total_t2_big=0; t2_big_ok=0
for f in $(grep -rl "^tier: 2" Claude/ --include="*.md" 2>/dev/null); do
  lines=$(wc -l < "$f")
  if [ "$lines" -gt 200 ]; then
    total_t2_big=$((total_t2_big + 1))
    has=$(grep -c "^## Regras e Invariantes" "$f")
    [ "$has" -gt 0 ] && t2_big_ok=$((t2_big_ok + 1))
  fi
done
echo "T2 grandes (>200 linhas): $t2_big_ok / $total_t2_big"
```

Output:
```
### Cobertura "Regras e Invariantes"
- T1 substantivas: X/Y ✅ (meta: 100%)
- T2 grandes (>200): X/Y ✅ (meta: 100%)
- MOCs: 0/N (intencional — meta-navegação)
```

Se cobertura <100%, listar notas faltantes:
```
FALTA:
- <nome-da-nota>
```
````

- [ ] **Step 2: Verificar parsing**

```bash
grep -c "^### Check" .claude/skills/knowledge-sync-code-reviewer/SKILL.md
```

Expected: `3`

- [ ] **Step 3: Smoke test manual (interativo)**

Manual check no Claude Code:
```
/knowledge-sync-code-reviewer
```

Expected: skill roda checks 1-3, produz output com:
- Diff stats
- Line numbers da heartbeat.py
- Cobertura: T1 substantivas 6/6, T2 grandes 4/4

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/knowledge-sync-code-reviewer/SKILL.md
git commit -m "feat(skill): implementar checks 1-3 (diff, line numbers, cobertura)"
```

---

## Task 4: Implementar checks 4-7 (sync matrix, ADRs pendentes, validação básica, áreas universais)

**Files:**
- Modify: `.claude/skills/knowledge-sync-code-reviewer/SKILL.md` (adicionar checks 4-7 após o check 3)

- [ ] **Step 1: Adicionar Check 4 — Sync matrix**

Adicionar após o final do Check 3:

````markdown
### Check 4 — Sync matrix (mudança óbvia)

Verifica se mudanças em código foram acompanhadas de mudanças nas notas correspondentes. **Pular este check se Check 1 reportou MODE: validação rápida.**

Matriz de relações:

| Arquivo de código mudou | Nota(s) que deveria atualizar |
|---|---|
| `heartbeat/heartbeat.py` | `Claude/modulo-heartbeat.md` ∧ `Claude/arquitetura.md` |
| `commands/code-review.md` | `Claude/regras-prompt-review.md` |
| `install.sh` | `Claude/deploy.md` ∧ `Claude/ADR-003-symlinks-no-install.md` |
| SCHEMA SQL (string const em `heartbeat.py`) | `Claude/arquitetura-banco.md` |
| `.env.example` | `Claude/env-setup.md` |

```bash
# Arquivos de código e vault no diff dos últimos 10 commits
code_changed=$(git diff --name-only HEAD~10..HEAD 2>/dev/null | grep -E '^(heartbeat/|commands/|install\.sh|\.env\.example)')
vault_changed=$(git diff --name-only HEAD~10..HEAD 2>/dev/null | grep -E '^Claude/')

echo "Código mudou: $code_changed"
echo "Vault mudou: $vault_changed"
```

Pra cada arquivo de código no diff, verificar se a(s) nota(s) esperada(s) também está(ão) no diff. Se não → flag `⚠️ vault drift suspeito`.

Output:
```
### Sync matrix
| Código mudou | Nota atualizada? |
|---|---|
| heartbeat/heartbeat.py | modulo-heartbeat.md ✅  arquitetura.md ❌ |
| commands/code-review.md | regras-prompt-review.md ✅ |
```

### Check 5 — ADRs pendentes (heurística)

Detecta mudanças estruturais sem nova ADR. **Pular este check se Check 1 reportou MODE: validação rápida.**

Heurística:
- `heartbeat.py` mudou >50 LOC nos últimos 10 commits SEM novo `Claude/ADR-*.md` no diff
- OU `commands/code-review.md` mudou >30 LOC SEM novo `Claude/ADR-*.md` no diff

```bash
heartbeat_loc=$(git diff --stat HEAD~10..HEAD -- heartbeat/heartbeat.py 2>/dev/null | tail -1 | grep -oP '\d+(?= insertion)' || echo 0)
prompt_loc=$(git diff --stat HEAD~10..HEAD -- commands/code-review.md 2>/dev/null | tail -1 | grep -oP '\d+(?= insertion)' || echo 0)
new_adrs=$(git diff --name-only --diff-filter=A HEAD~10..HEAD 2>/dev/null | grep -c '^Claude/ADR-')

echo "heartbeat.py LOC: $heartbeat_loc | code-review.md LOC: $prompt_loc | novos ADRs: $new_adrs"
```

Se `heartbeat_loc > 50` E `new_adrs == 0` → flag `⚠️ heartbeat.py mudou N LOC sem novo ADR — verificar se há decisão estrutural`.

Falsos positivos esperados (refactor sem mudança de decisão). Humano filtra.

Output:
```
### ADRs pendentes
- ✅ Mudanças cabíveis em ADRs existentes
ou
- ⚠️ heartbeat.py mudou N LOC sem novo ADR — verificar
```

### Check 6 — Validação básica

Sempre roda, independente do modo.

```bash
# Total notas substantivas + templates
total_notas=$(find Claude/ -name '*.md' -not -path '*/_templates/*' -type f | wc -l)
total_templates=$(find Claude/_templates/ -name '*.md' -type f 2>/dev/null | wc -l)

# Total links
total_links=$(grep -ro '\[\[' Claude/ --include='*.md' | wc -l)

# Ilhas (zero outbound links, excluir templates)
ilhas=$(find Claude/ -name "*.md" -not -path "*/_templates/*" -type f -print0 | while IFS= read -r -d '' f; do
  out=$(grep -co '\[\[' "$f" 2>/dev/null)
  if [ "${out:-0}" -eq 0 ]; then echo "$f"; fi
done | wc -l)

# Sem frontmatter
sem_fm=$(find Claude/ -name "*.md" -type f -print0 | while IFS= read -r -d '' f; do
  has_fm=$(head -1 "$f" | grep -c "^---$")
  if [ "$has_fm" -eq 0 ]; then echo "$f"; fi
done | wc -l)

# Broken links (com path resolution correto, ignora placeholders intencionais)
broken=$(for f in Claude/*.md Claude/_templates/*.md; do
  grep -oE '\[\[[^]|#]+' "$f" 2>/dev/null | sed 's/\[\[//' | sort -u | while read link; do
    [ -z "$link" ] && continue
    [ "$link" = "outra-nota" ] && continue  # placeholder intencional no template
    target_root="Claude/${link}.md"
    target_tpl="Claude/_templates/$(basename ${link}).md"
    if [ ! -f "$target_root" ] && [ ! -f "$target_tpl" ] && [ ! -f "Claude/${link}" ]; then
      echo "BROKEN em $(basename $f): [[$link]]"
    fi
  done
done | sort -u | wc -l)

echo "Notas: $total_notas + $total_templates templates"
echo "Links: $total_links"
echo "Ilhas: $ilhas | Sem FM: $sem_fm | Broken: $broken"
```

Output:
```
### Validação básica
- N notas substantivas + M templates
- L wikilinks
- I ilhas, F sem frontmatter, B broken links (placeholders ignorados)
```

### Check 7 — Áreas universais

Validar que as 3 notas mínimas (fallback genérico) existem e têm boa rede inbound.

```bash
for area in regras-negocio glossario arquitetura; do
  count=$(ls Claude/${area}*.md 2>/dev/null | wc -l)
  links=$(grep -rl "\[\[${area}" Claude/ --include="*.md" 2>/dev/null | wc -l)
  if [ "$count" -eq 0 ]; then
    echo "❌ $area: NOTA FALTA"
  elif [ "$links" -lt 3 ]; then
    echo "⚠️ $area: $count nota(s), $links inbound (deveria ter ≥3)"
  else
    echo "✅ $area: $count nota(s), $links inbound"
  fi
done
```

Output:
```
### Áreas universais
- ✅ regras-negocio: 18 inbound
- ✅ glossario: 3 inbound
- ✅ arquitetura: 20 inbound
```
````

- [ ] **Step 2: Verificar parsing**

```bash
grep -c "^### Check" .claude/skills/knowledge-sync-code-reviewer/SKILL.md
```

Expected: `7`

- [ ] **Step 3: Smoke test manual**

No Claude Code:
```
/knowledge-sync-code-reviewer
```

Expected: skill agora roda checks 1-7, produz output completo. Sem mudanças recentes → MODE rápido (pula 4-5). Com mudanças → MODE completo.

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/knowledge-sync-code-reviewer/SKILL.md
git commit -m "feat(skill): implementar checks 4-7 (sync matrix, ADRs, validação, áreas universais)"
```

---

## Task 5: Implementar check 8 (--check-targets) e formato de relatório

**Files:**
- Modify: `.claude/skills/knowledge-sync-code-reviewer/SKILL.md` (adicionar Check 8 + seção de relatório no fim)

- [ ] **Step 1: Adicionar Check 8 — Targets check (opt-in)**

Adicionar após Check 7:

````markdown
### Check 8 — Targets check (opt-in, `--check-targets`)

**Só roda se a invocação foi com flag `--check-targets`.** Verifica que os vaults dos repos NPU listados em `targets.txt` têm a estrutura esperada pelo `commands/code-review.md` (via ADR-006).

**Read-only: nenhuma modificação nos 6 vaults.**

```bash
TARGETS_FILE=".claude/skills/knowledge-sync-code-reviewer/targets.txt"
[ ! -f "$TARGETS_FILE" ] && echo "❌ targets.txt não encontrado" && exit 1

while IFS= read -r repo; do
  # Pular comentários e linhas vazias
  [[ "$repo" =~ ^[[:space:]]*# ]] && continue
  [ -z "$(echo "$repo" | tr -d '[:space:]')" ] && continue

  vault_path="$HOME/code/$repo/Claude"

  if [ ! -d "$vault_path" ]; then
    printf "  ❌ %-30s vault ausente em %s\n" "$repo" "$vault_path"
    continue
  fi

  has_regras="❌"
  [ -f "$vault_path/regras-negocio.md" ] && has_regras="✓"

  has_bugs="❌"
  [ -f "$vault_path/bugs-conhecidos.md" ] && has_bugs="✓"

  adr_count=$(ls "$vault_path"/ADR-*.md 2>/dev/null | wc -l)

  # Status: ✅ se ambos OK, ⚠️ se 1 falta, ❌ se vault ausente (já tratado acima)
  if [ "$has_regras" = "✓" ] && [ "$has_bugs" = "✓" ]; then
    status="✅"
  else
    status="⚠️"
  fi

  printf "  %s %-30s regras-negocio.md %s  bugs-conhecidos.md %s  ADRs: %d\n" \
    "$status" "$repo" "$has_regras" "$has_bugs" "$adr_count"
done < "$TARGETS_FILE"
```

Output:
```
### Targets check (--check-targets)
  ✅ hinc-backend                regras-negocio.md ✓  bugs-conhecidos.md ✓  ADRs: 5
  ✅ hinc-onepage                regras-negocio.md ✓  bugs-conhecidos.md ✓  ADRs: 6
  ⚠️  hinc-dashboards            regras-negocio.md ✓  bugs-conhecidos.md ❌  ADRs: 8
  ✅ hinc-etl                    regras-negocio.md ✓  bugs-conhecidos.md ✓  ADRs: 0
  ⚠️  hinc-pda-frontend          regras-negocio.md ❌  bugs-conhecidos.md ✓  ADRs: 4
  ✅ hinc-dashboards-backend     regras-negocio.md ✓  bugs-conhecidos.md ✓  ADRs: 3
```

Status `⚠️` significa: o reviewer (`commands/code-review.md`) espera ler esse arquivo mas ele não existe. Pode ser gap legítimo (repo simples não tem bugs documentados) ou drift (renomeou/removeu). Humano decide.

## Formato do relatório final

Gerar relatório completo em markdown, salvar opcionalmente em `~/.claude/heartbeat/logs/knowledge-sync-cr-YYYY-MM-DD-HHMM.log` (criar diretório se não existir):

```markdown
## Knowledge Sync Code-Reviewer Report — YYYY-MM-DD HH:MM

### Modo
{validação rápida | validação completa | validação completa + targets}

[seções dos checks 1-7, mais 8 se --check-targets]

### Gaps acionáveis
- [ ] <gap 1 derivado dos checks acima>
- [ ] <gap 2>
...
```

Imprimir no stdout sempre. Salvar em arquivo opcional (se diretório `~/.claude/heartbeat/logs/` existe).
````

- [ ] **Step 2: Verificar parsing**

```bash
grep -c "^### Check" .claude/skills/knowledge-sync-code-reviewer/SKILL.md
```

Expected: `8`

- [ ] **Step 3: Smoke test manual com flag**

No Claude Code:
```
/knowledge-sync-code-reviewer --check-targets
```

Expected: skill roda checks 1-8, mostra a tabela dos 6 hinc com status real.

- [ ] **Step 4: Smoke test manual sem flag (regressão)**

```
/knowledge-sync-code-reviewer
```

Expected: checks 1-7 apenas, sem mencionar targets.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/knowledge-sync-code-reviewer/SKILL.md
git commit -m "feat(skill): implementar check 8 (--check-targets) e formato de relatório"
```

---

## Task 6: Criar runbook no vault local

**Files:**
- Create: `Claude/runbook-knowledge-sync-code-reviewer.md`

- [ ] **Step 1: Criar runbook**

Conteúdo exato:
```markdown
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

Detalhamento em `.claude/skills/knowledge-sync-code-reviewer/SKILL.md`. Resumo:

1. **Diagnóstico do diff** — decide MODE (rápido vs completo) baseado em mudanças recentes.
2. **Line numbers** — funções em `heartbeat.py` batem com tabela em `arquitetura.md` e `modulo-heartbeat.md`?
3. **Cobertura "Regras e Invariantes"** — T1 substantivas (6) + T2 grandes (4) cobertas. MOCs intencionalmente fora.
4. **Sync matrix** — mudança em código foi acompanhada de mudança na nota correspondente?
5. **ADRs pendentes** — mudança estrutural (>50 LOC em heartbeat, >30 em prompt) sem novo ADR?
6. **Validação básica** — contagem, ilhas, frontmatter, broken links.
7. **Áreas universais** — `regras-negocio`, `glossario`, `arquitetura` existem com ≥3 inbound cada.
8. **Targets check** (opt-in) — vaults dos 6 NPU têm os arquivos que `code-review.md` espera ler?

## Output esperado (estado limpo)

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
```

- [ ] **Step 2: Validar frontmatter**

```bash
head -15 Claude/runbook-knowledge-sync-code-reviewer.md
```

Expected: frontmatter completo com `tier: 3`, `type: runbook`.

- [ ] **Step 3: Commit**

```bash
git add Claude/runbook-knowledge-sync-code-reviewer.md
git commit -m "docs(vault): runbook da skill knowledge-sync-code-reviewer"
```

---

## Task 7: Atualizar `_MOC Operacao.md` e `CLAUDE.md` raiz

**Files:**
- Modify: `Claude/_MOC Operacao.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Adicionar link no MOC Operacao**

Em `Claude/_MOC Operacao.md`, na seção "Manutenção rotineira", adicionar bullet:

Localizar:
```markdown
## Manutenção rotineira

- [[runbook-rotacionar-state-db]] — backup + cleanup do `state.db`.
- [[runbook-atualizar-prompt]] — fluxo seguro pra mudar `code-review.md`.
```

Substituir por:
```markdown
## Manutenção rotineira

- [[runbook-rotacionar-state-db]] — backup + cleanup do `state.db`.
- [[runbook-atualizar-prompt]] — fluxo seguro pra mudar `code-review.md`.
- [[runbook-knowledge-sync-code-reviewer]] — validar drift entre código e vault (skill local).
```

- [ ] **Step 2: Adicionar menção no CLAUDE.md raiz**

Em `CLAUDE.md` raiz, na seção "Comandos", após a seção atual de commands bash, adicionar:

Localizar:
```markdown
# Update (symlinks → git pull propaga)
git pull
```

Adicionar abaixo:
```markdown

# Validar drift entre código e vault (skill local)
# /knowledge-sync-code-reviewer            (checks 1-7 — vault local apenas)
# /knowledge-sync-code-reviewer --check-targets  (adiciona check 8 — read-only nos 6 NPU)
```

- [ ] **Step 3: Verificar mudanças**

```bash
git diff Claude/_MOC\ Operacao.md CLAUDE.md
```

Expected: 2 arquivos modificados, mudanças cirúrgicas (1 bullet + 4 linhas de comentário).

- [ ] **Step 4: Commit**

```bash
git add Claude/_MOC\ Operacao.md CLAUDE.md
git commit -m "docs: linkar runbook da skill no MOC Operacao + CLAUDE.md raiz"
```

---

## Task 8: Smoke test final end-to-end

**Files:** (nenhum modificado)

- [ ] **Step 1: Validar estado do repo antes do smoke**

```bash
git status
ls .claude/skills/knowledge-sync-code-reviewer/
ls Claude/runbook-knowledge-sync-code-reviewer.md
```

Expected:
- Working tree clean (ou só untracked do .obsidian, se ainda não commitamos).
- `SKILL.md` e `targets.txt` no diretório da skill.
- Runbook existe no vault.

- [ ] **Step 2: Rodar skill sem flag**

Manual no Claude Code (cwd = raiz deste repo):
```
/knowledge-sync-code-reviewer
```

Expected:
- Modo: validação rápida ou completa (depende do diff recente).
- Check 1: diff stats.
- Check 2: line numbers ✅.
- Check 3: T1 6/6, T2 4/4 ✅.
- Check 6: 29 notas, 344+ links, 0 ilhas, 0 sem FM, 0 broken.
- Check 7: regras-negocio/glossario/arquitetura ✅.
- Gaps acionáveis: idealmente vazio.

- [ ] **Step 3: Rodar skill com `--check-targets`**

```
/knowledge-sync-code-reviewer --check-targets
```

Expected:
- Tudo do Step 2 +
- Tabela dos 6 hinc com status real (✅/⚠️ por repo).

- [ ] **Step 4: Validar que skill não modificou nada**

```bash
git status
```

Expected: working tree no mesmo estado do Step 1 (skill é read-only).

- [ ] **Step 5: Documentar resultado em comentário no plano**

Editar este arquivo, adicionar seção no fim:

```markdown
## Smoke test result (preenchido após Task 8)

- Data: YYYY-MM-DD HH:MM
- Modo do step 2: [rápida|completa]
- Gaps no step 2: [contagem ou "nenhum"]
- Status dos 6 hinc no step 3:
  - hinc-backend: ✅
  - hinc-onepage: ✅
  - ...
- Issues encontrados: [lista ou "nenhum"]
- Próxima ação: [implementar fixes / pronto pra usar]
```

- [ ] **Step 6: Commit final**

```bash
git add docs/superpowers/plans/2026-05-23-knowledge-sync-code-reviewer.md
git commit -m "test(skill): smoke test end-to-end da knowledge-sync-code-reviewer"
```

---

## Critérios de aceitação (do spec §8)

- [x] `.claude/skills/knowledge-sync-code-reviewer/SKILL.md` existe e tem 8 checks (Tasks 2-5).
- [x] `.claude/skills/knowledge-sync-code-reviewer/targets.txt` existe com 6 repos NPU (Task 1).
- [x] `/knowledge-sync-code-reviewer` produz relatório dos checks 1-7 (Task 8 step 2).
- [x] `/knowledge-sync-code-reviewer --check-targets` adiciona check 8 (Task 8 step 3).
- [x] Vault tem nota documentando a skill (Task 6).
- [x] `CLAUDE.md` raiz menciona a skill (Task 7).

---

## Self-review

**Spec coverage:**
- §1-2 contexto/objetivos → não viram task (são docs).
- §3 escopo → coberto implicitamente nos checks.
- §4 localização/invocação → Tasks 1-2.
- §5 8 checks → Tasks 1, 3, 4, 5.
- §6 output → Task 5.
- §7 implementação → estrutura mapeada acima.
- §8 critérios → seção dedicada ao final.
- §9 smoke test → Task 8.
- §10 trabalho relacionado → fora de escopo (vault-review é próximo brainstorming).
- §11 riscos → não viram task (são notas de awareness).

✅ Toda seção do spec tem cobertura (ou justificativa de não-cobertura).

**Placeholder scan:** nenhum TBD/TODO encontrado.

**Type consistency:** flag `--check-targets` usada consistentemente em todas as tasks (não há `--check-target` ou `--targets-check`). Nomes de arquivos (`SKILL.md`, `targets.txt`) idênticos em todas referências.
