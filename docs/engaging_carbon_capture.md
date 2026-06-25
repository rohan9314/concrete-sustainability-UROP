# MIT Engaging cluster workflow for carbon capture CSV pipeline

This document describes how to run the full corpus workflow on MIT Engaging using
SLURM array jobs. The design separates **screening**, **retrieval**, **extraction**,
and **CSV export** so each stage can scale independently.

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

## Algorithm (7 stages)

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
│ Stage 5: EXTRACT (array × 6 methods)  │  26-question LLM extraction batches
│  → shards/extract/{method}/extract_*  │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│ Stage 6: MERGE-EXTRACT + EXPORT-CSV   │  Final answers + citations CSV
│  → csv/{method}_answers.csv           │
│  → csv/{method}_citations.csv         │
└───────────────────────────────────────┘
```

## Setup on Engaging

```bash
git clone <repo> ~/research_agent
cd ~/research_agent

# Lightweight deps (no Tavily, tiktoken, FastAPI)
python -m pip install --user -r requirements-screening.txt

# Copy pickle to cluster storage (not in git)
export PICKLE_PATH=$HOME/filtered_records_rohan.pkl
export OPENAI_API_KEY=sk-...
export OUTPUT_DIR=$HOME/research_agent/outputs
export EXTRACTION_CONCURRENCY=4
export TOP_N_SOURCES=50
export SHARD_SIZE=10000
```

## Plan shards

```bash
python pipeline/run_carbon_capture_cluster.py plan --shard-size 10000
# Example: 159372 records → 16 shards (tasks 0–15)
```

Update `#SBATCH --array=0-15` in the shell scripts to match.

## Run stages

Scripts live in `scripts/engaging/`.

```bash
mkdir -p logs

# 1. Screen all papers (array)
sbatch scripts/engaging/01_screen_array.sh

# 2. Merge screening (after array completes)
bash scripts/engaging/02_merge_screening.sh

# 3. Retrieve/rank per methodology (submit 6 arrays)
bash scripts/engaging/submit_all_retrieve.sh
# Or one methodology:
# METHODOLOGY=amine_absorption sbatch scripts/engaging/03_retrieve_array.sh

# 4. Global top-N per methodology
METHODOLOGY=amine_absorption bash scripts/engaging/04_merge_rank.sh
# Repeat for all six, or loop:
for m in amine_absorption membrane_separation calcium_looping oxyfuel_combustion cryogenic_capture mineralization; do
  METHODOLOGY=$m bash scripts/engaging/04_merge_rank.sh
done

# 5. Extract (array per methodology)
METHODOLOGY=amine_absorption sbatch scripts/engaging/05_extract_array.sh

# 6. Merge + CSV
METHODOLOGY=amine_absorption bash scripts/engaging/06_export_csv.sh
```

## Download CSVs

From your laptop:

```bash
scp engaging:~/research_agent/outputs/carbon_capture/csv/*.csv ./local_results/
```

## Output layout

```
outputs/carbon_capture/
├── screening_merged.jsonl
├── shards/
│   ├── screening/
│   ├── retrieve/{methodology}/
│   └── extract/{methodology}/
├── ranked/{methodology}_final.jsonl
├── extractions/{methodology}_merged.jsonl
└── csv/
    ├── amine_absorption_answers.csv
    ├── amine_absorption_citations.csv
    └── ...
```

## Cost / efficiency notes

- **Stage 1** is the most expensive (LLM call per paper). Run once; reuse `screening_merged.jsonl` for all six methodologies.
- **Stage 3** is cheap (keyword ranking only).
- **Stage 5** only runs on global top-N papers (default 50) per methodology, not the full corpus.
- Each worker loads the full pickle (~16s). Shards reduce *compute* per job, not pickle I/O. For faster loads later, consider converting to a shard-indexed format.

## Local testing

```bash
# Small slice without cluster
python pipeline/run_carbon_capture.py --methodology amine_absorption --start 0 --end 500 --top-n 5

# Test one cluster stage locally
python pipeline/run_carbon_capture_cluster.py screen --task-id 0 --shard-size 500
```
