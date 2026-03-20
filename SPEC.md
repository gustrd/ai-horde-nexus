# Horde Scribe Worker — Especificação Arquitetural e Análise Crítica

## Documento de referência para implementação via Claude Code

**Versão:** 0.2-draft
**Última atualização:** 2026-03-19

ATTENTION: EVEN WITH THIS PT-BR SPEC, ALL CODE AND COMMENTS MUST BE DONE IN ENGLISH

---

## ÍNDICE

1. [Contexto e Motivação](#1-contexto-e-motivação)
2. [Análise do Ecossistema Existente](#2-análise-do-ecossistema-existente)
3. [Análise Crítica do Rascunho Atual](#3-análise-crítica-do-rascunho-atual)
4. [Arquitetura Alvo](#4-arquitetura-alvo)
5. [Estrutura de Diretórios](#5-estrutura-de-diretórios)
6. [Módulo: Configuração (`core/config.py`)](#6-módulo-configuração)
7. [Módulo: Logger (`core/logger.py`)](#7-módulo-logger)
8. [Módulo: Horde API Client (`core/horde_api.py`)](#8-módulo-horde-api-client)
9. [Módulo: Parameter Mapper (`core/params.py`)](#9-módulo-parameter-mapper)
10. [Módulo: Backend Adapters (`backends/`)](#10-módulo-backend-adapters)
11. [Módulo: Worker Threads (`worker.py`)](#11-módulo-worker-threads)
12. [Módulo: Orchestrator / Main (`main.py`)](#12-módulo-orchestrator--main)
13. [Módulo: Health Monitor (`core/health.py`)](#13-módulo-health-monitor)
14. [Módulo: Blacklist e Filtros (`core/filters.py`)](#14-módulo-blacklist-e-filtros)
15. [Concorrência e Modelo de Threading](#15-concorrência-e-modelo-de-threading)
16. [Resiliência e Tratamento de Falhas](#16-resiliência-e-tratamento-de-falhas)
17. [Ciclo de Vida Pop → Generate → Submit](#17-ciclo-de-vida-pop--generate--submit)
18. [Mapa de Parâmetros por Backend](#18-mapa-de-parâmetros-por-backend)
19. [Deploy Multi-Máquina](#19-deploy-multi-máquina)
20. [Testes](#20-testes)
21. [Decisões Pendentes e Riscos](#21-decisões-pendentes-e-riscos)

---

## 1. Contexto e Motivação

O AI Horde é um cluster distribuído e comunitário para geração de imagens e texto com IA. Voluntários rodam "workers" que processam jobs da fila centralizada e recebem "kudos" como recompensa. A parte de texto (chamada "Scribe") funciona assim: o worker faz polling na API do Horde pedindo jobs (`POST /v2/generate/text/pop`), recebe um prompt com parâmetros de geração, envia o prompt para um backend local de inferência LLM (como KoboldCpp, llama.cpp server, Aphrodite Engine, TabbyAPI), coleta o texto gerado, e devolve ao Horde (`POST /v2/generate/text/submit`).

O problema é que o worker oficial de texto (AI-Horde-Worker da Haidra) é um codebase monolítico que mistura workers de imagem, texto e alchemy. Ele foi construído ao longo de anos com contribuições orgânicas, acumulando dívida técnica. Para quem quer rodar apenas texto em várias máquinas com backends diferentes, a experiência é péssima: instalação pesada, configuração confusa, single-threaded por padrão, frágil diante de falhas do backend, e sem boa abstração para trocar backends.

Este projeto nasce para ser uma alternativa limpa, focada exclusivamente em text generation (Scribe), com suporte real a múltiplos backends e execução concorrente de jobs sobre o mesmo backend. A premissa é que o operador já tem um backend rodando (KoboldCpp, llama.cpp server, Aphrodite, TabbyAPI) e quer apenas a "cola" entre o Horde e esse backend — leve, resiliente, e fácil de deployar em N máquinas.

---

## 2. Análise do Ecossistema Existente

### 2.1. Haidra AI-Horde-Worker (oficial)

O repositório `Haidra-Org/AI-Horde-Worker` é o worker de referência mantido pela organização que opera o Horde. Historicamente, ele centralizava workers de imagem (Dreamer), texto (Scribe) e pós-processamento (Alchemist) no mesmo codebase. Em janeiro de 2024, o worker de imagem foi migrado para o `horde-worker-reGen`, mas o worker de texto continua vivendo nesse repo legado.

**Pontos positivos:**
- É a referência oficial, portanto está sempre alinhado com as mudanças de API.
- Suporta tanto a API KoboldAI quanto a OpenAI-compatible via detecção de `.well-known/serviceinfo`.
- Tem configuração por YAML (`bridgeData.yaml`) com uma WebUI para editar.
- Reporta corretamente o `bridge_agent` para o Horde identificar a origem do worker.
- Trata as nuances de kudos, prioridade, modelo whitelist, e soft prompts.

**Pontos negativos:**
- O codebase tem acoplamento forte entre os três tipos de worker. Quem quer só texto ainda precisa instalar dependências de imagem (ou fazer uma instalação parcial com `--scribe`).
- A concorrência é limitada: o campo `max_threads` no pop payload diz ao Horde quantos jobs o worker pode receber, mas a execução real é essencialmente serial — um job de cada vez por processo.
- Não há circuit breaker: se o backend cai no meio de uma geração, o worker pode travar ou perder kudos por timeout.
- A instalação via `update-runtime.sh` baixa um runtime Python inteiro, o que é frágil e difícil de reproduzir.
- Não há suporte nativo a Docker para texto (só para imagem no reGen).
- O tratamento de erros no submit é básico — se o Horde retorna 404 (job expirou), o worker não distingue isso de um erro real.

### 2.2. KoboldCpp Built-in Worker

O KoboldCpp, mantido por LostRuins, tem um worker Horde embutido ativado via `--hordeconfig`. Isso permite que qualquer instância do KoboldCpp participe do Horde sem software adicional.

**Pontos positivos:**
- Zero setup: basta adicionar flags no launch do KoboldCpp.
- Mantido pelo mesmo desenvolvedor do KoboldCpp, então a compatibilidade é total.
- Funciona em Windows, Linux e macOS.

**Pontos negativos:**
- Lock-in completo: só funciona com KoboldCpp. Se você usa Aphrodite, TabbyAPI, ou llama.cpp server nativo, não serve.
- Single-thread: processa um job por vez. Não há como configurar concorrência.
- Controle limitado: os parâmetros de worker (filtros, prioridade, blacklist) são mínimos.
- Não há logs estruturados, métricas, ou qualquer forma de observabilidade.
- Não há graceful shutdown — se você mata o processo durante uma geração, o job é perdido.

### 2.3. horde_sdk (Haidra)

A organização Haidra mantém um SDK Python (`horde-sdk`) com tipos Pydantic, clientes async/sync, e mapeamento de todos os endpoints da API.

**Pontos positivos:**
- Tipos bem definidos para toda a API do Horde.
- Validação rigorosa dos payloads com Pydantic.
- Documentação razoável.

**Pontos negativos:**
- É um SDK, não um worker. Toda a lógica de polling, concorrência, e comunicação com backend teria que ser construída por cima.
- Dependência pesada para um worker simples: Pydantic v2, multidict, e todo o ecossistema do SDK.
- Over-engineering: para um scribe worker, 90% do SDK é irrelevante (modelos de imagem, alchemy, ratings, etc).

### 2.4. Workers DIY da comunidade

Existem scripts caseiros que circulam no Discord do KoboldAI e em forks do GitHub. Geralmente são 100-200 linhas de Python fazendo pop/submit manualmente.

**Pontos positivos:**
- Simples e fáceis de entender.
- Total controle sobre o comportamento.

**Pontos negativos:**
- Sem manutenção: quando a API do Horde muda, quebram.
- Sem cobertura de parâmetros: ignoram a maioria dos sampler params.
- Sem tratamento de erros: qualquer exceção mata o loop.
- Sem concorrência.

### 2.5. Como nosso projeto é melhor

O diferencial central é a combinação de quatro propriedades que nenhuma solução existente entrega simultaneamente:

1. **Multi-backend real**: um único binário que fala com qualquer backend via auto-detecção.
2. **Concorrência genuína**: N coroutines async fazendo pop/generate/submit em paralelo contra o mesmo backend.
3. **Leveza radical**: apenas `aiohttp` e `pyyaml` como dependências — sem PyTorch, sem Pydantic, sem ComfyUI.
4. **Deploy replicável**: mesmo config YAML funciona em qualquer máquina, com override por env vars para personalizar worker_name e backend_url.

---

## 3. Análise Crítica do Rascunho Atual

O rascunho de código que existe no repositório tem a estrutura certa mas contém problemas significativos que precisam ser corrigidos antes de estar pronto para produção.

### 3.1. Problemas na `core/horde_api.py`

**3.1.1. Sessão HTTP compartilhada sem sincronização**
O método `_get_session()` cria uma `aiohttp.ClientSession` lazily, mas múltiplas coroutines podem chamar isso concorrentemente, criando múltiplas sessões. Isso não é um race condition fatal (aiohttp é thread-safe), mas resulta em sessões órfãs. A sessão deveria ser criada no `__init__` ou protegida por um `asyncio.Lock`.

**3.1.2. Pop payload incompleto**
O payload de pop atual não inclui o campo `bridge_agent` como string formatada corretamente. O Horde espera o formato `name:version:url`. Além disso, faltam campos opcionais que afetam a seleção de jobs: `softprompts`, `blacklist`, `allow_unsafe_ip`. O campo `threads` no pop não deveria refletir `max_threads` da config — ele indica ao Horde quantas threads *este pop específico* está pedindo, e deveria ser 1 por chamada de pop (cada thread faz seu próprio pop).

**3.1.3. Parsing do job incompleto**
O response do pop pode conter campos além de `id`, `payload`, `model` e `softprompt`. Campos como `skipped` (que contém razões pelas quais certos jobs foram pulados) são úteis para diagnóstico mas estão sendo jogados num dict genérico `extra`. Mais importante: o campo `id` vindo do pop é o **job ID** (não request ID), e é isso que vai no submit. O código trata isso corretamente mas não tem nenhum comentário explicando a distinção.

**3.1.4. Submit error com metadata incorreta**
O método `submit_error` usa um `gen_metadata` com `type: "censorship"` e `value: "csam"` como placeholder. Isso é extremamente perigoso — se esse código for executado acidentalmente, o worker estaria dizendo ao Horde que detectou material de abuso infantil. O estado correto para reportar um erro de backend é `state: "faulted"` com `gen_metadata` contendo `type: "generation"`, `value: "faulted"`. Além disso, o método define `gen_metadata` localmente mas depois passa um diferente no submit — o código tem dead code.

**3.1.5. Timeout da sessão inadequado**
A sessão do Horde API tem timeout total de 60 segundos. Isso é razoável para pop e submit, mas se alguma chamada futura for mais lenta (por exemplo, durante manutenção do Horde), deveria haver timeouts diferenciados por operação.

### 3.2. Problemas na `backends/adapters.py`

**3.2.1. Sessões HTTP criadas por probe e não fechadas**
Cada função `_probe_*` cria uma `aiohttp.ClientSession` nova dentro de um `async with`, o que é correto em isolamento, mas resulta em 3-4 sessões sendo criadas e destruídas durante a auto-detecção. Isso é ineficiente e pode causar warnings se o event loop for fechado prematuramente. Melhor: criar uma sessão de probe, usá-la em todos os probes, e fechá-la ao final.

**3.2.2. Subclasses vazias sem valor**
`LlamaCppBackend`, `AphroditeBackend` e `TabbyAPIBackend` herdam de `OpenAIBackend` sem nenhum override. Isso é justificado como "futuro specialization" e logging, mas na prática o `name` deveria ser suficiente para distinguir nos logs. O problema real é que esses backends **têm** diferenças: Aphrodite suporta `frequency_penalty` e `presence_penalty` como campos separados; TabbyAPI requer autenticação via header `x-api-key`; llama.cpp suporta `grammar` no body mas os outros podem não suportar. As subclasses existem mas não implementam essas diferenças.

**3.2.3. Sem retry na geração**
Se a requisição de geração falha (timeout, connection reset, 503), o adapter simplesmente levanta uma exceção. Não há retry. Para um backend local, um 503 pode significar "estou processando outro request, tente de novo em 1s" — especialmente relevante quando há concorrência. Deveria haver pelo menos 1-2 retries com backoff curto.

**3.2.4. Sem validação do response**
O adapter OpenAI assume que o response tem `choices[0].text`, mas um backend mal-configurado pode retornar `choices[0].message.content` (formato chat) ou até um JSON malformado. Não há validação defensiva.

**3.2.5. Model name no body OpenAI**
O mapper OpenAI envia `model: model_name` no body, onde `model_name` vem do Horde (ex: `koboldcpp/Llama-3.1-8B-Instruct`). Porém, o modelo já está carregado no backend — muitos backends ignoram esse campo ou falham se o nome não bater. Para llama.cpp server, o campo `model` pode ser qualquer string; para Aphrodite/TabbyAPI, ele precisa corresponder ao modelo carregado. Isso deveria ser configurável: usar o nome do Horde, um nome fixo da config, ou omitir.

### 3.3. Problemas na `core/params.py`

**3.3.1. Mapeamento OpenAI incompleto para Aphrodite**
Aphrodite Engine é o backend mais capaz em termos de samplers. Ela suporta `frequency_penalty`, `presence_penalty`, `repetition_penalty`, `length_penalty`, `no_repeat_ngram_size`, `early_stopping`, e muitos outros que o mapper atual não mapeia. O mapper trata todos os backends OpenAI igualmente, quando deveria ter um branch para Aphrodite com cobertura expandida.

**3.3.2. sampler_order ignorado para OpenAI**
O Horde envia `sampler_order` (uma lista indicando a ordem de aplicação dos samplers). O KoboldCpp respeita isso nativamente, mas backends OpenAI não têm um equivalente direto. O mapper simplesmente ignora esse campo para OpenAI, o que é correto do ponto de vista de API mas resulta em geração diferente. Deveria ao menos logar um warning quando `sampler_order` é ignorado.

**3.3.3. Flags de formatação não tratadas**
Os campos `frmtadsnsp`, `frmtrmblln`, `frmtrmspch`, `frmttriminc` são flags de pós-processamento do texto gerado (adicionar espaço, remover linhas em branco, remover caracteres especiais, trim incompleto). O KoboldCpp aplica isso internamente, mas backends OpenAI não fazem isso. O worker deveria aplicar essas transformações no texto **após** receber a resposta do backend, caso o backend não as suporte nativamente. Isso está completamente ausente.

**3.3.4. `rep_pen` ≠ `frequency_penalty`**
O comentário no código diz que `rep_pen` é mapeado para `frequency_penalty` como "approximate mapping", mas na verdade `repetition_penalty` é um campo separado suportado tanto por llama.cpp quanto por Aphrodite. O mapper envia `repetition_penalty` (correto) mas o comentário é enganoso. Mais importante: `rep_pen_range` e `rep_pen_slope` não existem na API OpenAI padrão mas são suportados por Aphrodite como extensions. O mapper os envia como `repetition_penalty_range`, que é correto para Aphrodite mas será ignorado silenciosamente por llama.cpp e TabbyAPI.

### 3.4. Problemas na `worker.py`

**3.4.1. Todas as threads popam do mesmo HordeAPI**
Cada `WorkerThread` recebe a mesma instância de `HordeAPI`, o que significa que todas compartilham a mesma `aiohttp.ClientSession`. Isso é intencional (aiohttp sessions são async-safe), mas o pop payload de cada thread deveria indicar `threads: 1` (esta thread pede 1 job), não `threads: max_threads`. Do jeito atual, cada thread diz ao Horde que tem N threads, o que pode confundir o load balancing do Horde.

**3.4.2. Estimativa de tokens ingênua**
`token_estimate = len(text.split())` é uma estimativa muito imprecisa. O Horde calcula kudos com base em tokens reais (chars / 4 ou max_tokens, o que for menor, conforme o CHANGELOG). O worker deveria reportar uma estimativa melhor: `len(text) / 4` é mais alinhada com o cálculo do Horde, ou melhor ainda, usar a contagem de tokens retornada pelo backend (a API OpenAI retorna `usage.completion_tokens`).

**3.4.3. Sem respeito a `max_length` do job**
O `_process_job` passa `self.config.worker.max_length` como max_length para o backend, mas o job pode ter um `max_length` menor (definido pelo usuário que fez o request). O correto é usar `min(job.params.get("max_length", config_max), config_max)`.

**3.4.4. Sem timeout por job**
Se o backend travar numa geração infinita (modelo em loop), a thread fica bloqueada para sempre. Deveria haver um `asyncio.wait_for` com timeout configurável ao redor da chamada `backend.generate()`.

**3.4.5. Sem backoff diferenciado entre "sem jobs" e "erro"**
O backoff é aplicado tanto quando não há jobs disponíveis (normal) quanto quando há um erro inesperado. O delay deveria ser mais agressivo para erros (indicando possível problema sistêmico) e mais brando para fila vazia (situação normal).

### 3.5. Ausência de `main.py`

O rascunho não tem um entrypoint. Falta o orquestrador que:
- Carrega a configuração
- Configura logging
- Detecta o backend
- Faz health check inicial
- Lança as N threads
- Trata sinais (SIGINT, SIGTERM) para graceful shutdown
- Monitora a saúde do backend e pausa threads se necessário
- Exibe um banner inicial com informações do worker

### 3.6. Ausência de tratamento de formatação pós-geração

As flags `frmtadsnsp`, `frmtrmblln`, `frmtrmspch`, `frmttriminc` são responsabilidades do worker quando o backend não as trata. Isso é uma parte não-trivial da compatibilidade com o Horde e está totalmente ausente. Precisa de um módulo dedicado ou ao menos funções no params.py.

### 3.7. Ausência de modelo de `softprompts`

O Horde pode enviar um campo `softprompt` indicando que o worker deve usar um soft prompt específico. Isso é raramente usado hoje, mas um worker compliant deveria ao menos reconhecer o campo e logar um warning se não puder atendê-lo.

---

## 4. Arquitetura Alvo

```
                          ┌──────────────────────┐
                          │    AI Horde API       │
                          │  aihorde.net/api/v2   │
                          └───────┬──────┬────────┘
                                  │      ▲
                            pop   │      │  submit
                                  ▼      │
┌─────────────────────────────────────────────────────────────┐
│                      Orchestrator (main.py)                  │
│                                                              │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐                 │
│   │ Thread 0 │  │ Thread 1 │  │ Thread N │  asyncio tasks   │
│   └────┬─────┘  └────┬─────┘  └────┬─────┘                 │
│        │              │              │                        │
│        ▼              ▼              ▼                        │
│   ┌─────────────────────────────────────┐                    │
│   │         HordeAPI (shared)            │                    │
│   │   - pop_job() por thread             │                    │
│   │   - submit_job() por thread          │                    │
│   │   - sessão aiohttp compartilhada     │                    │
│   └─────────────────────────────────────┘                    │
│                                                              │
│   ┌─────────────────────────────────────┐                    │
│   │     BackendAdapter (shared)          │                    │
│   │   - generate() é concurrency-safe    │                    │
│   │   - health_check() periódico         │                    │
│   └──────────────┬──────────────────────┘                    │
│                  │                                            │
│   ┌──────────────┴──────────────────────┐                    │
│   │        ParameterMapper               │                    │
│   │   - horde params → backend params    │                    │
│   │   - pós-processamento de texto       │                    │
│   └─────────────────────────────────────┘                    │
│                                                              │
│   ┌─────────────────────────────────────┐                    │
│   │     HealthMonitor (background task)  │                    │
│   │   - verifica backend periodicamente  │                    │
│   │   - pausa threads se backend caiu    │                    │
│   │   - verifica heartbeat do Horde      │                    │
│   └─────────────────────────────────────┘                    │
│                                                              │
│   ┌─────────────────────────────────────┐                    │
│   │     WorkerStats (shared, lock-safe)  │                    │
│   │   - jobs, kudos, tokens, erros       │                    │
│   │   - summary para logs periódicos     │                    │
│   └─────────────────────────────────────┘                    │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │   Backend de Inferência│
              │  (externo, já rodando) │
              │                        │
              │  KoboldCpp       :5001 │
              │  llama.cpp server:8080 │
              │  Aphrodite       :2242 │
              │  TabbyAPI         :5000│
              └───────────────────────┘
```

O fluxo principal é:
1. `main.py` inicializa tudo, detecta backend, valida config.
2. N coroutines `WorkerThread.run()` são lançadas como `asyncio.Task`.
3. Cada thread faz `pop_job()` → `backend.generate()` → `submit_job()` independentemente.
4. Um `HealthMonitor` em background verifica o backend e o Horde periodicamente.
5. Sinais do SO (Ctrl+C, SIGTERM) disparam graceful shutdown via `asyncio.Event`.

---

## 5. Estrutura de Diretórios

```
horde-scribe-worker/
├── configs/
│   └── config.example.yaml       # Template de configuração documentado
├── src/
│   ├── __init__.py                # Versão do pacote
│   ├── main.py                    # Entrypoint e orquestrador
│   ├── worker.py                  # WorkerThread + WorkerStats
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py              # Loader de config YAML + env vars
│   │   ├── logger.py              # Setup de logging plain/structured
│   │   ├── horde_api.py           # Cliente async para a API do Horde
│   │   ├── params.py              # Mapeamento de parâmetros Horde → backend
│   │   ├── health.py              # HealthMonitor (backend + horde heartbeat)
│   │   └── filters.py             # Blacklist de palavras, filtro NSFW, validações
│   └── backends/
│       ├── __init__.py
│       └── adapters.py            # Base + KoboldAI + OpenAI + detect_backend()
├── tests/
│   ├── test_config.py
│   ├── test_params.py
│   ├── test_adapters.py
│   ├── test_horde_api.py
│   ├── test_worker.py
│   └── test_filters.py
├── README.md
├── requirements.txt               # aiohttp, pyyaml
├── pyproject.toml                  # Metadata do projeto
├── Dockerfile                      # Deploy containerizado
└── docker-compose.yaml             # Exemplo multi-worker
```

Cada arquivo e módulo tem uma responsabilidade clara e única. Não há dependência circular. A hierarquia de imports é: `main → worker → core/* + backends/*`. Os módulos `core/*` não importam uns dos outros exceto `config` e `logger` que são importados por todos.

---

## 6. Módulo: Configuração (`core/config.py`)

### Responsabilidade

Carregar configuração de um arquivo YAML, sobrepondo com variáveis de ambiente. Produzir um objeto de configuração tipado e imutável (após carregamento).

### Análise do estado atual

O rascunho usa dataclasses mutáveis com `_apply_dict` genérico. Isso funciona mas tem falhas:

- Não valida valores (um `max_threads: -5` seria aceito silenciosamente).
- Não tem valores mínimos/máximos.
- O mapeamento de env vars é manual e repetitivo.
- Não logga warnings para configs suspeitas (ex: `max_length` maior que `max_context_length`).

### O que deve ser feito

- Manter dataclasses (sem Pydantic, para manter leveza).
- Adicionar um método `validate()` chamado após o carregamento que verifica invariantes: `max_length < max_context_length`, `max_threads >= 1`, `api_key` não está vazio ou é o anon key (warn), `backend.url` é uma URL válida.
- O env var override deve suportar listas (para `models_to_serve` e `priority_usernames`) via separação por vírgula. Isso já existe mas está fora do loop principal de override.
- Adicionar um `__post_init__` que normaliza URLs (strip trailing slash) e uppercases o log level.
- Adicionar um método `to_display_dict()` que retorna a config para exibição no banner de startup, mascarando o API key (ex: `Tn3x...k9Zf`).

---

## 7. Módulo: Logger (`core/logger.py`)

### Responsabilidade

Configurar logging global com dois modos: plain (humano) e structured (JSON one-liner para ingestão em ferramentas como Loki/Grafana).

### Análise do estado atual

O rascunho está razoável. Pontos de melhoria:

- O `StructuredFormatter` tenta acessar atributos extras (`thread_id`, `job_id`, etc.) via `getattr`, mas eles nunca são passados via `LoggerAdapter` ou `extra`. Ou se usa `LoggerAdapter` consistentemente, ou se remove isso.
- Falta um mecanismo de log com contexto (ex: `log.info("...", extra={"job_id": "abc"})`). A solução mais limpa é usar `logging.LoggerAdapter` com um dict de contexto que cada `WorkerThread` mantém.
- Os nomes dos loggers (`horde.thread.0`, `horde.horde_api`, etc.) estão ok mas deveriam ser documentados para facilitar filtragem.

### O que deve ser feito

- Manter os dois formatters.
- Criar uma factory `get_thread_logger(thread_id)` que retorna um `LoggerAdapter` com `thread_id` no extra.
- No `PlainFormatter`, incluir o thread_id se presente: `10:23:45 [INFO   ] horde.thread.2       │ Job abc123: generated 512 chars`.
- Silenciar `aiohttp.access` além de `aiohttp` (caso alguém ative debug).

---

## 8. Módulo: Horde API Client (`core/horde_api.py`)

### Responsabilidade

Comunicação exclusiva com a API do AI Horde. Três operações: pop (pedir job), submit (devolver resultado), heartbeat (verificar se o Horde está vivo).

### Análise do estado atual

Ver seção 3.1 para problemas detalhados. Resumo:

- Sessão lazy sem lock → race condition benigno mas sujo.
- Pop payload com `threads: max_threads` errado.
- Submit error com metadata perigosa (csam placeholder).
- Parsing incompleto do response.

### O que deve ser feito

**Sessão:** Criar a `aiohttp.ClientSession` uma vez no `async def start()` (ou num `__aenter__`). Nunca criar lazily. Fechar no `async def close()`.

**Pop payload:** Cada chamada de pop deve enviar `threads: 1`. O campo `max_threads` da config é usado apenas para determinar quantas coroutines lançar. O payload deve incluir:
```
{
  "name": worker_name,
  "models": models_to_serve,
  "max_length": max_length,
  "max_context_length": max_context_length,
  "priority_usernames": [...],
  "nsfw": true/false,
  "require_upfront_kudos": true/false,
  "threads": 1,
  "bridge_agent": "horde-scribe-worker:0.1.0:https://github.com/...",
  "blacklist": [...],
}
```

**Response parsing:** O response do pop tem esta estrutura (quando há um job):
```json
{
  "payload": {
    "prompt": "...",
    "n": 1,
    "max_context_length": 4096,
    "max_length": 256,
    "temperature": 0.7,
    "top_p": 0.9,
    ... (todos os sampler params)
  },
  "id": "job-uuid",
  "skipped": { ... },
  "softprompt": null,
  "model": "koboldcpp/Llama-3.1-8B-Instruct"
}
```
Quando não há job, o response tem `id: null` ou é um dict vazio. O campo `skipped` contém razões como `{"max_context_length": 3, "models": 5}` — quantos jobs foram pulados por cada razão. Isso é útil para diagnóstico e deveria ser logado em nível DEBUG.

**Submit payload:**
```json
{
  "id": "job-uuid",
  "generation": "texto gerado",
  "state": "ok",
  "seed": 0,
  "gen_metadata": []
}
```
O `state` pode ser `"ok"`, `"faulted"`, ou `"censored"`. Para erros de backend, usar `state: "faulted"` com `gen_metadata: [{"type": "generation", "value": "faulted", "ref": "error message"}]`.

**Nunca** usar `type: "censorship"` ou `value: "csam"` como placeholder. Isso é um report de conteúdo ilegal e seria tratado como tal pelo Horde.

**Tratamento de erros no submit:** Diferenciar 404 (job expirou — silencioso) de 400 (payload inválido — erro de programação) de 5xx (Horde fora — retry). Não retratar 404.

---

## 9. Módulo: Parameter Mapper (`core/params.py`)

### Responsabilidade

Traduzir os parâmetros de geração que vêm do Horde (formato KoboldAI) para o formato esperado por cada backend. Também aplicar pós-processamento de formatação no texto gerado.

### Análise do estado atual

Ver seção 3.3 para problemas detalhados.

### O que deve ser feito

**Estrutura interna:** Manter duas funções de mapeamento (`map_to_koboldai`, `map_to_openai`) mas parametrizar a função OpenAI com o nome do backend para ativar extensions específicas.

**Mapeamento KoboldAI:** Está 95% correto. O KoboldCpp aceita praticamente os mesmos nomes de parâmetros do Horde, então a lista de direct mappings é adequada. Adicionar: `sampler_seed` para seeds, que é o nome correto na API do KoboldCpp (já feito, mas confirmar).

**Mapeamento OpenAI:** Precisa de três variantes:

- `map_to_openai_base`: parâmetros suportados por todos (temperature, top_p, max_tokens, stop, seed). Usado para backends genéricos.
- `map_to_openai_llamacpp`: base + `top_k`, `min_p`, `repetition_penalty`, `tfs_z`, `typical_p`, `mirostat_mode/tau/eta`, `grammar`, `dynatemp_range/exponent`, `top_a`, `presence_penalty`, `frequency_penalty`.
- `map_to_openai_aphrodite`: llamacpp + `repetition_penalty_range`, `smoothing_factor`, `smoothing_curve`, `length_penalty`, `no_repeat_ngram_size`.

Na prática, como llama.cpp e Aphrodite aceitam campos extras silenciosamente (ignoram o que não conhecem), pode-se usar um mapper único que envia tudo e cada backend pega o que suporta. Mas isso é arriscado — alguns backends retornam 400 para campos desconhecidos. A solução pragmática é: enviar tudo que é known safe (a maioria dos params), e ter uma config `strict_params: true|false` que, quando true, filtra apenas os params garantidos para aquele backend.

**Pós-processamento de formatação:** Adicionar um módulo ou função `apply_format_flags(text, params) -> str` que implementa:

- `frmttriminc` (trim incomplete): remover a última frase incompleta (que não termina em `.`, `!`, `?`, `"`, ou `\n`).
- `frmtrmblln` (remove blank lines): colapsar múltiplas linhas em branco em uma só.
- `frmtrmspch` (remove special chars): remover caracteres de controle Unicode exceto whitespace normal.
- `frmtadsnsp` (add sentence space): garantir que existe um espaço entre o fim da frase anterior e o início da geração.

Essas transformações devem ser aplicadas **apenas** se o backend não as suportar nativamente. Para KoboldCpp (que as implementa internamente), pular. Para backends OpenAI, aplicar sempre.

---

## 10. Módulo: Backend Adapters (`backends/adapters.py`)

### Responsabilidade

Abstrair a comunicação com o backend de inferência. Cada adapter sabe como fazer health check e enviar um request de geração para seu backend.

### Análise do estado atual

Ver seção 3.2.

### O que deve ser feito

**Classe base `BackendAdapter`:**

- `name: str` — identificador do backend para logs e bridge_agent.
- `api_style: str` — "koboldai" ou "openai".
- `url: str` — URL base do backend.
- `timeout: float` — timeout de geração.
- `supports_format_flags: bool` — se True, as flags frmtXXX são passadas ao backend (KoboldAI). Se False, o worker aplica pós-processamento.
- `async start()` — cria sessão.
- `async close()` — fecha sessão.
- `async health_check() -> bool` — verifica se o backend está vivo.
- `async generate(prompt, params, max_length, model_name) -> GenerationResult` — gera texto.

**GenerationResult:** Ao invés de retornar `str`, retornar um dataclass:
```
@dataclass
class GenerationResult:
    text: str
    token_count: int | None = None   # Se o backend retornar
    seed: int | None = None          # Se o backend retornar
    finish_reason: str | None = None # "stop", "length", etc
```
Isso permite que o worker reporte informações mais precisas ao Horde (token count real, seed usado).

**KoboldAIBackend:**

- Health check via `GET /api/v1/model`. Se retornar 200, o body contém `{"result": "model_name"}`.
- Geração via `POST /api/v1/generate`. Body é o output de `map_to_koboldai()`. Response: `{"results": [{"text": "..."}]}`.
- `supports_format_flags = True`.
- Token count: KoboldCpp não retorna token count na API v1. Estimar como `len(text) / 4`.
- Pode também checar `/api/extra/version` para confirmar que é KoboldCpp e não um KoboldAI original.

**OpenAIBackend:**

- Health check via `GET /health` (llama.cpp) ou `GET /v1/models` (geral).
- Geração via `POST /v1/completions`. Body é o output de `map_to_openai()`. Response: `{"choices": [{"text": "...", "finish_reason": "stop"}], "usage": {"completion_tokens": 42}}`.
- `supports_format_flags = False`.
- Token count: extrair de `response.usage.completion_tokens` se presente.
- **Importante:** usar `/v1/completions` (completions), não `/v1/chat/completions`. O Horde envia prompts crus, não mensagens chat-formatted. Backends que só suportam chat completions (improvável para os nossos alvos, mas possível) não são compatíveis.

**Subclasses específicas:**

- `LlamaCppBackend(OpenAIBackend)`: Override de health_check para usar `/health` que retorna `{"status": "ok"}`. Também suporta `/slots` para ver se há slot disponível.
- `AphroditeBackend(OpenAIBackend)`: Pode precisar de header `Authorization: Bearer TOKEN` se a instância estiver protegida. Adicionar campo `api_key` opcional no adapter.
- `TabbyAPIBackend(OpenAIBackend)`: Usa header `x-api-key` para autenticação. Adicionar campo `api_key` opcional. Health check via `GET /v1/models`.

**Auto-detecção (`detect_backend`):**

Manter a hierarquia de detecção: explícito → serviceinfo → probe. Mas:

1. Usar uma única sessão para todos os probes (criar, usar, fechar).
2. Quando `serviceinfo` retornar um nome desconhecido, tentar probar as APIs antes de defaultar para OpenAI.
3. Logar em nível INFO o resultado da detecção com detalhes: `"Detected: KoboldCpp v1.79 at http://localhost:5001 (KoboldAI API)"`.
4. Se a detecção falhar completamente (backend offline), o worker não deve iniciar. Deve logar um erro claro e sair com código 1.

---

## 11. Módulo: Worker Threads (`worker.py`)

### Responsabilidade

O loop principal de cada thread de trabalho: pop → generate → submit. Também acumula estatísticas.

### Análise do estado atual

Ver seção 3.4.

### O que deve ser feito

**WorkerStats:**

Manter como está, mas adicionar:
- `avg_generation_time: float` — média móvel do tempo de geração.
- `last_job_at: float | None` — timestamp do último job processado.
- Um método `to_dict()` para serialização (útil se futuramente expusermos métricas).

**WorkerThread:**

- Cada thread tem seu próprio `thread_id` e `LoggerAdapter` com contexto.
- O pop deve enviar `threads: 1` (não o max_threads global).
- Ao receber um job, logar: thread_id, job_id (primeiros 12 chars), modelo, max_length pedido, tamanho do prompt.
- Ao gerar, envolver `backend.generate()` em `asyncio.wait_for(timeout=config.resilience.backend_timeout)` para evitar travamentos.
- Após geração, aplicar `apply_format_flags()` se `backend.supports_format_flags` é False.
- Ao submeter, usar o `token_count` do `GenerationResult` se disponível, caso contrário estimar.
- Diferenciar backoff de "sem jobs" (1-30s com crescimento suave) de "erro" (2-60s com crescimento agressivo).
- Se `shutdown` for sinalizado durante geração, completar o job atual antes de parar (graceful).

**Gestão de concorrência:**

Todas as threads compartilham o mesmo `HordeAPI` e `BackendAdapter`. Isso funciona porque:
- `aiohttp.ClientSession` é async-safe para uso concorrente.
- Backends como KoboldCpp e llama.cpp server suportam requisições concorrentes (llama.cpp com `--parallel N`).
- Aphrodite e TabbyAPI são construídos para concorrência.

Porém, se o backend só suporta 1 request por vez (configuração single-slot do llama.cpp), múltiplas threads vão gerar 503s. O HealthMonitor deveria detectar isso e ajustar. Alternativamente, o worker deveria ter um semáforo configurável (`max_concurrent_generations`) que limita quantas chamadas a `generate()` acontecem simultaneamente, independente do número de threads. Isso permite que threads continuem fazendo pop (acumulando jobs na fila local) enquanto esperam um slot de geração.

Decisão: **não implementar fila local na v0.1**. Manter simples: cada thread faz pop → generate → submit sequencialmente. Se o backend retorna 503, a thread faz retry com backoff curto. Fila local é scope creep para a primeira versão.

---

## 12. Módulo: Orchestrator / Main (`main.py`)

### Responsabilidade

Entrypoint da aplicação. Inicializa todos os componentes, lança threads, gerencia lifecycle.

### O que deve ser feito

**Fluxo de startup:**

1. Carregar config (`load_config()`). Se o arquivo não existir, logar erro e sair.
2. Validar config (`config.validate()`). Se inválida, logar erros e sair.
3. Configurar logging (`setup_logging()`).
4. Exibir banner:
   ```
   ╔══════════════════════════════════════════════════╗
   ║  Horde Scribe Worker v0.1.0                      ║
   ║  Worker: MyScribeWorker                           ║
   ║  Backend: http://localhost:5001                   ║
   ║  Models: koboldcpp/Llama-3.1-8B-Instruct         ║
   ║  Threads: 3                                       ║
   ║  Max Context: 8192 | Max Length: 512              ║
   ╚══════════════════════════════════════════════════╝
   ```
5. Detectar backend (`detect_backend()`). Se falhar, logar erro e sair.
6. Health check inicial do backend. Se falhar, logar e sair.
7. Health check do Horde (heartbeat). Se falhar, logar warning mas continuar (Horde pode estar temporariamente fora).
8. Criar `HordeAPI`, `WorkerStats`, `shutdown_event`.
9. Lançar `HealthMonitor` como task em background.
10. Lançar N `WorkerThread.run()` como tasks.
11. Registrar handler para SIGINT/SIGTERM que seta `shutdown_event`.
12. Esperar todas as tasks terminarem.
13. Cleanup: fechar sessões, logar resumo final.

**Graceful shutdown:**

Quando `shutdown_event` é setado:
1. Cada `WorkerThread` completa o job atual (se houver) e para.
2. O `HealthMonitor` para.
3. O main espera todas as tasks com um timeout de 60 segundos.
4. Se alguma task não terminar, cancela forçadamente.
5. Fecha `HordeAPI` e `BackendAdapter`.
6. Loga resumo final: `"Shutdown complete. 47 jobs, 1234.5 kudos earned in 3.2 hours"`.

**Sinais:**

```python
loop = asyncio.get_event_loop()
for sig in (signal.SIGINT, signal.SIGTERM):
    loop.add_signal_handler(sig, shutdown_event.set)
```

No Windows, `add_signal_handler` não funciona. Fallback: capturar `KeyboardInterrupt` no bloco principal.

---

## 13. Módulo: Health Monitor (`core/health.py`)

### Responsabilidade

Monitorar em background a saúde do backend e do Horde. Pausar/retomar threads conforme necessário.

### O que deve ser feito

Uma coroutine que roda em loop:

1. A cada `backend_health_interval` segundos, chamar `backend.health_check()`.
2. Se o backend estiver down, logar warning e setar um `backend_healthy: asyncio.Event` como cleared. As threads verificam esse event antes de chamar `generate()` — se cleared, esperam.
3. Se o backend voltar, setar o event e logar.
4. A cada 5 minutos, chamar `horde.check_heartbeat()`. Se falhar, logar warning mas não pausar (o pop vai falhar naturalmente e backoff).
5. A cada 10 minutos, logar um summary das stats.

Isso é o pattern de circuit breaker simplificado: se o backend cai, as threads param de tentar gerar (evitando spam de erros) e voltam automaticamente quando ele retorna.

---

## 14. Módulo: Blacklist e Filtros (`core/filters.py`)

### Responsabilidade

Filtrar jobs com base em blacklist de palavras, política NSFW, e outras validações.

### O que deve ser feito

Uma função `should_skip_job(job, config) -> str | None` que retorna `None` se o job é ok, ou uma string com o motivo do skip.

Verificações:
1. Se `config.worker.blacklist` contém palavras que aparecem no prompt → skip.
2. Se o job pede mais `max_length` do que o worker suporta → skip (deveria ser filtrado no pop, mas defesa em profundidade).
3. Se o job pede mais `max_context_length` do que suportado → skip.

Se um job é skipado, o worker faz submit com `state: "faulted"` e uma mensagem informativa? **Não** — o worker simplesmente não deveria ter recebido o job. Se o Horde enviou um job que viola as constraints anunciadas no pop, é um bug do Horde. O worker deveria logar um warning e descartar o job sem submeter nada (o Horde vai timeout e reatribuir).

Na prática, o filtering mais importante acontece no pop: os campos `models`, `max_length`, `max_context_length`, `nsfw`, e `blacklist` no payload do pop já dizem ao Horde o que o worker aceita. O filtro local é apenas defesa em profundidade.

---

## 15. Concorrência e Modelo de Threading

O worker usa `asyncio` para concorrência. Não há OS threads reais — tudo roda num único thread do Python com coroutines cooperativas.

**Por que asyncio e não threads?**

- As operações são overwhelmingly I/O-bound (HTTP requests para Horde e backend).
- asyncio evita os problemas de sincronização de threading real.
- `aiohttp` é nativamente async.
- O overhead de coroutines é mínimo vs threads.

**Modelo mental:**

Imagine N coroutines rodando em paralelo:

```
Thread 0: pop ──── generate ──────── submit ── pop ── ...
Thread 1: pop ── generate ──── submit ── pop ── generate ── ...
Thread 2: pop ────── generate ────────── submit ── pop ── ...
```

Como as operações são I/O-bound, enquanto a Thread 0 espera o backend responder, a Thread 1 pode estar fazendo pop, e a Thread 2 pode estar submetendo. O event loop multiplexa isso eficientemente.

**Quantas threads usar?**

- 1 thread: adequado para backends lentos ou single-slot.
- 2-3 threads: bom para KoboldCpp com GGUF em GPU média.
- 4-6 threads: bom para Aphrodite/vLLM com batching.
- Mais que 6: raramente vale a pena, pois o backend é o bottleneck.

A regra prática: configure `max_threads` igual ao número de slots paralelos que seu backend suporta (ex: `--parallel 4` no llama.cpp server).

---

## 16. Resiliência e Tratamento de Falhas

### Falhas do backend

| Cenário | Comportamento |
|---|---|
| Backend offline no startup | Worker não inicia. Log de erro claro. |
| Backend cai durante operação | HealthMonitor detecta, pausa threads. Retoma quando voltar. |
| Geração timeout | `asyncio.wait_for` levanta `TimeoutError`. Job é reportado como faulted. |
| Backend retorna 503 | Retry com backoff curto (1-3s). Se persistir, tratar como down. |
| Backend retorna response malformado | Log de erro, job faulted, thread continua. |

### Falhas do Horde

| Cenário | Comportamento |
|---|---|
| Pop retorna 403 (auth failed) | Log de ERRO. A thread continua tentando (o operador pode consertar o API key sem reiniciar). |
| Pop retorna 5xx | Backoff exponencial. Thread aguarda e retenta. |
| Pop retorna 429 (rate limited) | Respeitar `Retry-After` header se presente, senão backoff 30s. |
| Submit retorna 404 (job expirou) | Log de warning. Não retentar. Seguir em frente. |
| Submit retorna 5xx | Retry com exponential backoff (até 3 tentativas). |
| Horde heartbeat falha | Log de warning. Continuar operando (pode ser intermitente). |

### Falhas de rede

| Cenário | Comportamento |
|---|---|
| DNS failure | Exceção capturada, backoff. |
| Connection reset | Exceção capturada, backoff. |
| SSL error | Log de erro. Deveria ser raro com aihorde.net. |

### Graceful shutdown

A prioridade é: **nunca perder um job em andamento**. Se o operador pressiona Ctrl+C:

1. O `shutdown_event` é setado.
2. Threads que estão em `pop` ou `sleep` saem imediatamente.
3. Threads que estão em `generate` ou `submit` completam a operação atual.
4. Após completar, a thread sai do loop.
5. O main espera todas as threads com timeout de 60s.
6. Após 60s, qualquer thread restante é cancelada (forçado).

---

## 17. Ciclo de Vida Pop → Generate → Submit

### Detalhamento passo a passo

**1. Pop**

A thread faz `POST /v2/generate/text/pop` com as constraints do worker. O Horde verifica sua fila de requests pendentes e, se houver um job que match as constraints (modelo, contexto, NSFW, etc.), retorna o job. Se não houver, retorna um response com `id: null`.

O payload de pop comunica ao Horde: "Eu sou o worker X, suporto os modelos Y, aceito até Z tokens de contexto, e estou livre para processar 1 job."

**2. Parse do Job**

O response contém o prompt completo (já formatado pelo frontend/requestor), os parâmetros de geração (temperature, samplers, etc.), o nome do modelo, e opcionalmente um softprompt.

O worker extrai o prompt, os parâmetros, e valida se tudo está dentro dos limites anunciados.

**3. Mapeamento de Parâmetros**

Os parâmetros do Horde são convertidos para o formato do backend. Para KoboldCpp, quase 1:1. Para backends OpenAI, exige tradução de nomes e semântica.

**4. Geração**

O worker envia o prompt + parâmetros mapeados para o backend via HTTP. Espera a resposta (que pode levar de 1s a 5 minutos dependendo do modelo e contexto).

**5. Pós-processamento**

Se o backend não suporta as flags de formatação do Horde, o worker aplica as transformações no texto gerado.

**6. Submit**

O worker envia `POST /v2/generate/text/submit` com o job_id, o texto gerado, estado "ok", e opcionalmente seed e gen_metadata.

O Horde responde com o número de kudos ganhos por este job. O cálculo de kudos leva em conta: tamanho do modelo (em parâmetros), quantidade de tokens gerados, e tempo esperado.

**7. Logging**

A thread loga o resultado: job_id, tokens gerados, tempo de geração, kudos ganhos, e o summary acumulado.

---

## 18. Mapa de Parâmetros por Backend

Esta tabela resume quais parâmetros do Horde são suportados por cada backend.

| Parâmetro Horde | KoboldCpp | llama.cpp | Aphrodite | TabbyAPI |
|---|---|---|---|---|
| `temperature` | ✅ direto | ✅ direto | ✅ direto | ✅ direto |
| `top_p` | ✅ direto | ✅ direto | ✅ direto | ✅ direto |
| `top_k` | ✅ direto | ✅ direto | ✅ direto | ✅ direto |
| `top_a` | ✅ direto | ✅ `top_a` | ✅ direto | ⚠️ varia |
| `min_p` | ✅ direto | ✅ direto | ✅ direto | ✅ direto |
| `typical` | ✅ direto | ✅ `typical_p` | ✅ `typical_p` | ✅ `typical_p` |
| `tfs` | ✅ direto | ✅ `tfs_z` | ✅ `tfs_z` | ✅ `tfs_z` |
| `rep_pen` | ✅ direto | ✅ `repetition_penalty` | ✅ `repetition_penalty` | ✅ `repetition_penalty` |
| `rep_pen_range` | ✅ direto | ❌ ignorado | ✅ `repetition_penalty_range` | ⚠️ varia |
| `rep_pen_slope` | ✅ direto | ❌ ignorado | ⚠️ varia | ❌ ignorado |
| `sampler_order` | ✅ direto | ❌ não suportado | ❌ não suportado | ❌ não suportado |
| `stop_sequence` | ✅ `stop_sequence` | ✅ `stop` (list) | ✅ `stop` (list) | ✅ `stop` (list) |
| `max_length` | ✅ direto | ✅ `max_tokens` | ✅ `max_tokens` | ✅ `max_tokens` |
| `max_context_length` | ✅ direto | ❌ (fixo no server) | ❌ (fixo no server) | ❌ (fixo no server) |
| `mirostat` | ✅ direto | ✅ `mirostat_mode` | ✅ `mirostat_mode` | ⚠️ varia |
| `mirostat_tau` | ✅ direto | ✅ direto | ✅ direto | ⚠️ varia |
| `mirostat_eta` | ✅ direto | ✅ direto | ✅ direto | ⚠️ varia |
| `dynatemp_range` | ✅ direto | ✅ direto | ✅ direto | ⚠️ varia |
| `dynatemp_exponent` | ✅ direto | ✅ direto | ✅ direto | ⚠️ varia |
| `smoothing_factor` | ✅ direto | ⚠️ recente | ✅ direto | ❌ ignorado |
| `smoothing_curve` | ✅ direto | ⚠️ recente | ✅ direto | ❌ ignorado |
| `grammar` | ✅ direto | ✅ direto | ❌ diferente | ❌ diferente |
| `seed` | ✅ `sampler_seed` | ✅ `seed` | ✅ `seed` | ✅ `seed` |
| `frmtadsnsp` | ✅ interno | ❌ → pós-proc | ❌ → pós-proc | ❌ → pós-proc |
| `frmtrmblln` | ✅ interno | ❌ → pós-proc | ❌ → pós-proc | ❌ → pós-proc |
| `frmtrmspch` | ✅ interno | ❌ → pós-proc | ❌ → pós-proc | ❌ → pós-proc |
| `frmttriminc` | ✅ interno | ❌ → pós-proc | ❌ → pós-proc | ❌ → pós-proc |
| `use_default_badwordsids` | ✅ direto | ❌ não suportado | ❌ não suportado | ❌ não suportado |

Legenda: ✅ = suportado, ❌ = não suportado, ⚠️ = suporte parcial ou variável por versão, "→ pós-proc" = worker aplica.

**Nota sobre `max_context_length`:** No KoboldCpp, o worker pode pedir um max_context_length menor que o configurado no backend. Em backends OpenAI, o context é fixo no server e não há como limitá-lo por request. O worker deve anunciar no pop o `max_context_length` que o backend suporta, e confiar que o Horde vai respeitar.

**Nota sobre `sampler_order`:** Esse é o parâmetro mais problemático. Ele determina a ordem de aplicação dos samplers (ex: temperatura primeiro, depois top_p, depois top_k). O KoboldCpp respeita isso, mas nenhum backend OpenAI tem equivalente. O resultado é que gerações no KoboldCpp podem diferir de gerações no llama.cpp mesmo com os mesmos parâmetros. Isso é uma limitação conhecida e não tem solução no nível do worker.

---

## 19. Deploy Multi-Máquina

### Cenário: 3 máquinas, backends diferentes

```
┌─────────────────────────────────┐
│ Máquina A: Desktop RTX 4090    │
│ Backend: KoboldCpp :5001        │
│ Modelo: Llama-3.1-8B-Instruct  │
│ Worker: Home-4090 (3 threads)  │
└─────────────────────────────────┘

┌─────────────────────────────────┐
│ Máquina B: Server 2x A6000     │
│ Backend: Aphrodite :2242        │
│ Modelo: Llama-3.1-70B-Instruct │
│ Worker: Server-A6000 (6 threads)│
└─────────────────────────────────┘

┌─────────────────────────────────┐
│ Máquina C: Laptop com 3060     │
│ Backend: llama.cpp server :8080 │
│ Modelo: Mistral-7B-Instruct    │
│ Worker: Laptop-3060 (1 thread) │
└─────────────────────────────────┘
```

### Como deployar

**Opção 1: Config YAML base + env vars**

Colocar um `config.yaml` idêntico em todas as máquinas (via git, rsync, ou NFS), e personalizar via env vars:

```bash
# Máquina A
HORDE_WORKER_NAME="Home-4090" \
HORDE_BACKEND_URL="http://localhost:5001" \
HORDE_MAX_THREADS=3 \
HORDE_MODELS_TO_SERVE="koboldcpp/Meta-Llama-3.1-8B-Instruct" \
python -m src.main
```

**Opção 2: Docker Compose**

```yaml
services:
  worker:
    image: horde-scribe-worker:latest
    environment:
      HORDE_API_KEY: "${HORDE_API_KEY}"
      HORDE_WORKER_NAME: "${HOSTNAME}-worker"
      HORDE_BACKEND_URL: "http://host.docker.internal:5001"
      HORDE_MAX_THREADS: "3"
    restart: unless-stopped
```

**Opção 3: Systemd service**

```ini
[Unit]
Description=Horde Scribe Worker
After=network.target

[Service]
Type=simple
User=horde
WorkingDirectory=/opt/horde-scribe-worker
Environment=HORDE_WORKER_NAME=Home-4090
Environment=HORDE_BACKEND_URL=http://localhost:5001
ExecStart=/usr/bin/python3 -m src.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Considerações de nomeação

O Horde exige que `worker_name` seja único em toda a rede. Recomendação: usar `{hostname}-{backend}` como padrão, por exemplo `desktop-koboldcpp`, `server-aphrodite`.

Cada worker/nome é registrado independentemente no Horde e ganha kudos separadamente, mas todos para a mesma API key/conta.

---

## 20. Testes

### Estratégia

Testes unitários com mocks para HTTP (usando `aioresponses` ou mocks manuais de `aiohttp`). Nenhum teste de integração com o Horde real (usaria kudos e dependeria de backend online).

### Testes por módulo

**`test_config.py`:**
- Carrega config de arquivo YAML.
- Override por env vars.
- Validação de limites (max_threads >= 1, etc).
- Config ausente gera defaults.

**`test_params.py`:**
- Map KoboldAI: verifica que todos os params do Horde aparecem no body.
- Map OpenAI: verifica tradução de nomes (rep_pen → repetition_penalty, typical → typical_p, etc).
- Params None/ausentes não aparecem no body.
- `apply_format_flags`: testa cada flag individualmente.

**`test_adapters.py`:**
- Mock de serviceinfo retornando KoboldCpp → instancia KoboldAIBackend.
- Mock de serviceinfo retornando Aphrodite → instancia AphroditeBackend.
- Sem serviceinfo + /health com status ok → LlamaCppBackend.
- Sem serviceinfo + /api/v1/model ok → KoboldAIBackend.
- Geração retorna texto correto de cada adapter.
- Geração com status != 200 levanta RuntimeError.

**`test_horde_api.py`:**
- Pop com job disponível → retorna HordeJob.
- Pop sem job (id null) → retorna None.
- Pop com 403 → retorna None, loga.
- Submit com 200 → retorna kudos.
- Submit com 404 → retorna None, sem retry.
- Submit com 500 → retenta N vezes.

**`test_worker.py`:**
- WorkerThread processa 1 job completo (mock pop → mock generate → mock submit).
- Shutdown durante sleep → thread sai.
- Geração falha → submit_error é chamado.
- Backoff aumenta com pops vazios, reseta com job.

**`test_filters.py`:**
- Job com blacklist word → skip.
- Job dentro dos limites → ok.

---

## 21. Decisões Pendentes e Riscos

### Decisões

1. **Fila local de jobs:** Na v0.1, não teremos fila. Cada thread faz pop-generate-submit sequencialmente. Isso simplifica o código mas significa que enquanto a Thread 0 está gerando (I/O-bound no backend), ela não está popando o próximo job. Se adicionarmos fila no futuro, o pop e o generate rodariam em coroutines separadas.

2. **Streaming:** O Horde atualmente não suporta streaming de texto (o submit é atômico). Quando/se o Horde adicionar streaming, será uma mudança significativa no worker. Por ora, `stream: False` em todos os requests.

3. **Softprompts:** Muito poucos backends e modelos suportam soft prompts hoje. Na v0.1, o worker aceitará jobs com softprompt mas logará um warning de que não está aplicando. Se isso virar problema, implementar na v0.2.

4. **Model name no OpenAI body:** Decisão: enviar o nome do modelo como está no Horde (ex: `koboldcpp/Llama-3.1-8B-Instruct`). Se o backend rejeitar, o operador pode configurar `backend.model_name_override` na config para enviar um nome fixo. Adicionar esse campo à config.

5. **Autenticação de backend:** Adicionar `backend.api_key` opcional na config, enviado como `Authorization: Bearer {key}` para backends OpenAI ou `x-api-key` para TabbyAPI. Se vazio, não enviar.

### Riscos

1. **Mudanças na API do Horde:** A API do Horde evolui (campos novos, deprecações). O worker precisa ser defensivo: ignorar campos desconhecidos, não falhar com campos ausentes.

2. **Rate limiting:** O Horde pode rate-limitar pops se forem muito frequentes. O backoff exponencial mitiga isso, mas se N threads de N máquinas estiverem popando agressivamente com a mesma API key, pode ser um problema. Monitorar.

3. **Contagem de tokens incorreta:** Se o worker reportar tokens muito diferentes do que o Horde espera, os kudos podem ser penalizados. Priorizar usar a contagem do backend (`usage.completion_tokens`) quando disponível.

4. **Concorrência no backend:** Se o operador configura 6 threads mas o backend suporta 1 slot, haverá muitos 503s. O worker vai funcionar (retry), mas será ineficiente. Documentar claramente a relação entre threads e slots do backend.

5. **Segurança dos prompts:** Prompts do Horde podem conter qualquer coisa. O worker processa e envia para o backend sem sanitizar. Isso é intencional (sanitizar quebraria a geração), mas o operador deve estar ciente de que conteúdo arbitrário passa pelo worker.

---

*Fim do documento. Este spec é a referência para a implementação. Qualquer decisão não coberta aqui deve ser resolvida com o princípio de simplicidade: a solução mais simples que funciona corretamente é a preferida.*
