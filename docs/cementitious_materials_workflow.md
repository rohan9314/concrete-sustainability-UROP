# Cementitious Materials Workflow (7-30 results)

Unified extraction pipeline that replaces the previous high-level split among Supplementary Cementitious Materials, Alternative Cementitious Materials, and Alternative Supplementary Cementitious Materials with one umbrella category:

**Cementitious Materials**

Classification uses:

- `category`
- `subcategory`
- `sub_subcategory`
- `technology_variant`

Classification is role- and intervention-sensitive (not keyword-only). Existing carbon-capture and SCM pipelines remain intact; this package adds a parallel unified workflow and a deterministic CCS migration path.

Taxonomy version: `cementitious-materials-v1-2026-07-30`  
Config: `config/cementitious_materials_taxonomy.yaml` (and `.json`)

---

## Taxonomy overview

Nine subcategories (58 sub-subcategories):

1. Conventional and Blended Cements
2. Clinker Feedstock Decarbonization
3. Cement Manufacturing Efficiency
4. Cement-Plant Carbon Capture
5. Alternative Cement Chemistries
6. Conventional Supplementary Cementitious Materials
7. Emerging Supplementary Cementitious Materials
8. Multi-Material Cementitious Blends
9. Inert and Low-Reactivity Fillers

List nodes:

```bash
python -m pipeline.export_taxonomy_partitions --list-taxonomy
python -m pipeline.run_cementitious_materials validate-taxonomy
```

---

## Directory structure

Final run output (exact name):

```text
${RESULTS_ROOT}/7-30 results/
├── concrete_decarbonization_results/        # CANONICAL five-level export
│   ├── concrete_decarbonization.csv         # Level 0 (all records)
│   ├── cementitious_materials/
│   │   ├── cementitious_materials.csv
│   │   └── … / <level3>/
│   │         ├── <level3>.csv
│   │         └── <level4>.csv
│   ├── aggregate_procurement/
│   ├── concrete_design/
│   ├── structural_and_construction_design/
│   ├── operation/
│   ├── policy/
│   └── end_of_life/
├── cementitious_materials_results/          # compatibility two-level cementitious view
│   ├── cementitious_materials_all_records.csv
│   ├── category_csvs/
│   └── subcategory_csvs/
├── all_records/                             # internal + compatibility copies
│   ├── cementitious_materials_all_records.csv
│   ├── cementitious_materials_all_records.jsonl
│   ├── citations_all.csv
│   ├── run_manifest.json
│   ├── taxonomy_manifest.json
│   ├── validation_report.json
│   └── partition_summary.csv
├── subcategories/          # 9 CSVs (always created, empty OK) — INTERNAL runtime
├── sub_subcategories/      # 58 CSVs (always created, empty OK) — INTERNAL runtime leaves
├── citations/
├── pending_taxonomy_review/
├── logs/
├── checkpoints/
├── rejected_records/
└── metadata/
    ├── run_manifest.json
    ├── validation_report.json
    ├── taxonomy_export_manifest.json
    ├── cementitious_runtime_taxonomy_migration.json
    ├── resource_usage_summary.json
    └── full_run_resource_recommendations.json
```

Canonical taxonomy config: `config/concrete_decarbonization_taxonomy.json` (five levels, 0–4).
The cementitious extraction runtime still uses `config/cementitious_materials_taxonomy.json` (9 groups / 58 leaves) and maps into the five-level tree at export time.

### Five-level export rules

- One canonical master dataframe; every hierarchical CSV is a filter of that same table.
- Levels 0–3: folder (except Level 0 uses the export root) + CSV, including empty header-only CSVs.
- Level 4: CSV in the Level-3 folder; empty Level-4 CSVs are omitted and listed in `metadata/taxonomy_export_manifest.json`.
- `taxonomy_level_4 = N.A.` (or blank) means the row belongs in ancestor CSVs but not in any Level-4 leaf CSV.
- `cementitious_materials_results/` remains a compatibility view of the cementitious subset using the previous two-level layout.

### User-facing vs internal taxonomy levels

The taxonomy has three internal levels: umbrella **category** (Cementitious Materials), **subcategory** (9 nodes), and **sub-subcategory / leaf** (58 nodes).

The user-facing export is two levels under the master CSV:

| User-facing output | Internal field / nodes | Example |
| --- | --- | --- |
| `category_csvs/<slug>.csv` | `subcategory_slug` (9) | `cement_plant_carbon_capture.csv` |
| `subcategory_csvs/<category>/<slug>.csv` | `sub_subcategory_slug` (58), nested under the parent subcategory | `cement_plant_carbon_capture/chemical_absorption.csv` |

Do not treat the 58 leaf files under internal `sub_subcategories/` as the user-facing subcategory folder. Those remain internal/intermediate (and still include empty files).

All user-facing CSVs are filtered views of **one** canonical dataframe (`cementitious_materials_all_records.csv`). They share the full unified schema and column order. Empty user-facing category/subcategory CSVs are **not** created.

Records that fail taxonomy validation are written to `rejected_records/` and are not in the master. Rows that reach export with a blank subcategory/leaf slug are kept in the master, copied to `cementitious_materials_results/unassigned_taxonomy.csv`, omitted from category/subcategory CSVs, and fail validation so `export.complete` is not written.

### Record count vs CSV file count

A successful taxonomy export still materializes **all** configured **internal** partition CSVs (9 subcategory + 58 leaf record files, plus matching citation CSVs), even when a branch has zero accepted rows. Pilot runs may therefore create ~150 internal CSV files while only populating one selected leaf (for example Chemical Absorption). Empty header-only **internal** partition files are valid.

The **user-facing** tree under `cementitious_materials_results/` only writes CSVs for partitions that have at least one canonical row.

### Backward compatibility

Downstream scripts and tests that read `all_records/`, `subcategories/`, `sub_subcategories/`, `citations/`, and `partition_summary.csv` keep working. Those paths remain the internal/compat layout. Prefer `cementitious_materials_results/` for new user-facing consumers.

### Final metadata contract

Canonical machine-readable summaries live under `metadata/`:

- `run_manifest.json` — what ran (mode, taxonomy, counts, checkpoints, job IDs, non-secret settings).
- `validation_report.json` — pass/fail checks that the exported partition tree matches the master records/citations.

`checkpoints/export.complete` is written **only after** both JSON files are written and `validation_report.overall_status` is `pass`.

Compatibility copies are also written under `all_records/` for older local-runner consumers.

### Metadata-only repair

If an older Engaging run exported CSVs and wrote `export.complete` before this contract existed, regenerate metadata without re-running LLM/web stages:

```bash
python -m pipeline.cementitious.cluster finalize-metadata \
  --output "/path/to/7-30 results"
```

This reads existing CSVs, writes `metadata/run_manifest.json` and `metadata/validation_report.json`, and refreshes `export.complete` only when validation passes. No OpenAI or Tavily calls are made.

### What counts as a successful final run

1. User-facing master + populated category/subcategory CSVs under `cementitious_materials_results/`, plus internal master + all taxonomy partition/citation CSVs with correct headers.
2. Every master record appears in the matching user-facing category/subcategory files and in the matching internal subcategory and leaf files only.
3. Citations align to records and leaf citation partitions.
4. Required audits for missing shards / invalid taxonomy are empty (as applicable).
5. `metadata/run_manifest.json` and `metadata/validation_report.json` exist with `overall_status: pass`.
6. `checkpoints/export.complete` is present.

### RESULTS_ROOT normalization

Both of the following resolve to the same final directory (never nested):

```bash
RESULTS_ROOT=/path/to/results-parent
# → /path/to/results-parent/7-30 results

RESULTS_ROOT="/path/to/results-parent/7-30 results"
# → /path/to/results-parent/7-30 results
```

Legacy directories named `730 results` are **not** written to. The resolver warns and refuses those paths. Optional explicit migration:

```bash
python -m pipeline.cementitious.cluster migrate-legacy-results --mode copy
# or --mode move
```

Do not rename or delete legacy `730 results` automatically.

If `RESULTS_ROOT` is unset, the default is `<repository_root>/results`, so output becomes:

```text
<repository_root>/results/7-30 results
```

---

## Environment-variable reference

| Canonical name | Aliases | Required | Purpose |
|---|---|---|---|
| `OPENAI_API_KEY` | — | yes (extract) | LLM |
| `PICKLE_PATH` | `PAPER_RECORDS_PATH` | yes except `web-only` | Corpus pickle (not assumed in-repo) |
| `RESULTS_ROOT` | — | yes (Engaging) | Parent of `7-30 results` |
| `TAVILY_API_KEY` | — | yes except `literature-only` | Web retrieval (never logged) |
| `TAXONOMY_PATH` | — | no | Override taxonomy JSON/YAML |
| `TOP_N` | `TOP_N_SOURCES` | no (default 50) | Extraction cap / ranking |
| `WEB_LIMIT` | — | no (default 50) | Legacy alias; prefer `WEB_MAX_TOTAL_URLS` |
| `WEB_QUERIES_PER_SUBCATEGORY` | — | no (default 3) | Query budget per subcategory |
| `WEB_QUERIES_PER_SUB_SUBCATEGORY` | — | no (default 5) | Query budget per sub-subcategory |
| `WEB_RESULTS_PER_QUERY` | — | no (default 10) | Tavily results per query |
| `WEB_MAX_URLS_PER_BRANCH` | — | no (default 50) | Unique URL cap per taxonomy branch |
| `WEB_MAX_TOTAL_URLS` | — | no (default 1000) | Global unique URL cap |
| `WEB_SEARCH_SHARD_SIZE` | — | no (default 10) | Queries per web-search shard |
| `WEB_EXTRACT_SHARD_SIZE` | — | no (default 10) | URLs per web-extract shard |
| `WEB_CONCURRENCY` | — | no (default 4) | Web concurrency bound |
| `WEB_REQUEST_TIMEOUT` | — | no (default 30) | Tavily/request timeout seconds |
| `WEB_MAX_RETRIES` | — | no (default 3) | Bounded retries |
| `WEB_PAGE_MAX_CHARS` | — | no (default 50000) | Max page text for extraction |
| `WEB_DOMAIN_ALLOWLIST` | — | no | Comma-separated domains |
| `WEB_DOMAIN_DENYLIST` | — | no | Comma-separated domains |
| `SHARD_SIZE` | — | no (default 10000) | Papers per screen shard |
| `EXTRACT_SHARD_SIZE` | — | no (default 25) | Ranked candidates per extract shard |
| `TOP_N_PER_SUBCATEGORY` | — | no | Optional per-subcategory ranking cap |
| `TOP_N_PER_SUB_SUBCATEGORY` | — | no | Optional per-sub-subcategory ranking cap |
| `KEYWORD_ONLY` | — | no | `1` uses keyword screening/extraction (tests/debug) |
| `SCREEN_ARRAY_OVERRIDE` | — | no | Debug-only screen array override |
| `CONCURRENCY` | `EXTRACTION_CONCURRENCY` | no (default 4) | Parallelism |
| `RUN_MODE` | — | no | `literature-and-web` / `literature-only` / `web-only` |
| `SELECTED_SUBCATEGORIES` | — | no | Comma-separated slugs/names |
| `SELECTED_SUB_SUBCATEGORIES` | — | no | Comma-separated slugs/names |
| `CEMENTITIOUS_PILOT_TAXONOMY_SCOPE` | — | no (pilot default `smoke`) | `smoke` = one-branch taxonomy restriction; `all` = full taxonomy with the literature record cap still applied. Independent of corpus sampling. |
| `CHECKPOINT_DIR` | — | no | Defaults under `7-30 results/checkpoints` |
| `LITERATURE_ONLY` | — | no | `1` forces literature-only |
| `WEB_ONLY` | — | no | `1` forces web-only |
| `FORCE` | — | no | Overwrite completed outputs |
| `RESUME` | — | no | Skip stages with success markers |
| `DRY_RUN` | — | no | Validate/plan without submitting |
| `EXECUTION_MODE` | — | no | `submit` (default) or `interactive` (in-process stages; no Slurm) |
| `CCS_MIGRATE_INPUT` | — | no | Existing CCS results path to migrate |

Confirm secrets without printing values:

```bash
test -n "${OPENAI_API_KEY:-}" && echo "OPENAI_API_KEY is set"
test -n "${TAVILY_API_KEY:-}" && echo "TAVILY_API_KEY is set"
test -r "${PICKLE_PATH:-}" && echo "PICKLE_PATH is readable"
test -n "${RESULTS_ROOT:-}" && echo "RESULTS_ROOT is set"
```

---

## Literature taxonomy analysis (optional)

Vocabulary discovery / validation against the approved taxonomy. Does **not** overwrite
`config/cementitious_materials_taxonomy.*`. Dataset `Category` values are treated as noisy
context only.

```bash
python -m pipeline.cementitious.analyze_literature_taxonomy \
  --input "/path/to/Literature mining dataset.csv" \
  --taxonomy config/cementitious_materials_taxonomy.yaml \
  --output "${RESULTS_ROOT}/7-30 results/metadata/literature_taxonomy_analysis"
```

Outputs (under `--output`): `observed_material_names.csv`, `proposed_synonym_mappings.csv`,
`unresolved_material_names.csv`, `ambiguous_abbreviations.csv`, `category_crosswalk.csv`,
`proposed_technology_variants.csv`, `taxonomy_coverage_summary.csv`,
`material_frequency_by_source.csv`, `data_quality_issues.csv`.

Optional pending synonym file (default `config/generated_literature_synonyms.yaml`) is marked
`pending_approval` and must be reviewed before any taxonomy edit. No live LLM calls unless
`--use-llm` is passed (currently a no-op guard).

---

## Local smoke-test commands

Unit tests (no corpus / no API required):

```bash
cd /path/to/concrete_sustainability_urop
python pipeline/test_cementitious_materials.py
```

Export-only smoke (synthetic merged CSV via tests is covered above). For a keyword-only local sample run (requires `PICKLE_PATH`):

```bash
export PICKLE_PATH=/absolute/path/to/filtered_records_rohan.pkl
export RESULTS_ROOT=/tmp/cementitious-smoke-root

python -m pipeline.run_cementitious_materials run \
  --sample-size 20 \
  --seed 42 \
  --literature-only \
  --keyword-only \
  --output /tmp/cementitious-smoke-test
```

LLM local sample (requires OpenAI key):

```bash
export OPENAI_API_KEY=...
export PICKLE_PATH=/absolute/path/to/filtered_records_rohan.pkl

python -m pipeline.run_cementitious_materials run \
  --sample-size 20 \
  --seed 42 \
  --literature-only \
  --output /tmp/cementitious-smoke-test
```

### Engaging launch modes: smoke vs full-taxonomy pilots vs full

A **pilot reduces corpus size**. It must not silently reduce the taxonomy to one branch.

| Command | Mode | Literature cap | Taxonomy | Output suffix |
| --- | --- | --- | --- | --- |
| `--pilot` | smoke | 50 | one branch (`cement_plant_carbon_capture` / `chemical_absorption`) unless `CEMENTITIOUS_PILOT_TAXONOMY_SCOPE=all` | `cementitious_engaging_pilot/` |
| `--pilot-50` | production-like 50 | 50 | **full** canonical Concrete Decarbonization tree (L0–L4) | `concrete_decarbonization_pilot_50/` |
| `--pilot-1000` | production-like 1000 | 1000 | **full** canonical tree | `concrete_decarbonization_pilot_1000/` |
| `--full` | production | uncapped | full canonical tree | `concrete_decarbonization_full_run/` |

All four modes enable literature **and** Tavily/web by default, write hierarchical `concrete_decarbonization_results/`, and emit resource telemetry (`resource_usage_summary.json`, `full_run_resource_recommendations.json`). Inner layout still uses `7-30 results/` under the suffix above.

```bash
bash scripts/engaging/run_concrete_decarbonization_full_workflow.sh --full --dry-run
bash scripts/engaging/run_concrete_decarbonization_full_workflow.sh --pilot-50 --dry-run
bash scripts/engaging/run_concrete_decarbonization_full_workflow.sh --pilot-1000 --dry-run
# backward-compatible alias:
bash scripts/engaging/run_cementitious_full_workflow.sh --pilot-50 --dry-run
```

`--pilot` remains the cheap smoke launcher (`run_cementitious_pilot.sh` just calls `--pilot`). To keep that 50-record cap on the smoke command without restricting taxonomy:

```bash
CEMENTITIOUS_PILOT_TAXONOMY_SCOPE=all bash scripts/engaging/run_cementitious_full_workflow.sh --pilot
```

Explicit `SELECTED_SUBCATEGORIES` / `SELECTED_SUB_SUBCATEGORIES` still override. Literature sampling is deterministic `random.Random(seed).sample` with default seed `42` (`CEMENTITIOUS_SAMPLE_SEED` / `SAMPLE_SEED`), not first-N. Pilot web caps (`WEB_MAX_TOTAL_URLS`, `WEB_MAX_TOTAL_QUERIES`, …) are conservative and overridable via env.

Checkpoints are per output directory: a completed 50-paper run cannot block 1000 or full. `FORCE=1` overwrites only the selected mode's output.

### Full-run memory bounds

The ~5.5 GB pickle is deserialized **once** in the preprocess job (64G request). Array workers read only their JSONL shard; they do not `pickle.load`.

Full defaults (override with env): `SHARD_SIZE=10000` (~16 shards for ~159k papers), `CEMENTITIOUS_WORKERS=1`, `ARRAY_MAX_CONCURRENCY=1`. Peak RSS scales roughly with concurrent array tasks × per-shard RSS. Do not raise concurrency without calibrated MaxRSS headroom.

Ranking streams `screening_results.jsonl` into a bounded TOP_N heap. Hierarchical export buckets row *references* and writes one taxonomy node at a time. Web search truncates `raw_content` to `WEB_PAGE_MAX_CHARS` and merges unique URLs without holding every raw Tavily row.

Soft-memory-stop checkpoints a shard and exits 75 (resumable). Slurm `OUT_OF_MEMORY` / exit 137 is a cgroup kill. Signal 9 is not labeled definite OOM unless MaxRSS is ≥80% of ReqMem or the job state is `OUT_OF_MEMORY`. `TIMEOUT` / `NODE_FAIL` are non-memory failures.

Full submit requires calibrated pilot telemetry (prefer `concrete_decarbonization_pilot_1000`). Override only with `--allow-uncalibrated-resources`.

---

## Full local run commands

```bash
export OPENAI_API_KEY=...
export TAVILY_API_KEY=...   # omit if literature-only
export PICKLE_PATH=/absolute/path/to/corpus.pkl
export RESULTS_ROOT=/path/to/results/root   # optional; default <repo>/results

python -m pipeline.run_cementitious_materials plan
python -m pipeline.run_cementitious_materials run --mode literature-and-web --sample-size 100 --seed 42
```

Selected scopes:

```bash
# One subcategory
python -m pipeline.run_cementitious_materials run \
  --subcategory cement_plant_carbon_capture

# One sub-subcategory
python -m pipeline.run_cementitious_materials run \
  --sub-subcategory biomass_ashes \
  --sample-size 500

# Multiple subcategories
python -m pipeline.run_cementitious_materials run \
  --subcategories conventional_supplementary_cementitious_materials,emerging_supplementary_cementitious_materials
```

---

## Selective export commands

```bash
# A. Export all results
python -m pipeline.export_taxonomy_partitions \
  --input merged_records.csv \
  --output "${RESULTS_ROOT}/7-30 results"

# B. Export Cement-Plant Carbon Capture
python -m pipeline.export_taxonomy_partitions \
  --input merged_records.csv \
  --subcategory cement_plant_carbon_capture \
  --output "${RESULTS_ROOT}/7-30 results"

# C. Export only Chemical Absorption
python -m pipeline.export_taxonomy_partitions \
  --input merged_records.csv \
  --sub-subcategory chemical_absorption \
  --output "${RESULTS_ROOT}/7-30 results"

# Summary counts
python -m pipeline.export_taxonomy_partitions --input merged_records.csv --summary
```

Display names also work:

```bash
python -m pipeline.export_taxonomy_partitions \
  --input merged_records.csv \
  --subcategory "Cement-Plant Carbon Capture" \
  --output "${RESULTS_ROOT}/7-30 results"
```

---

## Carbon-capture migration

Does **not** delete or overwrite existing CCS pipeline outputs. Reads them and writes normalized records under the new taxonomy.

```bash
python -m pipeline.run_cementitious_materials migrate-carbon-capture \
  --input /path/to/existing/carbon_capture/csv_or_dir \
  --output "${RESULTS_ROOT}/7-30 results"
```

Mineralization behavior:

1. Every mineralization record is preserved in `metadata/legacy_mineralization_records.csv` (with citations/IDs).
2. Mineralization is **never** mapped into the six Cement-Plant Carbon Capture sub-subcategories.
3. SCM-compatible carbonated materials (explicit SCM / cement-replacement evidence) migrate to Emerging SCMs → Carbonated Waste-Derived SCMs.
4. All other mineralization cases become Pending Taxonomy Review under `pending_taxonomy_review/` (not rejected solely for falling outside the six plant-capture nodes).
5. Unresolved cases also append to `metadata/taxonomy_proposals.csv`.
6. Genuinely invalid / non-mineralization unmapped rows may still appear in `rejected_records/unmapped_carbon_capture_records.csv`.

Known deterministic plant-capture mappings include amine/solvent → Chemical Absorption, cryogenic → Cryogenic Carbon Capture, oxy-fuel → Oxy-Fuel Combustion, membrane → Membrane Separation, calcium looping → Calcium Looping, LEILAC/direct separation → Direct Separation.

---

## Live validation status

Run manifests and `validation_report.json` include live-call metrics. Allowed `run_status` values:

- `successful_live_validation` — required OpenAI/Tavily calls succeeded; no total fallback
- `degraded_fallback` — some live calls succeeded but keyword/snippet fallbacks occurred
- `failed_live_validation` — live calls attempted but none succeeded (e.g. `credit_balance_exhausted`)
- `mocked_validation` — unit/mocked Tavily or LLM
- `not_attempted` — keyword-only / no live calls

A keyword fallback does **not** count as a successful live LLM validation.

---

## One-Command Engaging Run (genuinely sharded)

1. Log into Engaging.
2. Pull the latest repository code.
3. Export authorization tokens, corpus path, and results root.
4. Run `./run_730_results.sh`.

```bash
export OPENAI_API_KEY="..."
export TAVILY_API_KEY="..."
export PICKLE_PATH="/absolute/path/to/filtered_records_rohan.pkl"
export RESULTS_ROOT="/absolute/path/to/results/root"

chmod +x run_730_results.sh
./run_730_results.sh
```

### Execution graph

**literature-only**

```text
plan-screen → screen-array → merge-screen → rank/plan-extract
  → extract-array → merge-extract → dedupe-qc → export
```

No Tavily. `TAVILY_API_KEY` not required.

**web-only**

```text
plan-web-queries → web-search-array → merge-web-search (+ screen)
  → plan-web-extract → web-extract-array → merge-web-extract
  → merge-literature-web → dedupe-qc → export
```

No paper corpus load. `PICKLE_PATH` optional.

**literature-and-web**

```text
[parallel]
  literature: plan-screen → screen-array → merge-screen → lit orchestrator
              → extract-array → merge-extract  (writes literature_terminal_job_id.txt)
  web:        plan-web-queries → web-search-array → web orchestrator
              → web-extract-array → merge-web-extract  (writes web_terminal_job_id.txt)
[join — no long-running marker poll]
  finalize-submit (afterok on both orchestrators; exits after submitting):
    merge-literature-web afterok:lit_terminal:web_terminal
      → dedupe-qc → optional CCS migrate → export
```

Scoped literature runs (`SELECTED_SUBCATEGORIES` / `SELECTED_SUB_SUBCATEGORIES`) limit screening prompts, synonym/cue sets, ranking, and extraction to the selected branches **before** screening — not only after.
Defaults:

- `SHARD_SIZE=10000` — papers per screen task
- `EXTRACT_SHARD_SIZE=25` — ranked candidates per extract task
- `WEB_SEARCH_SHARD_SIZE=10` — queries per web-search task
- `WEB_EXTRACT_SHARD_SIZE=10` — URLs per web-extract task
- `TOP_N=50` — global ranked-candidate cap (override with `TOP_N_PER_SUBCATEGORY` / `TOP_N_PER_SUB_SUBCATEGORY`)

Array ranges are **derived from manifests**. Production never defaults silently to `0-0` when multiple shards exist. Debug-only overrides: `SCREEN_ARRAY_OVERRIDE`, `WEB_SEARCH_ARRAY_OVERRIDE`.

Variants:

```bash
DRY_RUN=1 bash scripts/engaging/run_730_results.sh
RUN_MODE=literature-only bash scripts/engaging/run_730_results.sh
RUN_MODE=web-only bash scripts/engaging/run_730_results.sh   # no PICKLE_PATH required
RUN_MODE=literature-and-web bash scripts/engaging/run_730_results.sh
SELECTED_SUB_SUBCATEGORIES=chemical_absorption bash scripts/engaging/run_730_results.sh
RESUME=1 bash scripts/engaging/run_730_results.sh
FORCE=1 bash scripts/engaging/run_730_results.sh
EXECUTION_MODE=interactive bash scripts/engaging/run_730_results.sh
KEYWORD_ONLY=1 EXECUTION_MODE=interactive bash scripts/engaging/run_730_results.sh
```

### Stage scripts

```bash
# Literature
bash scripts/engaging/730_cementitious_plan.sh
bash scripts/engaging/730_cementitious_screen_array.sh
bash scripts/engaging/730_cementitious_merge_screening.sh
bash scripts/engaging/730_cementitious_rank_plan_extract.sh
bash scripts/engaging/730_cementitious_extract_array.sh
bash scripts/engaging/730_cementitious_merge_extractions.sh
bash scripts/engaging/730_cementitious_orchestrate_after_screen.sh

# Web
bash scripts/engaging/730_cementitious_plan_web_queries.sh
bash scripts/engaging/730_cementitious_web_search_array.sh
bash scripts/engaging/730_cementitious_merge_web_search.sh
bash scripts/engaging/730_cementitious_plan_web_extract.sh
bash scripts/engaging/730_cementitious_web_extract_array.sh
bash scripts/engaging/730_cementitious_merge_web_extract.sh
bash scripts/engaging/730_cementitious_orchestrate_web.sh

# Join / finalize
bash scripts/engaging/730_cementitious_merge_literature_web.sh
bash scripts/engaging/730_cementitious_finalize.sh
bash scripts/engaging/730_cementitious_dedupe_qc.sh
bash scripts/engaging/730_cementitious_export.sh
```

### Per-shard paths

Screen shard `N` (zero-padded to 5 digits):

- input range from `metadata/screen_shards.json`
- output: `metadata/screening_shards/screening_shard_NNNNN.jsonl`
- summary: `metadata/screening_shards/screening_shard_NNNNN_summary.json`
- marker: `checkpoints/screen_shards/screen_shard_NNNNN.complete`

Extract shard `N`:

- candidates from `metadata/extraction_shards.json`
- output: `metadata/extraction_shards/extraction_shard_NNNNN.jsonl`
- citations: `metadata/extraction_shards/extraction_shard_NNNNN_citations.jsonl`
- summary: `metadata/extraction_shards/extraction_shard_NNNNN_summary.json`
- marker: `checkpoints/extraction_shards/extract_shard_NNNNN.complete`

Web search shard `N`:

- queries from `metadata/web_query_shards.json`
- output: `metadata/web_search_shards/web_search_shard_NNNNN.jsonl`
- marker: `checkpoints/web_search_shards/web_search_shard_NNNNN.complete`

Web extract shard `N`:

- sources from `metadata/web_extraction_shards.json`
- output: `metadata/web_extraction_shards/web_extraction_shard_NNNNN.jsonl`
- citations: `metadata/web_extraction_shards/web_extraction_shard_NNNNN_citations.jsonl`
- summary: `metadata/web_extraction_shards/web_extraction_shard_NNNNN_summary.json`
- marker: `checkpoints/web_extraction_shards/web_extract_shard_NNNNN.complete`
- failed LLM: `logs/failed_llm_responses/web_extraction_shard_NNNNN/`

### Rerun one failed web shard

```bash
python -m pipeline.cementitious.cluster missing-web-search-shards --output "$OUT"
# example: 2,6,9-11
sbatch --array=2 --export="$COMMON_EXPORT,RESUME=0" \
  scripts/engaging/730_cementitious_web_search_array.sh

python -m pipeline.cementitious.cluster missing-web-extraction-shards --output "$OUT"
sbatch --array=4 --export="$COMMON_EXPORT,RESUME=0" \
  scripts/engaging/730_cementitious_web_extract_array.sh
```

### Small live web test (do not run from CI; requires real keys)

```bash
export OPENAI_API_KEY="..."
export TAVILY_API_KEY="..."
export RESULTS_ROOT="/tmp/cementitious-web-test"

python -m pipeline.run_cementitious_materials run \
  --mode web-only \
  --sub-subcategory chemical_absorption \
  --web-queries-per-sub-subcategory 2 \
  --web-results-per-query 3 \
  --web-max-total-urls 6 \
  --output "/tmp/cementitious-web-test/7-30 results"
```

Inspect:

```bash
OUT="/tmp/cementitious-web-test/7-30 results"
jq '.[0:5]' "$OUT/metadata/web_queries.json"
head -n 5 "$OUT/metadata/web_search_results_raw.jsonl"
head -n 5 "$OUT/metadata/web_search_results_deduplicated.jsonl"
head -n 5 "$OUT/metadata/web_screening_results.jsonl"
head -n 5 "$OUT/metadata/web_records_raw.jsonl"
head -n 5 "$OUT/metadata/web_citations_raw.jsonl"
head -n 5 "$OUT/sub_subcategories/chemical_absorption.csv"
jq . "$OUT/all_records/validation_report.json"
jq . "$OUT/all_records/run_manifest.json"
```

Combined literature+web small test:

```bash
export PICKLE_PATH="/absolute/path/to/corpus.pkl"
python -m pipeline.run_cementitious_materials run \
  --mode literature-and-web \
  --sub-subcategory chemical_absorption \
  --sample-size 20 \
  --web-queries-per-sub-subcategory 2 \
  --web-results-per-query 3 \
  --web-max-total-urls 6 \
  --output "/tmp/cementitious-combined-test/7-30 results"
```

Unit tests including web (mocked Tavily; no live calls):

```bash
python -m unittest pipeline.test_cementitious_web pipeline.test_cementitious_sharding pipeline.test_cementitious_materials
```

---

### Legacy literature-only per-shard notes (continued)

Extract shard `N` (literature):

- candidates from `metadata/extraction_shards.json`
- output: `metadata/extraction_shards/extraction_shard_NNNNN.jsonl`
- citations: `metadata/extraction_shards/extraction_shard_NNNNN_citations.jsonl`
- summary: `metadata/extraction_shards/extraction_shard_NNNNN_summary.json`
- marker: `checkpoints/extraction_shards/extract_shard_NNNNN.complete`
- failed LLM: `logs/failed_llm_responses/extraction_shard_NNNNN/`

### Rerun one failed shard

```bash
# Discover incomplete screen shards (prints e.g. 3,7,11-14)
python -m pipeline.cementitious.cluster missing-screen-shards --output "$OUT"

# Rerun screen shard 17 only
sbatch --array=17 --export="$COMMON_EXPORT,RESUME=0" \
  scripts/engaging/730_cementitious_screen_array.sh

# Discover incomplete extract shards
python -m pipeline.cementitious.cluster missing-extraction-shards --output "$OUT"

# Rerun extract shard 4 only
sbatch --array=4 --export="$COMMON_EXPORT,RESUME=0" \
  scripts/engaging/730_cementitious_extract_array.sh
```

After repairing shards, re-run the corresponding merge stage.

### Job status and logs

```bash
squeue -u "$USER"
sacct -j <job-id> --format=JobID,JobName,State,Elapsed,ExitCode
```

- Job IDs: `${RESULTS_ROOT}/7-30 results/metadata/submitted_jobs.json`
- Human summary: `${RESULTS_ROOT}/7-30 results/metadata/submitted_jobs.txt`
- Slurm logs: `<repo>/logs/cm-*.out`

### Resume

`RESUME=1` skips a shard only when **both** the output file and marker exist **and** the output passes validation. A marker alone is not trusted.

Stage markers (created only after successful verification):

- `plan_screen.complete` / `plan.complete`
- `screen.complete` / `screen_merge.complete`
- `rank_plan_extract.complete`
- `extract.complete` / `extract_merge.complete`
- `dedupe_qc.complete`
- `export.complete`

Per-shard markers live under `checkpoints/screen_shards/` and `checkpoints/extraction_shards/`.

---

## Local Mac synchronization

Run on your Mac only:

```bash
export ENGAGING_HOST="<user>@<host>"
export ENGAGING_RESULTS_PATH="/remote/path/to/results-root"
export LOCAL_UROP_DIR="/local/path/to/UROP"

bash scripts/local/sync_730_results.sh --dry-run
bash scripts/local/sync_730_results.sh --yes
```

Destination: `"${LOCAL_UROP_DIR}/7-30 results"`  
Log: `"${LOCAL_UROP_DIR}/7-30 results/sync.log"`

`--delete` is off by default and must be requested explicitly.

---

## Common errors

| Symptom | Fix |
|---|---|
| `PICKLE_PATH is not set` | Export absolute corpus pickle path |
| `RESULTS_ROOT` missing on Engaging | Export results root before launcher |
| `TAVILY_API_KEY is required` | Set key or `LITERATURE_ONLY=1` / `RUN_MODE=literature-only` |
| Invalid parent-child in export | Check rejected_records; do not silently repair |
| Empty Chemical Absorption CSV | No records mapped yet — file still created with headers |
| Mineralization outside plant-capture | Preserved in `legacy_mineralization_records.csv`; SCM-compatible → Carbonated Waste-Derived SCMs; else `pending_taxonomy_review/` |
| Stale `730 results` path | Use `7-30 results`; optional `migrate-legacy-results` |
| `credit_balance_exhausted` | Run status is `failed_live_validation` / `degraded_fallback` — not a successful LLM smoke |

---

## Compatibility notes

- Existing carbon-capture pipeline (`pipeline/run_carbon_capture*.py`, `scripts/engaging/0*.sh`) is unchanged.
- Existing SCM pipeline (`pipeline.scm`, `scripts/engaging/scm/`) is unchanged.
- This workflow writes only under `${RESULTS_ROOT}/7-30 results` (or an explicit `--output`).
