# Historical scripts

This directory contains superseded data builders kept for experiment
provenance and ablations.

- `sft/build_mixed_sft.py`: deterministic V1 bootstrap mix.
- `sft/build_sft_v2_json.py`: one-time XML-to-JSON migration.
- `sft/build_sft_v3_augmented.py`: mechanical V3 augmentation experiment.
- `sft/build_english_formal_sft.py`: English-only formal-set composition.

These scripts may depend on historical inputs and compatibility parsers. They
are not entrypoints for the current SFT or RL pipeline.
