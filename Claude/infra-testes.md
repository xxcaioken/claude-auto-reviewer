---
title: Infraestrutura de testes (estado atual + plano)
type: tech-debt
status: draft
tags:
  - backend
  - debt/alta
  - pending
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[tech-debt]]"
  - "[[modulo-heartbeat]]"
  - "[[regras-prompt-review]]"
tier: 2
---

# Infraestrutura de testes

## Estado atual

**Zero testes automatizados.** Nada em `tests/`, sem `pytest.ini`, sem `tox.ini`, sem CI. Validação hoje é 100% manual: rodar `python3 heartbeat.py` em um repo de teste e olhar o resultado.

Confirmação:
```bash
find . -name "test_*.py" -o -name "*_test.py" -o -name "tests" -type d
# (vazio)
```

Sem CI: `.github/` não existe no repo. Workflow GitHub Actions seria primeiro passo.

## Por quê isto importa

O `heartbeat.py` tem lógica subtil onde regressões silenciosas custam caro:

1. **`needs_review`** decide se gasta dinheiro com Claude. Bug aqui = revisa de novo o mesmo commit (custo dobrado) ou não revisa quando deveria (PRs sem CR).
2. **Snapshot before/after** (`process_pr`). Bug = `runned` errado, histórico furado.
3. **Parse de `repos.txt`** (`load_repos`). Bug em linha mal-formada = repo ignorado silenciosamente, dev não percebe.
4. **Schema migrations** (`init_db`). Bug = DB antigo quebra ao atualizar o script.
5. **Lock fcntl** (`main`). Bug = ticks duplicam, custo paralelo.

Detalhado em [[tech-debt]] §TD-001.

## Plano sugerido (não implementado)

### Fase 1 — Testes puros (sem mock de subprocess)

Stack: `pytest` + `pytest-mock`. Adicionar `requirements-dev.txt` (não toca produção).

Funções alvo (todas determinísticas em isolamento):

#### `load_repos`
- Linha bem-formada → entry no resultado.
- Linha começando com `#` → ignorada.
- Linha vazia → ignorada.
- Linha mal-formada (menos de 3 pipes) → warning + ignorada (verificar via caplog).
- `enabled=0` → ignorada.
- `enabled=1` (default ausente) → incluída.

#### `needs_review`
Setup: `conn = sqlite3.connect(':memory:'); init_db(conn)`.
Casos:
- PR draft → False.
- PR com label `skip-code-review` → False.
- PR sem row em `code_reviews` → True.
- PR com row em `code_reviews` com mesmo head_sha → False (independente de `runned`).
- PR com row de outro head_sha → True.

#### `init_db`
- DB vazio → cria tabelas.
- DB com schema antigo (sem coluna `log`) → executa migration ALTER TABLE.
- DB com schema atual → no-op (idempotente).

Aproximadamente 15-20 testes pra cobrir o crítico. Roda em <1s.

### Fase 2 — Testes com `subprocess.run` mockado

Funções: `gh_pr_list`, `fetch_bot_comments`, `invoke_claude`.

Padrão:
```python
def test_gh_pr_list_handles_timeout(mocker):
    mocker.patch("heartbeat.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=60))
    result = heartbeat.gh_pr_list("org/repo")
    assert result == []
```

Cobertura desejada: cada `except` documentado em [[error-handling]] tem teste correspondente.

### Fase 3 — Teste de integração end-to-end (smoke)

Cenário: rodar o `heartbeat.py` contra um repo GitHub de teste real (não simulado), com `CLAUDE_BIN` apontando pra um script bash que mocka o Claude (echo do markdown esperado).

Útil pra detectar regressões em mudanças do CLI (`gh` ou `claude`) que mudam contrato de output.

Mais frágil — só rodar em CI marcado como integration, não em todo commit.

### Fase 4 — CI

GitHub Actions workflow em `.github/workflows/test.yml`:

```yaml
name: tests
on: [push, pull_request]
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.10"}
      - run: pip install -r requirements-dev.txt
      - run: pytest tests/ -v
```

Sem precisar de secrets — testes Fase 1 e 2 são todos offline. Fase 3 (integração) precisaria de PAT do GitHub e binário do Claude, deixar pra workflow separado manual.

## O que NÃO testar

- **Prompt do `code-review.md`** — não é código testável unitariamente. Validação é qualitativa (revisar comentários publicados, ajustar prompt).
- **Comportamento do Claude** — black-box modelo. Mudar de versão do modelo pode mudar saídas; isto é teste de aceitação humana, não unitário.
- **`install.sh`** — bash. Smoke test "roda sem erro" via shellcheck + execução em container limpo, mas baixo ROI vs custo de manter.

## Métricas que existiriam com testes

Quando os testes existirem, queremos saber:
- **Cobertura** (`pytest-cov`) — apontar pras funções de [[tech-debt]] §TD-001 e proteger contra rollback.
- **Tempo total** — manter <5s pra suite Fase 1+2.
- **Flakiness** — zero em Fase 1+2. Fase 3 (integração) tolerável até 5% (rede).
