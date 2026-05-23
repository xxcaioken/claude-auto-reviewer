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
