---
title: Regras de negócio — claude-auto-reviewer
type: business-rules
status: active
tags:
  - backend
  - pattern
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[arquitetura]]"
  - "[[arquitetura-banco]]"
  - "[[regras-prompt-review]]"
  - "[[glossario]]"
  - "[[bugs-conhecidos]]"
tier: 1
---

# Regras de negócio — claude-auto-reviewer

Regras que **não são óbvias só lendo o código**. Cada uma protege uma invariante operacional importante.

## Regras e Invariantes

Sumário (cada item detalhado nas seções numeradas abaixo):

1. **Idempotência por `head_sha`** — não re-revisa mesmo commit.
2. **Marcador HTML é contrato** — primeira linha do comentário OBRIGATÓRIA.
3. **`bypassPermissions` + `CLAUDE_CWD=$HOME` são obrigatórios** — sem isso, sistema trava ou usa prompt errado.
4. **Append-only em `code_reviews`, UPSERT em `pr_state`** — modelos de escrita opostos por design.
5. **`runned=0` ≠ erro** — pode ser filtro do prompt funcionando.
6. **Push novo cria comentário novo** (não edita) — rastreabilidade > limpeza visual.
7. **Lock fcntl global** — 1 tick por vez, não 1 PR por vez.
8. **`enabled=0` pausa sem perder configuração**.
9. **`repos.txt` é local** (não versionado).
10. **Sem retry com backoff** — próximo tick reprocessa em silêncio.

**Quebrar qualquer uma destas regras quebra uma garantia operacional documentada.** Antes de mudar, ler a seção correspondente abaixo e considerar criar ADR.

## 1. Idempotência por `(repo, pr_number, head_sha)`

**Regra**: um PR é revisado UMA vez por commit. Re-revisão só acontece se o `head_sha` mudar (push novo).

**Implementação**: `needs_review()` em `heartbeat.py:204` consulta `SELECT 1 FROM code_reviews WHERE repo=? AND pr_number=? AND head_sha=? LIMIT 1`. Se existe linha (independente de `runned=0` ou `1`), pula.

**Consequência sutil**: se o Claude falhou (`runned=0`), o sistema **NÃO retenta** automaticamente no mesmo commit. Isso é intencional — evita loop de falha. Pra forçar retry: `DELETE FROM code_reviews WHERE id=?` ou aguardar push novo. Ver [[runbook-debugar-revisao-falhada]].

## 2. Marcador HTML é contrato de detecção

**Regra**: a primeira linha do corpo do comentário publicado **DEVE** ser `<!-- code-review-bot:v1 -->`.

**Por quê**: `fetch_bot_comments()` (heartbeat.py:179) usa `gh api ... --jq '.[] | select(.body | startswith("<!-- code-review-bot:v1 -->"))'`. Sem marcador, o snapshot before/after não detecta o comentário novo, e o `process_pr` grava `runned=0` **mesmo que o comentário tenha sido publicado**.

**Risco de mudar `MARKER`**: comentários antigos com marcador anterior viram invisíveis ao snapshot. O `before_ids` fica vazio, o `after` também — efeito: o sistema vê o comentário novo como "primeiro de sempre", grava `runned=1` corretamente, mas você perde a contagem histórica. Não quebra, mas confunde análise via Datasette.

**Documentado em**: `commands/code-review.md` §"Regras estritas (modo Heartbeat)" item 6.

## 3. `bypassPermissions` + `CLAUDE_CWD=$HOME` são obrigatórios

**Regra do bypass**: invocar `claude` sem `--permission-mode bypassPermissions` faz o Claude **travar pedindo aprovação interativa** pra rodar `gh`. Como o heartbeat roda via cron (sem TTY), trava silenciosa → timeout 600s → `runned=0`.

**Regra do cwd**: invocar `claude` com `cwd` que tenha `.claude/commands/code-review.md` local faz **o comando local vencer o global**. Isso quebra a arquitetura — o prompt versionado no repo deixa de ser usado. Default `CLAUDE_CWD=$HOME` garante o global.

**Implementação**: `invoke_claude()` em `heartbeat.py:241` passa ambos. Variáveis sobrescrevíveis por env mas defaults seguros.

**Anti-pattern**: nunca rodar o heartbeat com `cwd=<repo-que-tem-.claude/commands/code-review.md>`. Se quiser testar uma versão local do prompt, mude `CLAUDE_CWD` explicitamente e saiba do que está fazendo.

## 4. Append-only em `code_reviews`, UPSERT em `pr_state`

**Regra**: `code_reviews` nunca recebe UPDATE — só INSERT. Cada tentativa de revisão gera uma linha nova, sucesso ou falha.

**Por quê**: histórico imutável. Se uma revisão for "ruim" e o dev mandar um push corretivo, o histórico mostra ambas. Útil pra:
- Auditar quantas tentativas até passar.
- Investigar regressões no prompt (revisões antes/depois de mudança em `code-review.md`).
- Calcular custo real (cada linha = ~1 invocação do Claude).

`pr_state`, ao contrário, é UPSERT por `(repo, pr_number)` — só guarda o último estado. Serve como cache "qual o estado deste PR agora" sem precisar bater no GitHub.

Detalhes do schema: [[arquitetura-banco]].

## 5. Filtros do prompt podem causar `runned=0` "legítimo"

**Regra**: o prompt `code-review.md` tem filtros de "não publicar" (PR draft, diff só `*.md`/lock files, diff vazio, label `skip-code-review`). Quando ativa um filtro, o Claude **não posta** e retorna mensagem curta.

**Comportamento do heartbeat**: o snapshot detecta zero comentários novos → `save_review(runned=False)`. **Isto não é falha** — é o sistema funcionando corretamente.

**Como distinguir falha real de filtro**: inspecionar coluna `log` da linha `runned=0`:
- `rc=0` + stdout curto explicando "diff só docs" → filtro do prompt.
- `rc != 0` ou stderr não-vazio → falha real (timeout, gh sem auth, etc.).

Ver [[runbook-debugar-revisao-falhada]] pra o passo-a-passo.

## 6. Re-revisão por push novo cria comentário novo, não edita

**Regra**: se um PR recebe `push`, o `head_sha` muda. O sistema revisa de novo e **adiciona um novo comentário** (não usa `gh pr comment --edit-last`).

**Por quê**: rastreabilidade. O dev vê a evolução das revisões. Trade-off: PRs com muitas iterações ficam ruidosos. Há ticket no roadmap (`README.md` §Roadmap) pra mudar pra `--edit-last`, mas requer guardar `comment_id` e gerenciar edição vs criação. Ver [[tech-debt]] §`--edit-last`.

## 7. Lock fcntl global → 1 tick por vez (não 1 PR por vez)

**Regra**: `fcntl.flock(LOCK_EX | LOCK_NB)` no início do `main()`. Ticks subsequentes que tentam pegar o lock recebem `BlockingIOError` e abortam **silenciosamente** (log INFO, não ERROR).

**Consequência operacional**: se há lote grande (20 PRs × 5 min = ~100 min de processamento), os ticks do cron a cada 5 min vão abortar todos. Isto é desejado. Ver [[ADR-001-cron-vs-webhook]] §Consequências.

**Como interromper um tick travado**: `pkill -f heartbeat.py; pkill -f "claude -p /code-review"`. O próximo tick do cron pega o lock (já solto pelo OS) e segue.

## 8. `enabled=0` em `repos.txt` pausa sem perder configuração

**Regra**: linhas em `repos.txt` com último campo `0` são ignoradas pelo `load_repos`. Mantém a linha pra reativar fácil (trocar `|0` por `|1`).

**Ver**: [[runbook-adicionar-repo]] pra o formato completo.

## 9. `repos.txt` é local (não versionado)

**Regra**: `repos.txt` está em `.gitignore` (heartbeat/repos.txt). Cada instalação tem o seu. O versionado é `repos.txt.example`.

**Por quê**: lista de repos é configuração do usuário, não do projeto.

## 10. Sem retry com backoff em falha de `gh`

**Regra**: se `gh pr list` ou `gh api` falham (timeout, rede), o heartbeat loga warning, retorna `[]`/`[]`, e segue. **Não há retry interno**. O próximo tick (5 min) reprocessa.

**Consequência**: rede flaky pode atrasar a revisão por 1+ ticks. Aceitável dado que CR não é tempo-real.
