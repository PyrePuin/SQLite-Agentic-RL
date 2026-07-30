# SQLite Agentic RL V2 Data

This directory is the canonical data root for V2. Paths stored inside task
files are project-relative so the repository can move between machines.

## Official SFT Train Sets

### Current Formal Train: V3 Real JSON

Use this file for the next SFT run:

- Train file: `data/sft/v3_real_json/sft_v3_real_json_5817.jsonl`
- Manifest: `data/sft/v3_real_json/manifest.json`
- Audit: `data/sft/v3_real_json/audit.json`
- Protocol: `json_v2`, pure JSON assistant targets, no XML tags.
- Current row count: 5,817.

Composition:

- V2 JSON base: 5,486 rows
- Verified real English teacher-agent hard traces: 331 rows

The 331 V3-real rows come from actual DeepSeek teacher rollouts through the SQLite tool environment and are verifier-successful. They are not mechanical gold-SQL bootstrap traces.

Key audit facts:

- Assistant XML tags: 0
- Assistant schema errors: 0
- Strict invalid tool names: 0
- Teacher-real DB coverage: 81 DBs
- Teacher-real difficulty: 230 hard, 101 medium

### Previous V2 JSON Base

Kept as the reproducible base dataset:

- Train file: `data/sft/v2_json/sft_v2_json_5486.jsonl`
- Current row count: 5,486
- Manifest: `data/sft/v2_json/manifest.json`
- Audit: `data/sft/v2_json/audit.json`

## Validation Sets

Derived from `data/splits/v2_db_seed42/dev.jsonl` only. The held-out
`final_eval.jsonl` is not used for checkpoint selection.

Standard V2 validation sets:

- `data/eval/sft_v2_json/mini_dev.jsonl`: 60 rows, 36 DBs
- `data/eval/sft_v2_json/fast_dev.jsonl`: 120 rows, 36 DBs
- `data/eval/sft_v2_json/full_dev.jsonl`: 300 rows, 36 DBs

Hard English mini-val for V3:

- `data/eval/sft_v2_json/hard_mini_dev_en.jsonl`: 110 rows, 22 DBs

The hard mini-val is task/eval data, not a teacher trajectory dataset. It should be used by the agent evaluator to run real model rollouts.

## Train Command Root

Run SFT commands from the repository root:

```bash
cd SQLite-Agentic-RL-V2
```
