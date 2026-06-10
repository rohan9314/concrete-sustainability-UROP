# Concrete Decarbonization Research Agent

Full-stack research tool for evaluating cement and concrete decarbonization technologies. The backend retrieves scientific papers from a **local paper database** configured via `PAPER_RECORDS_PATH`, optionally supplements with internet sources (Tavily), and uses OpenAI to answer configurable research questions.

## Project structure

```
/
├── frontend/          # React + TanStack Start UI
├── backend/           # Python research agent + FastAPI wrapper
│   ├── api.py         # HTTP API
│   ├── paper_records.py  # Local pickle paper retrieval
│   ├── pipeline.py    # Research workflow
│   ├── questions/     # Configurable question sets (JSON)
│   └── outputs/       # Saved research JSON (gitignored)
├── README.md
└── .gitignore
```

## Prerequisites

- Python 3.11+
- Node.js 20+ (or Bun)
- API keys: OpenAI, Tavily (optional supplement)
- Local paper database file (configured via `PAPER_RECORDS_PATH`, gitignored)

## Local paper database

Set the absolute path to your confidential paper database in `backend/.env`:

```
PAPER_RECORDS_PATH=/absolute/path/to/your/paper_database.pkl
```

Pickle files (`*.pkl`) are **gitignored** and must never be committed.

## Backend setup (required)

The frontend cannot load question sets or run research without the backend.

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys and PAPER_RECORDS_PATH
uvicorn api:app --reload --port 8000
```

Keep this running in a separate terminal while using the app.

### CLI (optional)

```bash
cd backend
python main.py "calcium looping" --questions carbon_capture
```

## Frontend setup

From the **repo root** (recommended):

```bash
npm install
cp frontend/.env.example frontend/.env
npm run dev
```

Or from `frontend/` directly:

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

> **Important:** The app that calls the 26-question research API lives in `frontend/`.
> Running `npm run dev` from the repo root now forwards to `frontend/`.
> You must also have the backend running on port 8000.

### API base URL

```
VITE_API_BASE_URL=http://localhost:8000
```

## Retrieval workflow

1. **Local paper database** — scans all ~159k records with multiple targeted queries; keeps top 30 papers
2. **Tavily internet search** — multiple targeted queries for technical, economic, and deployment evidence; keeps top 20 pages
3. **OpenAI extraction** — answers all 26 questions in two focused batches using both source streams

Both retrieval streams run on every research job. Sources are labeled `scientific_paper` or `internet` in the report.

## API contract (research pipeline)

### POST /api/research

```json
{
  "subject": "calcium looping",
  "question_set": "carbon_capture"
}
```

### Completed result shape

```json
{
  "technology": "Calcium Looping",
  "questions_file": "carbon_capture",
  "executive_summary": "...",
  "answers": [],
  "retrieval_summary": {
    "internet_sources_found": 0,
    "scientific_paper_sources_found": 8,
    "local_paper_database_enabled": true
  }
}
```

## Mock evaluation API

For frontend development without OpenAI/Tavily:

- `POST /api/evaluate` — returns mock `TechnologyEvaluation` objects
- `GET /api/evaluations` — list saved evaluations
- `GET /api/evaluations/{id}` — fetch one evaluation
