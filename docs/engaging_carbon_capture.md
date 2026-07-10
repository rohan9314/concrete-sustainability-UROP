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

```bash
git clone <repo> ~/concrete_sustainability_urop
cd ~/concrete_sustainability_urop

# Lightweight deps (includes tavily-python for web search)
python -m pip install --user -r requirements-screening.txt

# Copy pickle to cluster storage (not in git)
export PICKLE_PATH=$HOME/filtered_records_rohan.pkl
export OPENAI_API_KEY=sk-...
export TAVILY_API_KEY=tvly-...
export OUTPUT_DIR=$HOME/concrete_sustainability_urop/outputs
export EXTRACTION_CONCURRENCY=4
export TOP_N_SOURCES=50
export WEB_LIMIT=50
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
for m in amine_absorption membrane_separation calcium_looping oxyfuel_combustion cryogenic_capture mineralization; do
  METHODOLOGY=$m bash scripts/engaging/04_merge_rank.sh
done

# 5. Extract literature (array per methodology)
for m in amine_absorption membrane_separation calcium_looping oxyfuel_combustion cryogenic_capture mineralization; do
  METHODOLOGY=$m sbatch scripts/engaging/05_extract_array.sh
done

# 6. Merge literature extractions (after extract arrays complete)
for m in amine_absorption membrane_separation calcium_looping oxyfuel_combustion cryogenic_capture mineralization; do
  METHODOLOGY=$m bash scripts/engaging/06_merge_extract.sh
done

# 7. Internet search + web extraction (requires TAVILY_API_KEY)
bash scripts/engaging/submit_all_web.sh
# Or one methodology:
# METHODOLOGY=amine_absorption sbatch scripts/engaging/07_web_extract.sh

# 8. Export CSVs (literature + web)
for m in amine_absorption membrane_separation calcium_looping oxyfuel_combustion cryogenic_capture mineralization; do
  METHODOLOGY=$m bash scripts/engaging/08_export_csv.sh
done
```

## Download CSVs

From your laptop:

```bash
scp engaging:~/concrete_sustainability_urop/outputs/carbon_capture/csv/*.csv ./local_results/
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
