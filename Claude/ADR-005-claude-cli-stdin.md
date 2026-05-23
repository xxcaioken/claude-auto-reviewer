---
title: ADR-005 — Claude posta direto, não retorna markdown
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
  - "[[regras-prompt-review]]"
  - "[[regras-negocio]]"
  - "[[modulo-heartbeat]]"
tier: 3
---

# ADR-005 — Claude posta o comentário direto, heartbeat detecta via snapshot

## Contexto

O fluxo "Claude revisa PR e o resultado vira comentário" pode ser implementado de duas formas:

1. **Heartbeat orquestra**: Claude retorna o markdown via stdout. Heartbeat captura e chama `gh pr comment` manualmente.
2. **Claude orquestra**: Claude usa `gh pr comment` ele mesmo. Heartbeat só detecta o comentário publicado (via snapshot before/after).

## Decisão

**Claude posta direto.** Heartbeat invoca `claude --permission-mode bypassPermissions -p '/code-review <url> publique'`, Claude usa `gh pr comment ... --body-file -` ele mesmo, heartbeat detecta o comentário novo via snapshot.

O Claude retorna apenas `Publicado em <url-do-comentário>` no stdout — uma confirmação humana, não dado estruturado.

## Consequências

### Positivas

- **Heartbeat fica burro (= robusto)**: não precisa parsear markdown grande, não precisa lidar com encoding, não precisa cuidar de heredoc em bash. Sua única responsabilidade é "snapshot antes, snapshot depois, diff".
- **Limite do GitHub é problema do Claude**: ~65k chars. Claude lida com truncamento conforme regras do prompt ([[regras-prompt-review]] §"Limite de tamanho do comentário"). Heartbeat não vê o markdown completo.
- **Encoding sem dor**: Claude escreve direto via `gh` (que cuida de UTF-8 + newlines). Heartbeat não passa string grande via `subprocess`.
- **Erros do `gh pr comment` ficam no domínio do Claude**: se falha (PR fechado, sem permissão), Claude sabe e pode tentar recover ou retornar mensagem. Heartbeat só vê "stdout não menciona URL novo" e age fail-soft.
- **Posta com a identidade certa**: `gh` usa as credenciais do user que rodou. Comentário fica autoria do user (perfeito pra MVP single-user).
- **Reaproveita inteligência do Claude**: filtros de "não publicar" (diff só docs, PR draft inesperado) vivem no prompt onde podem evoluir com nuance. Não em código rígido do heartbeat.

### Negativas

- **Heartbeat precisa de snapshot before/after**: 2 chamadas `gh api` por PR pra detectar o comentário novo. Custo: ~2s extra por revisão.
- **Detecção depende do marcador HTML**: contrato implícito entre prompt e heartbeat ([[regras-negocio]] §2). Se Claude esquece o marcador, comentário publicado mas heartbeat marca `runned=0`. Mitigação: regra é explícita e numerada no prompt.
- **`bypassPermissions` obrigatório**: sem isso, Claude trava pedindo aprovação pra `gh`. Documentado e default no `invoke_claude` ([[regras-negocio]] §3).
- **Comentário pode ter sido publicado mesmo com `runned=0`**: snapshot pode falhar (rate-limit, timeout). Comentário fica "órfão" — existe no PR, ausente no SQLite. Caso raro mas documentado em [[error-handling]] §"Cenário D".
- **Confiar no Claude pra usar `gh` "direito"**: prompt assume Claude conhece sintaxe `gh pr comment --body-file -`. Quebra se Claude default mudar comportamento (regression do modelo).

### Neutras

- Postagem síncrona — Claude bloqueia até confirmar publicação. Sem fila.

## Alternativas consideradas

### A. Heartbeat captura stdout do Claude e posta

```python
rc, stdout, stderr = invoke_claude(pr_url)
if rc == 0 and stdout.strip():
    subprocess.run(["gh", "pr", "comment", str(pr_num),
                    "--repo", gh_repo, "--body-file", "-"],
                   input=stdout, text=True)
```

- **Pró**: heartbeat tem controle direto, snapshot desnecessário.
- **Contra**: stdout pode misturar markdown com mensagens do Claude (tipo "Pensei sobre..."). Parsing frágil.
- **Contra**: Claude pode mandar limpeza extra (logs, debug) que vão pro PR.
- **Contra**: Claude precisa de jeito de sinalizar "não publicar" (filtros). Hoje ele só não posta. Com captura stdout, viraria string mágica (`"[SKIP]"`) ou exit code.
- **Contra**: limite de 65k chars vira problema do heartbeat (truncate em código, perde nuance da priorização do prompt).
- **Veredicto**: viável mas perde modularidade. Rejeitado por todas as razões positivas listadas acima.

### B. Webhook reverso — Claude chama HTTP endpoint do heartbeat

- **Pró**: confirmação estruturada (JSON).
- **Contra**: requer HTTP server no heartbeat. Quebra "zero infra" do [[ADR-001-cron-vs-webhook]].
- **Veredicto**: rejeitado por consistência arquitetural.

### C. Claude escreve em arquivo, heartbeat lê

- **Pró**: independente de stdout.
- **Contra**: file I/O + cleanup + lifecycle do arquivo. Mais peças móveis.
- **Veredicto**: rejeitado por sobre-engenharia.

### D. Não publicar — só salvar no SQLite, dev vê via Datasette

- **Pró**: zero ruído em PR.
- **Contra**: defeats purpose (dev não recebe feedback no contexto do PR).
- **Veredicto**: rejeitado.

## Quando reabrir

- **Resposta estruturada vira requisito**: se quisermos extrair, p.ex., contagem de issues por severidade pro SQLite, vai precisar de output estruturado do Claude (JSON em vez de markdown). Aí faz sentido o heartbeat parsear stdout. Considerar adicionar fase de "stage" antes do publish.
- **Múltiplos publishers** (postar tb em Slack além de PR): Claude orquestrando vira limitante. Heartbeat orquestrando dá fan-out natural.
- **Edição em vez de novo comentário** ([[tech-debt]] §TD-003): provavelmente força refator pra heartbeat passar `comment_id` pra editar. Claude continua postando, mas o que ele invoca muda (`gh api PATCH` em vez de `gh pr comment`).
