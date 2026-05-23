---
title: Runbook — adicionar repo ao monitoramento
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
  - "[[glossario]]"
  - "[[runbook-testar-localmente]]"
tier: 3
---

# Runbook — adicionar um repo novo ao monitoramento

## Quando usar
- Novo projeto que quer code review automático nos PRs.
- Reativar repo que estava com `enabled=0`.

## Pré-requisitos
- `gh auth status` funcional com permissão de leitura no repo (`repo` scope).
- Clone local do repo (não obrigatório, mas o prompt lê `CLAUDE.md` local se existir).

## Passos

### 1. Confirmar que `gh` enxerga o repo
```bash
gh pr list --repo <owner>/<repo> --state open --limit 1
```

Se der erro de permissão, rodar:
```bash
gh auth refresh -s repo
```

### 2. (Opcional) Clonar localmente
```bash
git clone https://github.com/<owner>/<repo>.git ~/code/<repo>
```

Não é necessário, mas o prompt `/code-review` tenta ler `<path_local>/CLAUDE.md` se existir, e pega contexto adicional.

### 3. Adicionar linha em `repos.txt`
Editar:
```bash
nano ~/.claude/heartbeat/repos.txt
```

Formato (4 campos pipe-separated):
```
nome_local|path_local|owner/repo|enabled
```

- `nome_local`: identificador interno (qualquer string, sem `|`). Usado em logs e na coluna `repo` do SQLite. Convenção: kebab-case curto.
- `path_local`: caminho absoluto do clone. Se não tem, usar string qualquer (ex: `/dev/null`) — o prompt apenas tenta ler `CLAUDE.md` desse path, falha silenciosa. **Convenção NPU-Brain**: repos clonados via `npu-brain-setup.sh` ficam em `~/code/<repo>/`. O prompt detecta esse fallback automaticamente ([[ADR-006-leitura-vault-repo-alvo]] §Detecção em cascata).
- `owner/repo`: usado por `gh pr list --repo <owner/repo>`.
- `enabled`: `1` ativo, `0` pausado. Default `1` se ausente.

Exemplo:
```
meu-app|/home/me/code/meu-app|minha-org/meu-app|1
```

### 4. Validar sem invocar Claude

Rodar um tick e ver se o repo aparece no log sem erro:
```bash
python3 ~/.claude/heartbeat/heartbeat.py
tail -30 ~/.claude/heartbeat/logs/heartbeat.log
```

Esperado:
```
Processando meu-app (minha-org/meu-app)
  N PR(s) aberto(s)
```

Se houver PRs abertos não revisados, o Claude será invocado em sequência — pode demorar. Pra só validar a descoberta sem invocar Claude, ver §"Pausar Claude temporariamente" abaixo.

### 5. (Opcional) Marcar PRs antigos como já revisados

Cenário: repo tem 50 PRs abertos antigos que você NÃO quer revisar todos. Sem ação, o próximo tick revisa todos (custo $$$).

Pre-seed do SQLite pra pular os antigos:
```bash
sqlite3 ~/.claude/heartbeat/state.db <<'SQL'
INSERT INTO code_reviews (repo, pr_number, pr_name, pr_creator, pr_url, head_sha, cr_description, pr_state, runned)
SELECT 'meu-app', 1, 'pre-seed', 'system', 'https://github.com/minha-org/meu-app/pull/1', 'aaaa', '', 'OPEN', 0
WHERE NOT EXISTS (SELECT 1 FROM code_reviews WHERE repo='meu-app' AND pr_number=1);
SQL
```

Mais escalável: script Python que itera os PRs abertos via `gh pr list --json number,headRefOid` e insere uma linha pra cada com `runned=0`. Próximos pushes nesses PRs (que mudam `head_sha`) serão revisados.

Alternativa simples: aplicar label `skip-code-review` nos PRs antigos (manualmente ou via `gh pr edit <num> --add-label skip-code-review`).

### 6. Confirmar via Datasette (opcional)
- <http://localhost:8001> → tabela `pr_state` → filtrar por `repo='meu-app'` → ver lista atualizada após o tick.

## Pausar Claude temporariamente

Pra testar adição de repo sem gastar com Claude:

```bash
# Renomear binário pra forçar check_prerequisites a falhar
mv ~/.local/bin/claude ~/.local/bin/claude.bak

# Tick não invoca Claude (sai logo após check)
python3 ~/.claude/heartbeat/heartbeat.py

# Restaurar
mv ~/.local/bin/claude.bak ~/.local/bin/claude
```

Ou: aplicar `skip-code-review` em todos os PRs antes de adicionar o repo, depois remover gradualmente.

## Adicionar múltiplos repos de uma vez

Múltiplas linhas em `repos.txt`. Ordem importa apenas pra log (processamento sequencial).

Se >5 repos com muitos PRs, considerar onboarding gradual:
1. Adicionar 1 repo, esperar lote inicial estabilizar.
2. Adicionar próximo repo no dia seguinte.

Lote inicial grande pode atravessar vários ticks (lock fcntl aborta os intermediários — ver [[regras-negocio]] §7).

## Reverter

Desativar (mantém histórico):
```bash
# Trocar último campo |1 por |0 em repos.txt
sed -i 's|\(meu-app|.*|.*|\)1$|\10|' ~/.claude/heartbeat/repos.txt
```

Próximo tick ignora. Sem perda de dados.

Remover completamente:
1. Deletar linha do `repos.txt`.
2. (Opcional) Apagar histórico do SQLite:
   ```bash
   sqlite3 ~/.claude/heartbeat/state.db "DELETE FROM code_reviews WHERE repo='meu-app';"
   sqlite3 ~/.claude/heartbeat/state.db "DELETE FROM pr_state WHERE repo='meu-app';"
   ```
   Cuidado: perde auditoria. Considere backup ([[deploy]] §Backup).

## Notas relacionadas
- [[env-setup]] — vars de ambiente caso queira customizar comportamento por instância.
- [[runbook-debugar-revisao-falhada]] — se as primeiras revisões falharem.
- [[glossario]] §`enabled` e §`repos.txt`.
