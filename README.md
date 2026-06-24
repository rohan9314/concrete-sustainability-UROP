# Concrete Decarbonization Research Agent

Full-stack research tool for evaluating cement and concrete decarbonization technologies.

## Architecture

The project is split into two paths:

1. **Offline pipeline** (`pipeline/`) — filters, ranks, extracts, and merges structured technology records from the local paper corpus. Designed for batch processing and parallel batch workers over large corpora.
2. **Web frontend** — reads prepared records from a static technology database (`data/sample_technology_database.json` for development). Live analysis remains available as an experimental option.

The website should **not** process the full corpus live. Offline batch jobs build `data/technology_database.json`, and the frontend displays coverage, confidence, and missing-field indicators from those prepared records.

```
/
├── pipeline/              # Offline stages (load → filter → rank → extract → merge → export)
│   ├── load_corpus.py
│   ├── filter_relevance.py
│   ├── rank_sources.py
│   ├── extract_structured_fields.py
│   ├── merge_records.py
│   ├── export_database.py
│   ├── run_batch.py       # Corpus shard processor for batch workloads
│   └── run_pipeline.py    # Small local end-to-end test
├── data/
│   └── sample_technology_database.json   # Committed sample for frontend dev
├── frontend/              # React + TanStack Start UI
├── backend/               # FastAPI wrapper + live analysis (optional)
└── docs/
    └── batch_worker_example.sh         # Example parallel worker pattern (documentation only)
```

## Prerequisites

- Python 3.11+
- Node.js 20+ (or Bun)
- API keys: OpenAI (pipeline extraction + optional live analysis), Tavily (optional live analysis only)
- Local paper database file (gitignored pickle configured via `PICKLE_PATH`)

## Backend setup

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# Edit .env: TECH_DATABASE_PATH, PICKLE_PATH, API keys as needed
uvicorn api:app --reload --port 8000
```

### API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/technology-database` | List prepared technology records |
| `GET /api/technology-database/search?q=` | Search prepared records |
| `GET /api/technology-database/{record_id}` | Fetch one record |
| `POST /api/research` | Optional experimental live analysis |

## Frontend setup

```bash
npm install
cp frontend/.env.example frontend/.env
npm run dev
```

The default search UI reads prepared database records. Expand **Experimental: Run live analysis** for the slower live extraction path.

## Offline pipeline

### Small local test (no LLM)

```bash
export PICKLE_PATH=/path/to/your/corpus.pkl
python pipeline/run_pipeline.py --start 0 --end 500 --query "cement decarbonization"
```

### Small local test with extraction (uses OpenAI)

```bash
python pipeline/run_pipeline.py --start 0 --end 500 --extract --query "LC3 cement"
```

### CCS abstract screening (cluster-friendly)

Stage 1 screening uses only title + abstract and does **not** require Tavily, tiktoken, FastAPI, or the full backend retrieval stack. On MIT Engaging or other batch clusters, install the lightweight screening requirements:

```bash
python -m pip install --user -r requirements-screening.txt
export PICKLE_PATH=/path/to/your/corpus.pkl
export OPENAI_API_KEY=your_key_here
python pipeline/run_ccs_abstract_screening.py --start 0 --end 10
```

For local development with the full extraction pipeline, use `backend/requirements.txt` instead.

### Corpus shard (batch processing)

```bash
python pipeline/run_batch.py --start 0 --end 10000 --out outputs/batch_0_10000.jsonl
```

With extraction:

```bash
python pipeline/run_batch.py --start 0 --end 100 --extract --technology "carbon capture" --out outputs/batch_0_100.jsonl
```

See `docs/batch_worker_example.sh` for an example parallel worker pattern. Large-scale processing should remain batch/offline — not a dependency of the live website.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PICKLE_PATH` | — | Local paper corpus pickle |
| `TOP_N_SOURCES` | `50` | Ranked papers per shard/query |
| `EXTRACTION_CONCURRENCY` | `4` | Bounded parallel workers |
| `OUTPUT_DIR` | `./outputs` | Shard output directory |
| `TECH_DATABASE_PATH` | `./data/sample_technology_database.json` | Database served to frontend |

## Gitignored assets

Never commit: `.env`, `*.pkl`, `outputs/`, `cache/`, `technology_database.json`, or full generated databases. The committed `data/sample_technology_database.json` is for frontend development only.

## Prepared record schema

Each technology record includes standardized fields such as `technology_category`, `deployment_stage`, `performance_metrics`, quantitative fields, projects, sources, `missing_fields`, `confidence_by_field`, and `coverage_score`. See `pipeline/schema.py` for the canonical definition.
