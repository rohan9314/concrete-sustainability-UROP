# SCM workflow

Parallel **Supplementary Cementitious Materials (SCM)** pipeline alongside the preserved carbon-capture workflow.

Carbon capture continues to use:

- `python pipeline/run_carbon_capture.py`
- `python pipeline/run_carbon_capture_cluster.py`
- `scripts/engaging/*.sh`
- outputs under `outputs/carbon_capture/` (or `OUTPUT_DIR`)

SCM uses a separate package and output root and does **not** rewrite carbon-capture schemas, prompts, CLI commands, or Engaging scripts.

## Architecture

```text
SCM workflow
│
├── A. Playbook-defined seed-category pipelines
│   ├── slag_cement
│   ├── coal_fly_ash
│   ├── harvested_coal_ash
│   ├── coal_bottom_ash
│   ├── silica_fume
│   ├── natural_pozzolans
│   ├── glass_pozzolan
│   └── ternary_blends
│
└── B. Open-ended SCM discovery pipeline
    ├── Broad literature / web screening
    ├── Open-ended material extraction
    ├── Alias normalization
    ├── Corpus-level category clustering
    └── Recommendations only (no auto-activation)
```

The eight seed categories are **anchors**, not a complete taxonomy. Additional categories may be recommended by discovery, but they stay `status: proposed` until manually approved.

Package layout:

```text
pipeline/scm/
  seed_categories.py   # playbook seed definitions
  schema.py            # evidence + discovery schemas / validation
  prompts.py
  retrieval.py
  extraction.py
  web.py
  merge.py
  export.py
  discovery.py
  normalize.py
  classification.py
  postprocess.py       # generate-category-config
  runner.py / stages.py / cluster.py / __main__.py
```

Shared infrastructure reused from the parent `pipeline/` package includes corpus loading, sharding, ranking, concurrency, OpenAI calls, JSON parsing, and Engaging-style resume checkpoints. Category-specific behavior stays inside `pipeline/scm/`.

## Outputs

Default root: `$OUTPUT_DIR/scm/` (test mode: `$OUTPUT_DIR/scm_test_run/`).

Seed category files (examples):

```text
scm/slag_cement_results.csv
scm/slag_cement_citations.csv
...
scm/ternary_blends_results.csv
scm/ternary_blends_citations.csv
```

Discovery / combined:

```text
scm/scm_discovery_evidence.csv
scm/scm_material_normalization.csv
scm/scm_discovered_categories.csv
scm/scm_all_evidence.csv
scm/scm_all_citations.csv
```

`scm_all_evidence.csv` includes `pipeline_branch` = `seed_category` | `open_discovery`.

## Running SCM Without Running Carbon Capture

SCM and carbon capture are independently executable. Running any SCM command does **not**
screen, retrieve, extract, merge, or write carbon-capture outputs, and does **not** require
carbon-capture results to exist.

### Isolation guarantees

- Entry point: `python -m pipeline.scm ...` (imports SCM + shared infra only)
- Optional dispatcher: `python -m pipeline.run --category scm ...` (requires explicit category)
- Output root: `$SCM_OUTPUT_ROOT` or `$OUTPUT_DIR/scm` (test mode: `$OUTPUT_DIR/test/scm`)
- Collision guard: SCM refuses to write if the resolved path equals/is inside the carbon-capture root
- Merge guard: SCM merge raises if a carbon-capture record is present
- Screening inputs must resolve under the SCM output root
- Checkpoints live under `outputs/scm/checkpoints/` only

Carbon-capture execution remains available via:

```bash
python pipeline/run_carbon_capture.py ...
python -m pipeline.run --category carbon_capture -- --methodology amine_absorption --test-mode
```

### Exact SCM-only commands

```bash
export PICKLE_PATH=/path/to/corpus.pkl
export OPENAI_API_KEY=...
# optional
export SCM_OUTPUT_ROOT=/path/to/outputs/scm
export TAVILY_API_KEY=...

# One SCM seed category
python -m pipeline.scm run-seed-category --subcategory slag_cement \
  --test-mode --paper-limit 5 --top-n 5 --web-limit 5

# All eight SCM seed categories (does NOT run discovery)
python -m pipeline.scm run-all-seed-categories --test-mode --paper-limit 5

# SCM discovery only (does NOT run seed-category extraction)
python -m pipeline.scm run-discovery --test-mode --paper-limit 50 --top-n 10 --web-limit 5

# All SCM stages (seeds + discovery + merge) — still never runs carbon capture
python -m pipeline.scm run-all --test-mode --paper-limit 5

# Dry run (no papers, no APIs, no CSV writes)
python -m pipeline.scm run-all --dry-run --test-mode

# Explicit category dispatcher
python -m pipeline.run --category scm run-all-seed-categories --test-mode
```

### Verify carbon-capture outputs were not changed

```bash
# Before / after an SCM test run
stat -f '%m %N' outputs/carbon_capture/* 2>/dev/null || true
# or
git status -- outputs/carbon_capture
```

If `outputs/carbon_capture` does not exist, SCM still runs normally.

### Resume

SCM resume inspects only `$SCM_OUTPUT_ROOT/checkpoints/` and SCM literature/web JSONL files.
A completed carbon-capture shard with a similar name is ignored.

## Engaging

Preserve existing carbon-capture scripts under `scripts/engaging/`.

SCM cluster scripts live under `scripts/engaging/scm/` and call only `python -m pipeline.scm` /
`python -m pipeline.scm.cluster`. They require environment variables (`PICKLE_PATH`, `OUTPUT_DIR`,
`SCM_OUTPUT_ROOT`, `OPENAI_API_KEY`, `TAVILY_API_KEY`) and do not hardcode absolute repo paths or
reference carbon-capture entry points/paths.

```bash
export REPO_ROOT=/path/to/repo
export PICKLE_PATH=/absolute/path/to/corpus.pkl
export OUTPUT_DIR=$REPO_ROOT/outputs
export SCM_OUTPUT_ROOT=$OUTPUT_DIR/scm
bash scripts/engaging/scm/01_plan.sh
# then submit 02_screen_array.sh → 03_merge_screening.sh → …
# with SUBCATEGORY=slag_cement for per-seed retrieve/extract/web/export
```

### 500-paper SCM seed-only Engaging test (recommended first cluster test)

One self-contained job covering **only** the eight playbook seed categories with literature +
internet retrieval. Open-ended discovery and carbon capture are disabled.

```bash
cd "$REPO_ROOT"
export PICKLE_PATH=/absolute/path/to/filtered_records_rohan.pkl
export OPENAI_API_KEY=...
export TAVILY_API_KEY=...
export OUTPUT_DIR="$REPO_ROOT/outputs"
# optional: activate the project virtualenv on Engaging
# source .venv/bin/activate

mkdir -p logs
sbatch --export=ALL scripts/engaging/run_scm_500_test.sh
```

Dry run (validates env/paths; no API calls, no paper processing):

```bash
bash scripts/engaging/run_scm_500_test.sh --dry-run
# or
sbatch --export=ALL,DRY_RUN=1 scripts/engaging/run_scm_500_test.sh
```

Monitor / cancel:

```bash
squeue -u "$USER"
tail -f logs/scm-500-test-<jobid>.out
tail -f logs/scm-500-test-<jobid>.err
sacct -j <jobid> --format=JobID,State,Elapsed,MaxRSS,ExitCode
scancel <jobid>
```

Outputs land under:

```text
outputs/7-27 SCM Test/
```

Key artifacts after completion:

```text
outputs/7-27 SCM Test/summary/scm_500_engaging_test_report.md
outputs/7-27 SCM Test/merged/scm_all_seed_evidence.csv
outputs/7-27 SCM Test/merged/scm_all_citations.csv
outputs/7-27 SCM Test/validation/validation_warnings.csv
outputs/7-27 SCM Test/csv/*_results.csv
outputs/7-27 SCM Test/merged/*_all_evidence.csv
```

Safe resume: resubmit the same `sbatch` command. The orchestrator reuses the seed-42
500-paper manifest and skips completed literature/web checkpoints under
`outputs/7-27 SCM Test/checkpoints/`.

Settings: `sample_size=500`, `random_seed=42`, `top_n=50`, `web_limit=10`,
`EXTRACTION_CONCURRENCY=2`, sequential categories, Slurm `4 CPU / 64G / 24h`.

## Normalization and promotion

- Alias overrides: `config/scm_material_alias_overrides.json` (small unambiguous starter set only).
- Promotion thresholds (env-overridable): `SCM_MIN_STRONGLY_RELEVANT_RECORDS` (20), `SCM_MIN_UNIQUE_SOURCES` (10), `SCM_MIN_INDEPENDENT_ORGANIZATIONS` (5), `SCM_MIN_LITERATURE_SOURCES` (5).
- Recommendations never auto-create or activate new pipeline modules.
- Generated configs under `config/scm_candidates/` remain `status: proposed` until manually approved.

## Ternary blends

Treated as binder systems. Constituents are stored as JSON arrays of `{material_name, fraction_percent}` (`NA` when a percentage is omitted). Do not flatten constituents into a single material name.

## Environment variables

| Variable | Purpose |
|---|---|
| `PICKLE_PATH` / `PAPER_RECORDS_PATH` | Corpus pickle |
| `OUTPUT_DIR` | Base outputs directory |
| `OPENAI_API_KEY` | Screening / extraction / clustering |
| `TAVILY_API_KEY` | Web retrieval |
| `TOP_N_SOURCES` | Default ranked papers |
| `EXTRACTION_CONCURRENCY` | Parallel LLM workers |
| `WEB_LIMIT` | Cap web sources |
| `SCM_MIN_*` | Promotion thresholds |

## Reviewing a newly discovered category

1. Inspect `scm_discovered_categories.csv`.
2. If `recommended_action` is `CREATE_DEDICATED_PIPELINE`, generate a draft config.
3. Review aliases / search terms in `config/scm_candidates/*.yaml`.
4. Manually approve (edit `status`) before any dedicated pipeline is added.
