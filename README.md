# AI Horde Nexus (Horde Scribe Worker)

A lightweight, highly concurrent, and multi-backend worker for text generation (Scribe) on the [AI Horde](https://aihorde.net/) network. 

Designed as a clean, fast alternative to the monolithic official worker, this project provides the essential "glue" between the AI Horde and your local LLM inference engine.

## 🌟 Key Features

* **Multi-Backend Auto-Detection**: Works out of the box with **KoboldCpp**, **llama.cpp server**, **Aphrodite Engine**, and **TabbyAPI**. The worker automatically probes your backend URL to detect the API format.
* **True Concurrency**: Spin up `N` asynchronous worker threads that independently pop, generate, and submit jobs to fully saturate backends capable of batching (like Aphrodite) or parallel slots (like llama.cpp).
* **Auto-Discovery**: Support for `models_to_serve: ["*"]`. The worker automatically queries your backend to announce the exact loaded model name to the Horde.
* **Resilience & Safety**: Circuit-breaker style health monitoring pauses work if your backend goes offline. Graceful shutdown ensures no in-progress jobs (and kudos) are lost when you press `Ctrl+C`.
* **Lightweight**: Built entirely on `aiohttp` and `pyyaml`. No heavy SDKs, PyTorch, or monolithic ecosystems required. Use `uv` for instant dependency resolution.
* **Docker First**: Ready to deploy across a multi-machine setup with a configurable `docker-compose.yaml`.

## Getting Started

### Prerequisites

Ensure you have a backend (e.g., [KoboldCpp](https://github.com/LostRuins/koboldcpp)) already running.
It's highly recommended to use [uv](https://github.com/astral-sh/uv) to manage Python dependencies.

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/gustrd/ai-horde-nexus.git
   cd ai-horde-nexus
   ```

2. Scaffolding & Dependencies (using `uv`):
   ```bash
   uv sync --frozen
   ```

3. Setup Configuration:
   ```bash
   cp configs/config.example.yaml configs/config.yaml
   ```
   Edit `configs/config.yaml` to include your AI Horde `api_key` and adjust `max_threads` to match the parallel slots your backend supports.

4. Run the Worker:
   ```bash
   uv run python -m src.main
   ```

## Docker Deployment

The worker is designed to be easily deployed across multiple machines using Docker Compose.

1. Review and adjust `docker-compose.yaml` (or pass environmental variables natively):
   ```yaml
   environment:
     - HORDE_API_KEY=your_api_key_here
     - HORDE_WORKER_NAME=Docker-Scribe-Worker
     - HORDE_MAX_THREADS=4
     - HORDE_BACKEND_URL=http://host.docker.internal:5001
   ```

2. Start the container:
   ```bash
   docker compose up -d
   ```

## ⚙️ Configuration Properties

The worker is highly configurable via `configs/config.yaml` or through equivalent Environment Variables (`HORDE_*` prefixed).

| YAML Key | Environment Variable | Default | Description |
|---|---|---|---|
| `horde.api_key` | `HORDE_API_KEY` | `0000...` | API key from aihorde.net (earns Kudos). |
| `worker.name` | `HORDE_WORKER_NAME` | `ScribeWorker` | Distinct name for this worker instance. |
| `worker.max_threads` | `HORDE_MAX_THREADS` | `1` | Number of simultaneous jobs. Align with backend's parallel slots. |
| `worker.max_context_length` | `HORDE_MAX_CONTEXT_LENGTH` | `8192` | Absolute max context limit your worker advertises. |
| `worker.models_to_serve` | `HORDE_MODELS_TO_SERVE` | `*` | Comma-separated list of models. `*` enables auto-discovery. |
| `backend.url` | `HORDE_BACKEND_URL` | `http://localhost:5001` | Your local backend URL. |
| `backend.api_key` | `HORDE_BACKEND_API_KEY` | | Optional Auth Bearer or x-api-key for protected backends. |

## 🛠️ Testing & Development

This project aims for 100% test coverage using `pytest`. Run the suite with:

```bash
uv run pytest
```

## Roadmap & Status

- **Phase 1: DONE.** Complete scaffolding, backend auto-detection, KoboldCpp and llama.cpp integration, threaded polling/submission loop, resilience monitoring, and full unit test coverage.
- **Status Update:** Successfully verified against **KoboldCpp** and **llama.cpp** with multi-threaded execution (2+ threads).
- **Next Phases:** Additional backends, WebUI with stats, etc. Suggestions are welcome!
