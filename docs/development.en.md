# Development guide

[README](../README.en.md) · [中文](development.md)

## Requirements

- Python 3.12+ and uv, using the committed `uv.lock`.
- Node.js 22.12+ (or the compatible range in Vite's installed package) and npm, using `web/package-lock.json`.
- FFmpeg and ffprobe on the backend PATH for video probing, splitting, composition, continuity frames and enhancement.
- SQLite by default, or a configured PostgreSQL database. Model API access is configured separately.

## Run locally

Start the backend from the repository root:

```sh
uv sync --dev
make dev PORT=9000
```

In another terminal:

```sh
cd web
npm ci
npm run dev
```

Open [localhost:3000](http://localhost:3000). The frontend proxies `/api` and `/media` to port 9000. Retain `uv.lock` and `web/package-lock.json` for reproducible installation.

## Project structure

```text
novelvids/
├── api/                         # HTTP routes under /api
├── controllers/                 # Business orchestration
├── models/                      # Tortoise ORM models
├── schemas/                     # Pydantic validation and response schemas
├── services/
│   ├── ai_task_executor.py      # Background AI tasks
│   ├── extraction/              # Asset extraction
│   ├── storyboard/              # Storyboard generation
│   ├── reference/               # Reference image generation
│   ├── remake/                  # Uploads, analysis, progress and persistence
│   ├── creation_agent/          # Tools, scope, memory, context and changes
│   ├── billing/                 # Usage, pricing and summaries
│   ├── image_generation/        # Image protocols and capabilities
│   ├── video/                   # Video adapters, composition and continuity
│   ├── oss/                     # Local and OSS storage
│   └── audio_references.py      # Audio upload and trimming
├── prompts/                     # Central prompt templates and pure renderers
├── seeds/                       # Initial audio and digital human data
├── scripts/                     # Maintenance tools
├── test/                        # Backend tests
├── web/
│   ├── src/
│   │   ├── pages/               # Application pages
│   │   ├── features/workbench/  # Infinite canvas
│   │   ├── features/creation-agent/ # Assistant UI
│   │   ├── components/          # Shared components
│   │   ├── i18n/                # Language state and translation catalog
│   │   ├── shared/              # Shared state and utilities
│   │   ├── api.ts               # API client
│   │   └── router.ts            # Routes
│   └── public/                  # Static assets
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── pyproject.toml
├── README.md                    # Chinese documentation
└── README.en.md                 # English documentation
```

## Technology stack

| Backend | Purpose |
| --- | --- |
| FastAPI / Uvicorn | Asynchronous API and ASGI server |
| Tortoise ORM / asyncpg / aiosqlite | Database models and drivers |
| Pydantic | Validation and serialization |
| Pydantic AI / AG-UI | Assistant tool loop, typed output and streaming events |
| OpenAI SDK / HTTPX | Model calls and media transport |
| PySceneDetect / FFmpeg | Shot detection, media processing and composition |
| uv / pytest | Dependency management and testing |

| Frontend | Purpose |
| --- | --- |
| Vue 3 / TypeScript / Vite | Application framework, types and build tooling |
| Pinia / Vue Router | State and navigation |
| Element Plus / vue-element-plus-x / AG-UI Client | Assistant and settings components |
| Vue Flow | Infinite canvas |
| vue-i18n | Chinese and English interface text |
| Vitest | Unit and component tests |

## Tests

From the repository root:

```sh
# Backend suite, including coverage reporting
AUTH_ENABLED=false uv run pytest

# Targeted backend tests
uv run pytest test/test_services/test_storyboard_handler.py -q
```

Frontend checks:

```sh
cd web
npm run test
npm run typecheck
npm run build
```

Authentication-specific tests target deployments with authentication enabled. Real-model tests require local provider configuration and can incur charges. Keep `test/.test.env` private. Automated request-contract tests do not establish actual voice fidelity, accent or lip synchronization.

## Architecture and extensions

- `api → controllers → services/models`: validate requests, orchestrate business operations, call providers and persist data.
- `prompts/skills/`: one creative rule pack. See [skill development](agent-skills-workflow.en.md); do not add a second prompt pipeline in an adapter.
- `services/image_generation/` and `services/video/`: capability contracts and provider adapters.
- `services/video_enhancement/`: preparation, provider submission, collection and settlement.
- `web/src/features/workbench/`: canvas interaction and node views; storyboard and canvas use the same project objects.

Run the permission suite separately with `AUTH_ENABLED=true uv run pytest test/test_auth -q --no-cov`. Real model tests require `test/.test.env` and a reviewed cost budget; passing mocks does not establish provider output quality. Never use production credentials implicitly to run the ordinary suite.

Before a pull request, run relevant regression tests and `git diff --check`. Frontend changes also require typecheck, build and dark/light validation. Keep dependencies pinned unless a dependency change is part of the agreed scope.

See [contributing](../CONTRIBUTING.md) and [third-party notices](../NOTICE.md).
