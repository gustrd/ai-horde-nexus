# Implementation Checklist for Horde Scribe Worker (v0.1.0)

This checklist follows the architectural specification defined in `SPEC.md`.

## 1. Project Scaffolding
- [x] Set up the project using `uv` for minimal and fast dependency management.
- [x] Create directory structure (`src/`, `configs/`, `tests/`).
- [x] Document dependencies (`aiohttp`, `pyyaml`).
- [x] Create a `Dockerfile` and `docker-compose.yaml` to ensure the project is highly Docker-friendly for multi-machine deploy.

## 2. Configuration (`core/config.py`)
- [x] Implement configuration dataclasses (no Pydantic).
- [x] Add `__post_init__` to normalize URLs and log levels.
- [x] Add `validate()` method to enforce invariants (e.g., `max_length < max_context_length`, `max_threads >= 1`).
- [x] Implement environment variable overrides supporting lists (comma-separated).
- [x] Add `to_display_dict()` to mask API keys for safe logging.
- [x] Add support for `backend.model_name_override` and `backend.api_key`.

## 3. Logging (`core/logger.py`)
- [x] Refactor `StructuredFormatter` and `PlainFormatter`.
- [x] Implement `get_thread_logger(thread_id)` returning a `LoggerAdapter` for thread-specific context.
- [x] Ensure `aiohttp` access logs are silenced by default.

## 4. Horde API Client (`core/horde_api.py`)
- [x] Manage `aiohttp.ClientSession` lifecycle explicitly natively in `start()` / `close()` methods.
- [x] Fix Pop payload: format `bridge_agent` correctly, and send `threads: 1` per thread.
- [x] Safely parse Horde's Pop response, handling `id: null` and logging `skipped` jobs metadata.
- [x] Fix `submit_error()` metadata: remove CSAM placeholder and replace with `state: "faulted"` and metadata type `"generation"`.
- [x] Implement differentiated request timeouts for Pop and Submit operations.
- [x] Add error handling distinguishing 4xx and 5xx.
- [x] Strictly follow Horde API best practices to avoid worker ban (respect `Retry-After`, use distinct worker labels, never misreport metadata).

## 5. Filter & Blacklist (`core/filters.py`)
- [x] Implement `should_skip_job(job, config)`.
- [x] Filter jobs containing words in the user's blacklist.
- [x] Enforce sanity checks on `max_length` and `max_context_length`.

## 6. Parameters Mapping & Processing (`core/params.py`)
- [x] Ensure `map_to_koboldai` handles sampler names correctly (e.g. `sampler_seed`).
- [x] Create specialized mappings for OpenAI backends (`map_to_openai_base`, `map_to_openai_llamacpp`, `map_to_openai_aphrodite`).
- [x] Implement `apply_format_flags()` to handle Horde-specific text flags manually (`frmttriminc`, `frmtrmblln`, `frmtrmspch`, `frmtadsnsp`), applied only if the backend does not support it natively.

## 7. Backend Adapters (`backends/adapters.py`)
- [x] Define `GenerationResult` dataclass (`text`, `token_count`, `seed`, `finish_reason`).
- [x] Write `BackendAdapter` base class structure with properties (`api_style`, `supports_format_flags`, `timeout`, etc).
- [x] Implement `KoboldAIBackend` (support text formatting internally, uses `/api/v1/generate`).
- [x] Implement `OpenAIBackend` and its specific variants (`LlamaCppBackend`, `AphroditeBackend`, `TabbyAPIBackend`) injecting authentication parameters when required.
- [x] Rewrite `detect_backend()` to share a single short-lived `aiohttp` session across all probe attempts.

## 8. Worker Threads & Execution (`worker.py`)
- [x] Enhance `WorkerStats` tracker (`avg_generation_time`, `last_job_at`, `to_dict()`).
- [x] Update `WorkerThread.run()` loop (pop -> generate -> submit) with specific `LoggerAdapter` context.
- [x] Enclose `backend.generate()` inside `asyncio.wait_for()` with a configurable timeout.
- [x] Extract generation `token_count` from `GenerationResult` when available, fallback to length estimate.
- [x] Use `min(job.params.max_length, config_max_length)` dynamically per job.
- [x] Implement separate backoff strategies ("no jobs" vs "error").
- [x] Ensure **Graceful Shutdown**: finish the currently active job before stopping when signal is caught.

## 9. Health Monitoring (`core/health.py`)
- [x] Build background task looping `backend.health_check()`.
- [x] Use `asyncio.Event` to pause worker threads if the backend becomes unavailable.
- [x] Verify Horde API heartbeat asynchronously.
- [x] Periodic logging of runtime statistics (every 10 minutes).

## 10. Orchestrator (`main.py`)
- [x] Sequence startup: load/validate config, setup logging, show banner, map components.
- [x] Start `HordeAPI` and detect backend.
- [x] Initialize `HealthMonitor` task and `WorkerThread` tasks dynamically based on `max_threads`.
- [x] Register `SIGINT`/`SIGTERM` handlers for updating the shutdown event globally.
- [x] Orchestrate graceful shutdown process and print final summary.

## 11. Testing (`tests/`)
- [ ] Ensure 100% feature coverage with proper unit tests across the codebase.
- [x] Write tests for `test_config.py`.
- [x] Write tests for `test_params.py` (including format flags function).
- [ ] Write tests for `test_adapters.py`.
- [x] Write tests for `test_horde_api.py`.
- [ ] Write tests for `test_worker.py`.
- [ ] Write tests for `test_filters.py`.
