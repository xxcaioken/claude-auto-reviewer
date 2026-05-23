---
title: ADR-003 — Symlinks no install.sh
type: adr
status: active
tags:
  - adr
  - backend
  - pattern
created: 2026-05-23
updated: 2026-05-23
owner: claude
project: claude-auto-reviewer
related:
  - "[[deploy]]"
  - "[[bugs-conhecidos]]"
tier: 3
---

# ADR-003 — `install.sh` cria symlinks (não copia)

## Contexto

Dois arquivos precisam estar em paths fixos pro sistema funcionar:
- `~/.claude/heartbeat/heartbeat.py` — invocado pelo cron.
- `~/.claude/commands/code-review.md` — lido pelo Claude CLI como comando global.

A questão: como o `install.sh` coloca esses arquivos lá? Cópia ou symlink?

## Decisão

**Symlinks absolutos pro path do clone do repo.**

```bash
ln -sf "$REPO_DIR/heartbeat/heartbeat.py"  "$HEARTBEAT_DIR/heartbeat.py"
ln -sf "$REPO_DIR/commands/code-review.md" "$COMMANDS_DIR/code-review.md"
```

## Consequências

### Positivas

- **Atualização via `git pull`**: zero re-instalação após updates. `cd <repo> && git pull` propaga mudanças imediatamente.
- **Source of truth único**: o arquivo no repo é o oficial. Sem dúvida de "estou editando a cópia ou o original?".
- **Permite editar/testar com hot-reload**: editar `heartbeat.py` no repo → próximo tick do cron usa a versão nova. Não tem build step.
- **Diff fácil**: `git status` no repo mostra mudanças não-committadas em produção, evita drift.
- **Roll-back trivial**: `git checkout <commit>` reverte tudo simultaneamente.

### Negativas

- **Mover o repo de pasta quebra os symlinks**: documentado como [[bugs-conhecidos]] §B-001. Mitigation: rodar `install.sh` de novo do novo path.
- **Apagar o repo desinstala tudo**: pode confundir user que apaga "pra reinstalar limpo" — o cron vai falhar até reinstalar.
- **Distribuição via tarball quebra**: o destinatário precisa manter o tarball extraído num path fixo. Não é problema porque o uso é via git clone.

### Neutras

- Symlink absoluto vs relativo: absoluto escolhido pra funcionar independente do CWD do invocador. Trade-off: menos portável entre máquinas com paths diferentes. Como `install.sh` é re-executável idempotente, não é problema.

## Alternativas consideradas

### A. `cp` (cópia simples)

- **Pró**: independente do path do repo. Pode apagar o clone após install.
- **Contra**: cada update vira `cp <repo>/heartbeat.py ~/.claude/heartbeat/heartbeat.py` manual. Esquecível.
- **Contra**: drift entre o que está em `~/.claude/` e o que está no repo. Investigação fica difícil ("essa versão tem o bug? deixa eu ver o git log... oh, mas a versão em prod é antiga").
- **Veredicto**: rejeitado. Acumula débito operacional rápido.

### B. `pip install -e` (editable install)

- **Pró**: padrão Python pra "instalar do diretório atual".
- **Contra**: requer `setup.py`/`pyproject.toml` + entry point. Mais código.
- **Contra**: instala em `~/.local/bin/`, não em `~/.claude/heartbeat/`. Não resolve `code-review.md`.
- **Veredicto**: rejeitado pra MVP. Considerar se o repo virar pacote distribuído (PyPI).

### C. Container Docker

- **Pró**: isola dependências (Python version, datasette).
- **Contra**: complexidade absurda pra single-process com 0 deps externas além de CLIs. Cron dentro de container vs no host abre nova lata de minhocas.
- **Veredicto**: anti-pattern aqui. Se virar SaaS mantido por outros, reconsiderar.

### D. Script de update separado (`update.sh`)

- **Pró**: pode validar antes de propagar (rodar testes, checar syntax).
- **Contra**: dois scripts pra manter. Replica trabalho do `git pull`.
- **Veredicto**: rejeitado, mas considerar quando tiver testes ([[infra-testes]]).

## Quando reabrir

- **Distribuição muda pra binário/pacote**: PyPI publish, brew formula, etc.
- **Múltiplas máquinas idênticas**: provisioning automatizado (ansible/cloud-init) pode preferir cópia versionada (imutável).
- **Auditoria de segurança requer arquivos non-symlink** em paths privilegiados: rare, mas pode forçar mudança.
