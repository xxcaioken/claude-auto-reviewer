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

### Check 1 — Diagnóstico do diff

Lista o que mudou desde os últimos 10 commits nos arquivos que vault precisa acompanhar.

```bash
# Determinar base — repo jovem pode não ter HEAD~10
BASE=$(git rev-list --max-count=10 HEAD | tail -1)
git diff --stat "$BASE..HEAD" -- heartbeat/ commands/ install.sh .env.example .obsidian/
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
# Usar while + process substitution pra suportar filenames com espaços
total_t1_sub=0
t1_sub_ok=0
while IFS= read -r f; do
  bn=$(basename "$f" .md)
  case "$bn" in _MOC*) continue;; esac
  total_t1_sub=$((total_t1_sub + 1))
  has=$(grep -c "^## Regras e Invariantes" "$f")
  [ "$has" -gt 0 ] && t1_sub_ok=$((t1_sub_ok + 1))
done < <(grep -rl "^tier: 1" Claude/ --include="*.md" 2>/dev/null)
echo "T1 substantivas: $t1_sub_ok / $total_t1_sub"

# T2 grandes (>200 linhas)
total_t2_big=0
t2_big_ok=0
while IFS= read -r f; do
  lines=$(wc -l < "$f")
  if [ "$lines" -gt 200 ]; then
    total_t2_big=$((total_t2_big + 1))
    has=$(grep -c "^## Regras e Invariantes" "$f")
    [ "$has" -gt 0 ] && t2_big_ok=$((t2_big_ok + 1))
  fi
done < <(grep -rl "^tier: 2" Claude/ --include="*.md" 2>/dev/null)
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
# Determinar base — repo jovem pode não ter HEAD~10
BASE=$(git rev-list --max-count=10 HEAD | tail -1)

# Arquivos de código e vault no diff
code_changed=$(git diff --name-only "$BASE..HEAD" | grep -E '^(heartbeat/|commands/|install\.sh|\.env\.example)')
vault_changed=$(git diff --name-only "$BASE..HEAD" | grep -E '^Claude/')

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
- `heartbeat.py` mudou >50 LOC desde os últimos 10 commits SEM novo `Claude/ADR-*.md` no diff.
- OU `commands/code-review.md` mudou >30 LOC SEM novo `Claude/ADR-*.md` no diff.

```bash
BASE=$(git rev-list --max-count=10 HEAD | tail -1)

heartbeat_loc=$(git diff --stat "$BASE..HEAD" -- heartbeat/heartbeat.py | tail -1 | grep -oP '\d+(?= insertion)' || echo 0)
prompt_loc=$(git diff --stat "$BASE..HEAD" -- commands/code-review.md | tail -1 | grep -oP '\d+(?= insertion)' || echo 0)
new_adrs=$(git diff --name-only --diff-filter=A "$BASE..HEAD" | grep -c '^Claude/ADR-')

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
    [ "$link" = "outra-nota" ] && continue          # placeholder do template nota-livre
    [ "$link" = "Claude/regras-X" ] && continue     # placeholder de convenção (ADR-006)
    link="${link#Claude/}"                           # strip path prefix se presente
    target_root="Claude/${link}.md"
    target_tpl="Claude/_templates/$(basename ${link}).md"
    if [ ! -f "$target_root" ] && [ ! -f "$target_tpl" ] && [ ! -f "Claude/${link}" ]; then
      echo "BROKEN em $(basename "$f"): [[$link]]"
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
