# Concrete Decarbonization Research Agent

Full-stack research tool for evaluating cement and concrete decarbonization technologies. The backend retrieves internet sources (Tavily), optionally scientific literature (Edison API), and uses OpenAI to answer configurable research questions. The frontend displays structured reports with citations, confidence levels, and executive summaries.

## Project structure

```
/
├── frontend/          # React + TanStack Start UI (Lovable)
├── backend/           # Python research agent + FastAPI wrapper
│   ├── api.py         # HTTP API
│   ├── pipeline.py    # Research workflow
│   ├── questions/     # Configurable question sets (JSON)
│   └── outputs/       # Saved research JSON (gitignored)
├── README.md
└── .gitignore
```

## Prerequisites

- Python 3.11+
- Node.js 20+ (or Bun)
- API keys: OpenAI, Tavily (Edison optional)

## Backend setup

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys
uvicorn api:app --reload --port 8000
```

### CLI (optional)

The original CLI still works:

```bash
cd backend
python main.py "calcium looping" --questions carbon_capture
```

## Frontend setup

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

### API base URL

Set the backend URL in `frontend/.env`:

```
VITE_API_BASE_URL=http://localhost:8000
```

The frontend calls:

- `GET /api/health`
- `GET /api/question-sets`
- `POST /api/research`
- `GET /api/research/{job_id}`

## Local development

1. Start the backend on port 8000
2. Start the frontend (default Vite port 5173)
3. Open the frontend URL and run a research query

CORS is enabled for `http://localhost:5173` and `http://localhost:3000`.

## Question sets

Question sets live in `backend/questions/*.json`. Add or edit questions without changing Python code. The API exposes available sets via `GET /api/question-sets`.

Current sets:

- `evaluation_questions` (default)
- `general_decarbonization`
- `carbon_capture`
- `scm`
- `alternative_cement`

## API contract

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
  "answers": [
    {
      "question": "...",
      "answer": "...",
      "confidence": "Medium",
      "source_type_used": ["internet"],
      "sources": [
        {
          "title": "...",
          "url": "...",
          "source_type": "internet",
          "snippet": "...",
          "full_text": "",
          "metadata": {
            "authors": [],
            "year": "",
            "journal": "",
            "doi": ""
          }
        }
      ]
    }
  ],
  "retrieval_summary": {
    "internet_sources_found": 8,
    "scientific_paper_sources_found": 0,
    "edison_enabled": false
  }
}
```

## Edison API

Edison scientific literature retrieval is optional. If `EDISON_API_KEY` is missing or set to `YOUR_TOKEN_HERE`, the backend continues with internet sources only.
