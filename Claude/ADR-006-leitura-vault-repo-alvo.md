---
title: ADR-006 — Leitura do vault Obsidian do repo-alvo durante review
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
  - "[[ADR-005-claude-cli-stdin]]"
  - "[[arquitetura]]"
tier: 3
---

# ADR-006 — Leitura do `Claude/` do repo-alvo durante o review

## Contexto

O `commands/code-review.md` é hoje stack-agnóstico — adapta análise pela extensão dos arquivos no diff, mas não conhece convenções, ADRs ou regras de negócio específicas do repo sendo revisado. Resultado: review tecnicamente correto mas genérico; não consegue dizer "esta abordagem contraria ADR-002 do seu repo" ou "esta query reintroduz o bug B-007".

Vários repos do ecossistema NPU-Brain (e este próprio repo) mantêm um vault Obsidian em `<REPO_PATH>/Claude/` documentando:
- Regras de negócio (`regras-negocio.md`, `regras-*.md`).
- Bugs conhecidos (`bugs-conhecidos.md`).
- ADRs (`ADR-NNN-*.md`).
- Arquitetura (`arquitetura.md`, `arquitetura-banco.md`).

Esses arquivos representam **contrato documentado** do repo. Sem ler, o reviewer perde contexto crítico.

## Decisão

**O prompt instrui o Claude a ler `<REPO_PATH>/Claude/*.md` quando o diretório existe**, e usar como contexto adicional na análise. Quando não existe, comporta exatamente como antes — **graceful degradation total**, sem mencionar a ausência do vault.

Implementação: nova seção em `commands/code-review.md` §"Contexto do repo via Obsidian vault (opcional)" + regra estrita 7 ("CONSULTAR VAULT QUANDO EXISTE"). Sem mudanças no `heartbeat.py` — o Claude lê os arquivos ele mesmo, é só prompt-level.

Path do repo — **cascata em 3 níveis** (refinamento posterior à decisão original):

1. **`<path_local>/Claude/`** do `repos.txt` (forma canônica — usuário declara explicitamente onde está cada repo).
2. **`$HOME/code/<basename>/Claude/`** (convenção do ecossistema NPU-Brain — repos clonados via `npu-brain-setup.sh` ficam aqui).
3. **`./Claude/`** (modo interativo — Claude já está no cwd do repo).

Cascata garante robustez se `path_local` está mal configurado (ex: `/dev/null` do `.example`, path obsoleto após `mv` do clone), sem prejudicar usuários fora do ecossistema NPU (que continuam usando caminho 1 ou caindo no graceful degradation).

## Consequências

### Positivas

- **Reviews contextualizados** quando vault existe: cita ADR específica ao discordar, flag explícito ao reintroduzir bug conhecido, severidade calibrada pela criticidade da regra violada.
- **Educação passiva do time**: comentários do reviewer citam `[[Claude/regras-X]]` — devs aprendem o vault só lendo reviews.
- **Independente do mesh NPU-Brain**: capability vive aqui, no prompt. Repo-alvo só precisa ter `Claude/`. Sem coupling com `.knowledge-sync.yml` ou skill `knowledge-sync`.
- **Compatibilidade total para repos sem vault**: graceful degradation. Sem regression em repos hoje monitorados que não têm `Claude/`.
- **Sem mudança no `heartbeat.py`**: implementação puramente no prompt. Risco operacional zero.
- **Acumulação de valor**: à medida que mais repos adotam vault, mais reviews ganham contexto. Sem mudança no reviewer.

### Negativas

- **Custo de tokens por revisão**: vault típico tem ~80-200KB. Leitura completa adiciona ~3-5K tokens por invocação. Mitigado por leitura seletiva por área do diff.
- **Vault stale pode fornecer info errada**: line numbers desatualizados, regras revogadas mas não removidas. Mitigado pela instrução "tratar como guia, não fato; cruzar com código atual". Risco baixo aqui porque o curador roda `/knowledge-sync` diariamente, mas o prompt assume vault potencialmente stale por segurança.
- **Tentação de over-cite**: reviewer pode citar nota irrelevante só pra "mostrar que leu". Mitigado pelo prompt: "não citar nota que você não leu" + foco em violações/contradições reais.
- **Comentário fica mais denso**: links pro vault aumentam tamanho. Aceitável (cabe no limite de 65k do GitHub).

### Neutras

- **Não atualiza o vault** — leitura unidirecional. Curadoria continua sendo trabalho do `/knowledge-sync` (manual, single-curator).
- **Não detecta drift do vault** — flag tipo "PR mudou X mas vault não" foi descartado intencionalmente (ver Alternativas §C).

## Alternativas consideradas

### A. Não ler nada — manter stack-agnostic

- **Pró**: zero custo de tokens, zero risco de info stale.
- **Contra**: review continua genérico. Perde o ganho composto do ecossistema NPU-Brain (cérebros existem mas reviewer ignora).
- **Veredicto**: rejeitado. O custo de tokens é baixo vs ganho qualitativo do review.

### B. `heartbeat.py` lê o vault e injeta no prompt como argumento

- **Pró**: separação clara, vault carregado uma vez por revisão.
- **Contra**: aumenta complexidade do heartbeat (precisa parsear, decidir o que carregar, lidar com tamanhos). Quebra [[ADR-005-claude-cli-stdin]] §"heartbeat é orquestrador burro".
- **Contra**: Claude já tem ferramentas pra ler arquivos via `cat` — desnecessário pre-carregar.
- **Veredicto**: rejeitado. Mantém heartbeat burro, lê quem precisa ler (Claude).

### C. Ler vault + flagar drift (PR mudou X mas vault não foi atualizado)

- **Pró**: reviewer vira enforcer automático do `knowledge-sync`. Detecta drift que o curador veria só na próxima sincronização manual.
- **Contra**: cria pressão indireta no autor do PR — "agora também sou responsável pelo vault?". Pode gerar fricção e label `skip-code-review` defensivo.
- **Contra**: curador roda `/knowledge-sync` diariamente — drift máximo é 24h, baixo risco.
- **Veredicto**: rejeitado **por ora**. Reabrir se o curador ficar sobrecarregado ou se o drift começar a doer.

### D. Vault central separado dos repos (referenciado por todos os reviewers)

- **Pró**: 1 vault, N reviewers — single source of truth.
- **Contra**: cada repo tem regras próprias. Vault central vira gigante e genérico, perde a especificidade que dá valor.
- **Contra**: pra atualizar o vault de 1 repo, dev precisa ir em outro lugar. Atrito.
- **Veredicto**: rejeitado. O modelo "vault co-localizado com código" do `brain-seed` já está estabelecido.

## Quando reabrir

- **Custo de tokens fica relevante**: se vault crescer pra >500KB típico, ou se a conta do Claude começar a doer, considerar pre-filtragem (carregar só notas com tags relevantes à área do diff).
- **Vault drift virar problema apesar do sync diário**: reconsiderar Alternativa C (flag de drift).
- **Mais de 1 curador no time**: review pode ajudar a coordenar — flag "esta nota foi tocada por dois PRs simultâneos, conflito potencial".
- **Pedido de revisão também atualizar vault**: hoje uni-direcional. Se quisermos bi-direcional, exigiria prompt mais elaborado + possível mudança em `process_pr` pra detectar/persistir mudanças no vault. Significativo.
- **Adoção do vault em <30% dos repos monitorados**: se quase ninguém tem `Claude/`, o ganho do feature é baixo — considerar simplificar prompt removendo a seção.
