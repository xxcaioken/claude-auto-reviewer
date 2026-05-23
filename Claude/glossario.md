---
title: Glossário de termos do projeto
type: reference
status: active
tags:
  - reference
  - backend
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[arquitetura]]"
  - "[[regras-negocio]]"
  - "[[arquitetura-banco]]"
tier: 1
---

# Glossário

Termos específicos deste repo. Em ordem alfabética. Cada termo linka pra nota que explora mais.

## Regras e Invariantes

- **Ordem alfabética estrita** — adicionar termo novo no lugar certo.
- **Cada termo linka pra nota que explora** — não duplicar definição, redirecionar.
- **Só termos não-óbvios pra desenvolvedor médio** — não definir "PR" ou "SQLite", definir "head_sha" e "snapshot before/after".
- **Quando definição muda no código, atualizar aqui na mesma sessão** — glossário stale é pior que ausente.

---

### Append-only
Padrão de persistência onde nunca há UPDATE — só INSERT. Aplica-se à tabela `code_reviews`. Cada execução de revisão adiciona uma linha nova; mesmo `(repo, pr_number)` pode ter N linhas (uma por `head_sha`). Ver [[arquitetura-banco]] §`code_reviews`.

### `bypassPermissions`
Modo do `claude` CLI (`--permission-mode bypassPermissions`) que pula prompts interativos de autorização (ex: "permitir rodar `gh`?"). **Obrigatório no heartbeat** porque cron não tem TTY pra responder. Sem isso, o Claude trava → timeout → `runned=0`. Ver [[regras-negocio]] §3.

### CR (Code Review)
Sigla usada nos IDs do comentário (`CR-001`, `CR-002`...). Numeração contínua através de todas severidades (não reseta entre 🔴/🟡/🟢). Definido em `commands/code-review.md` §"Regras de renderização".

### `cr_description`
Coluna da tabela `code_reviews` — guarda o **markdown completo** do comentário publicado, NÃO a descrição do PR. Vazio quando `runned=0`. Pode ter ~50KB em PRs grandes. Ver [[arquitetura-banco]].

### `enabled` (em `repos.txt`)
Quarto campo da linha pipe-separated. `1` = monitorado, `0` = pausado mas mantém a config. Linhas com `0` são puladas no `load_repos` (heartbeat.py:152). Ver [[runbook-adicionar-repo]].

### Heartbeat
Nome do processo cron que dispara o ciclo de revisão. Cada execução é um "tick". Single-process, single-machine. Implementado em `heartbeat/heartbeat.py`.

### `head_sha`
SHA do commit no topo da branch do PR (campo `headRefOid` retornado por `gh pr list`). É a **chave de idempotência** — `needs_review` verifica se já existe `code_reviews` com mesmo `(repo, pr_number, head_sha)`. Push novo no PR → `head_sha` muda → nova revisão. Ver [[regras-negocio]] §1.

### Marcador HTML
A string `<!-- code-review-bot:v1 -->` que deve ser a **primeira linha** de todo comentário publicado. É contrato entre o prompt (`code-review.md`) e o detector (`fetch_bot_comments`). Sem ele, o snapshot before/after não detecta o comentário → `runned=0`. Configurável via env `MARKER`, mas **não mudar em produção** ([[bugs-conhecidos]] §B-002).

### Modo Heartbeat
Modo de operação do prompt `/code-review` quando o argumento contém "publique" ou URL de PR. Posta direto via `gh pr comment`, não retorna markdown. Definido em `commands/code-review.md` §"Modos de operação". Contrasta com modo interativo.

### Modo Interativo
Modo do `/code-review` invocado por dev (sem "publique"). Gera relatório, oferece via `AskUserQuestion`: salvar arquivo / publicar comentário / criar issues / só exibir.

### `MOC` (Map of Content)
Notas do vault que começam com `_MOC ` — funcionam como landing pages temáticas. Listam outras notas com contexto. Ver as 5 MOCs: [[_MOC Auto-Reviewer]], [[_MOC Onboarding]], [[_MOC Operacao]], [[_MOC Bugs]], [[_MOC ADRs]].

### `pr_state` (tabela)
Cache UPSERT do último estado conhecido de cada PR. Atualizada toda execução de `process_repo`. Útil pra consultar "qual o estado deste PR agora" sem bater no GitHub. Independente de `code_reviews` (que é append-only). Ver [[arquitetura-banco]].

### `pr_state` (coluna)
Coluna da `code_reviews` que registra o estado do PR no momento da revisão (`OPEN` / `MERGED` / `CLOSED`). Útil pra TTL de retenção (TD-007 em [[tech-debt]]).

### `repos.txt`
Arquivo de configuração que lista os repos monitorados. Formato: `nome_local|path_local|owner/repo|enabled` por linha. Local (não versionado — `.gitignore`). Template versionado: `heartbeat/repos.txt.example`.

### `runned`
Coluna booleana em `code_reviews`. `1` = Claude executou E publicou comentário com marcador detectado. `0` = Claude executou mas snapshot não detectou comentário novo (timeout, erro, ou filtro do prompt — diff só docs, etc.). **Não é "tentou rodar"** — é "rodou com sucesso completo". Ver [[regras-negocio]] §5.

### `skip-code-review` (label)
Label do GitHub que, quando aplicada a um PR, faz o heartbeat pular a revisão. Verificada em `needs_review` (heartbeat.py:211-213). Customizável via env `SKIP_LABEL`.

### Snapshot before/after
Padrão usado em `process_pr` (heartbeat.py:282) pra detectar comentário novo. Lê comentários do bot **antes** (`before_ids`), invoca o Claude, lê de novo **depois** (`after`), diff por `id`. Comentário com id em `after` mas não em `before` = novo. Por que não confiar no stdout do Claude? Porque o Claude pode rodar, postar, e ainda assim falhar de modos diferentes (timeout no fim, retry interno). O snapshot é a fonte da verdade.

### Tick
Uma execução do `heartbeat.py`. Sequência: lock → check_prerequisites → init_db → load_repos → process_repo × N. Tipicamente disparado pelo cron a cada 5 min. Ticks paralelos abortam silenciosamente via lock fcntl. Ver [[regras-negocio]] §7.

### WAL (Write-Ahead Logging)
Modo SQLite ativado por `PRAGMA journal_mode=WAL` (heartbeat.py:121). Permite leituras simultâneas a uma escrita (ex: heartbeat escrevendo + datasette lendo, sem conflito). Cria arquivos auxiliares `state.db-shm` e `state.db-wal` (ambos no `.gitignore`).
