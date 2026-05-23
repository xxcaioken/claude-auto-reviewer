---
title: _MOC — Operação dia-a-dia
type: moc
status: active
tags:
  - moc
  - runbook
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[_MOC Onboarding]]"
  - "[[_MOC Auto-Reviewer]]"
  - "[[_MOC Bugs]]"
  - "[[_MOC ADRs]]"
tier: 1
---

# _MOC — Operação dia-a-dia

Mapa por **tarefa operacional**. Use quando algo precisa ser feito ou investigado.

## Setup e onboarding de repos

- [[deploy]] — `install.sh` na primeira vez.
- [[env-setup]] — vars de ambiente.
- [[runbook-adicionar-repo]] — adicionar repo novo ao monitoramento.
- [[runbook-testar-localmente]] — rodar tick manual sem cron.

## Manutenção rotineira

- [[runbook-rotacionar-state-db]] — backup + cleanup do `state.db`.
- [[runbook-atualizar-prompt]] — fluxo seguro pra mudar `code-review.md`.
- [[runbook-knowledge-sync-code-reviewer]] — validar drift entre código e vault (skill local).

## Debugging e incidentes

- [[runbook-debugar-revisao-falhada]] — investigar `runned=0`.
- [[error-handling]] — todos os modos de falha possíveis.
- [[bugs-conhecidos]] — limites conhecidos do sistema.

## Consultas comuns ao SQLite

Listadas em detalhe em [[arquitetura-banco]] §"Queries comuns":
- Últimas N revisões.
- Revisões com `runned=0` (investigação).
- Custo estimado por dia.
- PRs com mais retries (`head_sha` mudou várias vezes).

Ou via Datasette: <http://localhost:8001>.

## Cheatsheet de comandos

```bash
# Tick manual
python3 ~/.claude/heartbeat/heartbeat.py

# Tail de log
tail -f ~/.claude/heartbeat/logs/heartbeat.log

# Listar últimas revisões
sqlite3 ~/.claude/heartbeat/state.db \
  "SELECT runned_at, repo, pr_number, runned, pr_creator FROM code_reviews ORDER BY id DESC LIMIT 10;"

# Pausar cron
crontab -l | sed 's|^\(\*/5.*heartbeat.py.*\)$|# \1|' | crontab -

# Re-armar cron
crontab -l | sed 's|^# \(\*/5.*heartbeat.py.*\)$|\1|' | crontab -

# Matar tick em andamento
pkill -f heartbeat.py
pkill -f "claude -p /code-review"

# Backup do DB
sqlite3 ~/.claude/heartbeat/state.db ".backup ~/.claude/heartbeat/backups/state-$(date +%F).db"

# Datasette status
systemctl --user status datasette-heartbeat

# Update do código (symlinks → git pull propaga)
cd <repo-do-claude-auto-reviewer> && git pull
```

## Quando intervir

| Sinal | Onde olhar |
|---|---|
| PR recém-criado não recebeu CR em ≥10 min | `tail -f heartbeat.log`, ver se cron disparou. Verificar `repos.txt` |
| Comentário esperado não apareceu, mas heartbeat rodou | [[runbook-debugar-revisao-falhada]] — começar pelo log do `code_reviews` |
| Muitos `runned=0` recentes | [[runbook-debugar-revisao-falhada]] §"Muitos runned=0 recentes" |
| `state.db` cresceu (>500MB) | [[runbook-rotacionar-state-db]] §Cleanup |
| Datasette caiu | `systemctl --user restart datasette-heartbeat` |
| Heartbeat aborta com "outro tick em progresso" várias vezes seguidas | Tick anterior travou. `pkill -f heartbeat.py` + investigar log |

## Navegação por MOC

- [[_MOC Onboarding]] — caminho de entrada no projeto.
- [[_MOC Auto-Reviewer]] — visão técnica do sistema.
- [[_MOC Bugs]] — débitos e bugs conhecidos.
- [[_MOC ADRs]] — decisões arquiteturais.
