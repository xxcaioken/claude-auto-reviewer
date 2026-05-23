---
title: Runbook — rodar tick manual (teste local)
type: runbook
status: active
tags:
  - runbook
  - backend
  - onboarding
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[env-setup]]"
  - "[[runbook-debugar-revisao-falhada]]"
  - "[[runbook-atualizar-prompt]]"
tier: 3
---

# Runbook — rodar um tick manual pra testar

## Quando usar
- Validar setup após `install.sh`.
- Reproduzir bug.
- Testar mudança no prompt sem esperar 5 min do cron.
- Forçar revisão imediata após retry manual.

## Tick básico (sem mexer em nada)

```bash
python3 ~/.claude/heartbeat/heartbeat.py
```

Comportamento esperado:
1. Adquire lock (`heartbeat.lock`). Se outro tick está rodando, aborta com info.
2. Valida pré-requisitos (`claude`, `gh`, `gh auth status`, `repos.txt` existe).
3. Itera repos do `repos.txt`.
4. Pra cada PR não revisado, invoca o Claude.

Tempo: depende de quantos PRs novos. Tipicamente segundos (se ninguém pushou). Pode demorar horas em lote inicial.

## Tick com env vars customizadas

```bash
CLAUDE_TIMEOUT=120 GH_TIMEOUT=10 python3 ~/.claude/heartbeat/heartbeat.py
```

Útil pra testar timeouts curtos sem afetar a config do cron.

## Tick observando logs em tempo real

Em outro terminal:
```bash
tail -f ~/.claude/heartbeat/logs/heartbeat.log
```

Disparar no primeiro:
```bash
python3 ~/.claude/heartbeat/heartbeat.py
```

Log mostra cada repo + cada PR processado.

## Forçar revisão de um PR específico

Cenário: você quer rodar a revisão num PR específico, ignorando o cron.

### Opção A — via heartbeat com filtro temporário

`heartbeat.py` hoje não aceita `--repo` ou `--pr` (poderia ser feature futura). Workaround: editar `repos.txt` temporariamente pra ter só o repo de interesse.

```bash
cp ~/.claude/heartbeat/repos.txt ~/.claude/heartbeat/repos.txt.bak
echo "test-repo|/tmp|<owner>/<repo>|1" > ~/.claude/heartbeat/repos.txt

# Garantir que a linha pro head_sha não existe (forçar revisão)
HEAD_SHA=$(gh pr view <num> --repo <owner>/<repo> --json headRefOid -q .headRefOid)
sqlite3 ~/.claude/heartbeat/state.db \
  "DELETE FROM code_reviews WHERE repo='test-repo' AND pr_number=<num> AND head_sha='$HEAD_SHA';"

# Rodar
python3 ~/.claude/heartbeat/heartbeat.py

# Restaurar
mv ~/.claude/heartbeat/repos.txt.bak ~/.claude/heartbeat/repos.txt
```

### Opção B — invocar Claude direto, sem heartbeat

Pula a parte de detecção/persistência. Útil pra testar só o prompt.

```bash
cd ~  # CWD sem .claude/commands/code-review.md local
claude --permission-mode bypassPermissions -p "/code-review https://github.com/<owner>/<repo>/pull/<num> publique"
```

Comportamento: Claude lê o diff, gera o comentário, posta via `gh pr comment`. Sem registro no SQLite — depois fica como "publicação fantasma" se rodar o heartbeat (que vê o comment mas considera revisão completa só após detectar via snapshot, e nesse caso o snapshot post estaria com comentário já presente antes → marcaria runned=0 falso). Recomendado: depois apagar o comentário OU adicionar manualmente uma linha no SQLite.

### Opção C — modo interativo (sem publicar)

```bash
cd ~
claude
> /code-review https://github.com/<owner>/<repo>/pull/<num>
```

(Sem `publique`.) Gera relatório no terminal, oferece via `AskUserQuestion` salvar/publicar/criar issues/só exibir.

Use pra **testar mudança no prompt** sem efeito colateral no PR.

## Bypassar `check_prerequisites` (teste de regression)

Se quer testar comportamento do código com `gh` ausente:

```bash
PATH="/usr/bin:/bin" GH_BIN=/nonexistent python3 ~/.claude/heartbeat/heartbeat.py
```

Deve logar `gh não encontrado em /nonexistent` e exit 1.

## Disparar com profiling

```bash
python3 -m cProfile -o /tmp/heartbeat.prof ~/.claude/heartbeat/heartbeat.py
python3 -m pstats /tmp/heartbeat.prof <<EOF
sort cumulative
stats 30
EOF
```

Útil se desconfia de tick lento. Hoje, dominantes seriam: `subprocess.run` (Claude), `subprocess.run` (gh), SQLite I/O.

## Smoke test pós-install completo

```bash
# 1. Pré-requisitos
which claude gh python3
gh auth status

# 2. Symlinks ok
ls -la ~/.claude/heartbeat/heartbeat.py ~/.claude/commands/code-review.md

# 3. repos.txt válido
cat ~/.claude/heartbeat/repos.txt | grep -v '^#' | grep -v '^$'

# 4. DB inicializado
sqlite3 ~/.claude/heartbeat/state.db ".tables"   # deve mostrar code_reviews + pr_state

# 5. Tick (1 a 2 min)
time python3 ~/.claude/heartbeat/heartbeat.py

# 6. Log sem ERROR
tail -20 ~/.claude/heartbeat/logs/heartbeat.log | grep -i error
```

Se 1-6 passam sem ERROR, instalação OK.

## Notas relacionadas
- [[env-setup]] — env vars disponíveis.
- [[runbook-debugar-revisao-falhada]] — quando o teste mostra `runned=0`.
- [[runbook-atualizar-prompt]] — usar modo interativo (Opção C) pra validar prompt antes de mergear.
