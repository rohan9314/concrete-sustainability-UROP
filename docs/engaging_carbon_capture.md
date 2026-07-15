# MIT Engaging cluster workflow for carbon capture CSV pipeline

This document describes how to run the full corpus workflow on MIT Engaging using
SLURM array jobs. The design separates **screening**, **retrieval**, **extraction**,
**web search**, and **CSV export** so each stage can scale independently.

## Why the original `run_carbon_capture.py` is not cluster-optimal

`run_carbon_capture.py` is fine for **local smoke tests** on a corpus slice, but it has
limitations at full-corpus scale:

| Issue | Problem on Engaging |
|-------|---------------------|
| Single process | Cannot use SLURM job arrays |
| `top_n` per shard | Each shard keeps its own top 50 — **not** the global top 50 |
| Direct CSV writes | Hard to merge parallel workers |
| Full pickle load per run | ~16s + RAM per worker (acceptable, but needs sharding) |

Use `run_carbon_capture_cluster.py` for production Engaging runs.

## Algorithm (8 stages)

```
Corpus (~159k papers)
        │
        ▼
┌───────────────────────────────────────┐
│ Stage 1: SCREEN (SLURM array)         │  Title+abstract LLM screening per shard
│  → shards/screening/screening_*.jsonl │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│ Stage 2: MERGE-SCREEN (login node)    │  One merged screening file
│  → screening_merged.jsonl             │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│ Stage 3: RETRIEVE (array × 6 methods) │  Methodology-specific ranking per shard
│  → shards/retrieve/{method}/ranked_*  │  No top_n limit at shard level
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│ Stage 4: MERGE-RANK (login node × 6)  │  Global dedupe + top-N per methodology
│  → ranked/{method}_final.jsonl        │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│ Stage 5: EXTRACT (array × 6 methods)  │  Literature LLM extraction batches
│  → shards/extract/{method}/extract_*  │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│ Stage 6: MERGE-EXTRACT (login × 6)    │  Combine literature extraction shards
│  → extractions/{method}_merged.jsonl  │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│ Stage 7: WEB (job × 6 methods)        │  Tavily internet search + web extraction
│  → web/{method}_web.jsonl             │  Seeds follow-ups from literature rows
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│ Stage 8: EXPORT-CSV (login × 6)       │  Merge literature + web → answers CSV
│  → csv/{method}_answers.csv           │
│  → csv/{method}_literature.csv        │
│  → csv/{method}_web.csv               │
└───────────────────────────────────────┘
```

## Setup on Engaging

Default cluster checkout:

```text
REPO_ROOT=/home/rohan931/urop/concrete-sustainability-UROP
scripts  → $REPO_ROOT/scripts/engaging/
outputs  → $REPO_ROOT/outputs/
pickle   → $REPO_ROOT/filtered_records_rohan.pkl
```

```bash
# ── Setup (once) ──────────────────────────────────────────
cd /home/rohan931/urop/concrete-sustainability-UROP
git pull origin main
python -m pip install --user -r requirements-screening.txt

export REPO_ROOT=/home/rohan931/urop/concrete-sustainability-UROP
export PICKLE_PATH=$REPO_ROOT/filtered_records_rohan.pkl
export OPENAI_API_KEY=sk-...          # required for screen / extract / web
export TAVILY_API_KEY=tvly-...        # required for web search
export OUTPUT_DIR=$REPO_ROOT/outputs
export EXTRACTION_CONCURRENCY=4
export TOP_N_SOURCES=50
export WEB_LIMIT=50
export SHARD_SIZE=10000

mkdir -p logs

# Plan shards, then set #SBATCH --array=0-N in scripts to match
python pipeline/run_carbon_capture_cluster.py plan --shard-size 10000
# Example: 159372 records → 16 shards (tasks 0–15)
```

Scripts resolve `REPO_ROOT` from their own location when unset, but exporting
`REPO_ROOT` / `OUTPUT_DIR` / API keys is still recommended (especially for SLURM).

## Run all stages automatically (recommended)

```bash
cd /home/rohan931/urop/concrete-sustainability-UROP
export OPENAI_API_KEY=sk-...
export TAVILY_API_KEY=tvly-...

bash scripts/engaging/run_full_pipeline.sh
```

This submits stages 1–8 as a SLURM dependency chain (`afterok:...`), so you do not
need to run each step by hand. Monitor with `squeue -u $USER`.

Useful options:

```bash
SKIP_SCREEN=1 bash scripts/engaging/run_full_pipeline.sh   # reuse existing screening
SKIP_WEB=1 bash scripts/engaging/run_full_pipeline.sh      # literature-only
START_FROM=5 bash scripts/engaging/run_full_pipeline.sh    # resume at extract
```

## Run stages manually

Scripts live in `/home/rohan931/urop/concrete-sustainability-UROP/scripts/engaging/`.

```bash
cd /home/rohan931/urop/concrete-sustainability-UROP

# ── 1. Screen all papers ──────────────────────────────────
sbatch --export=ALL scripts/engaging/01_screen_array.sh
# wait until array finishes: squeue -u $USER

# ── 2. Merge screening ────────────────────────────────────
bash scripts/engaging/02_merge_screening.sh

# ── 3. Retrieve/rank (all 6 methodologies) ────────────────
bash scripts/engaging/submit_all_retrieve.sh
# wait until arrays finish

# ── 4. Global top-N per methodology ───────────────────────
for m in amine_absorption membrane_separation calcium_looping oxyfuel_combustion cryogenic_capture mineralization; do
  METHODOLOGY=$m bash scripts/engaging/04_merge_rank.sh
done

# ── 5. Extract literature (all 6) ─────────────────────────
for m in amine_absorption membrane_separation calcium_looping oxyfuel_combustion cryogenic_capture mineralization; do
  sbatch --export=ALL,METHODOLOGY="$m" scripts/engaging/05_extract_array.sh
done
# wait until arrays finish

# ── 6. Merge literature extractions ────────────────────────
for m in amine_absorption membrane_separation calcium_looping oxyfuel_combustion cryogenic_capture mineralization; do
  METHODOLOGY=$m bash scripts/engaging/06_merge_extract.sh
done

# ── 7. Internet search + web extraction ───────────────────
bash scripts/engaging/submit_all_web.sh
# wait until jobs finish

# ── 8. Export CSVs (literature + web) ─────────────────────
for m in amine_absorption membrane_separation calcium_looping oxyfuel_combustion cryogenic_capture mineralization; do
  METHODOLOGY=$m bash scripts/engaging/08_export_csv.sh
done
```

## Download CSVs

From your laptop:

```bash
mkdir -p ./local_results
scp engaging:/home/rohan931/urop/concrete-sustainability-UROP/outputs/carbon_capture/csv/*.csv ./local_results/
```

## Output layout

```
outputs/carbon_capture/
├── screening_merged.jsonl
├── shards/
│   ├── screening/
│   ├── retrieve/{method}/
│   └── extract/{method}/
├── ranked/{method}_final.jsonl
├── extractions/{method}_merged.jsonl   # literature
├── web/{method}_web.jsonl             # internet search
└── csv/
    ├── {method}_answers.csv           # literature + web merged
    ├── {method}_literature.csv
    └── {method}_web.csv
```

Each answers CSV includes source fields on every row:
`source_type`, `source_title`, `source_url_or_citation`
(`source_type` is `Literature` or `Web`).

## Cost / efficiency notes

- **Stage 1** is the most expensive (LLM call per paper). Run once; reuse `screening_merged.jsonl` for all six methodologies.
- **Stage 3** is cheap (keyword ranking only).
- **Stage 5** only runs on global top-N papers (default 50) per methodology, not the full corpus.
- **Stage 7** uses Tavily for technology-level queries plus company/project follow-ups seeded from literature rows. Cap with `WEB_LIMIT` (default 50).
- Each literature worker loads the full pickle (~16s). Shards reduce *compute* per job, not pickle I/O. For faster loads later, consider converting to a shard-indexed format.

## Local testing

```bash
# Lightweight test mode (writes to outputs/test_run/ by default)
python pipeline/run_batch.py \
  --subcategory "oxyfuel combustion" \
  --test-mode \
  --paper-limit 5 \
  --web-limit 5 \
  --output-dir outputs/test_run

python pipeline/run_batch.py \
  --subcategory "oxyfuel combustion" \
  --test-mode \
  --paper-limit 5 \
  --skip-web \
  --output-dir outputs/test_literature_only

# Equivalent via run_carbon_capture.py
python pipeline/run_carbon_capture.py --subcategory "oxyfuel combustion" \
  --test-mode --paper-limit 5 --web-limit 5 --output-dir outputs/test_run

# Full local run
python pipeline/run_carbon_capture.py --all --start 0 --end 500 --top-n 5
```
