# Model artifacts

Model weights are intentionally not committed to this repository.

The selected SFT artifact is the LoRA adapter from
`qwen25-coder3b-sqlite-sft-v3-checkpoint600`. Its local weight file is about
228 MiB and must be distributed through an external model or file host.

Before publishing the adapter, record:

- base model: `Qwen/Qwen2.5-Coder-3B-Instruct`
- adapter format: PEFT LoRA
- selected optimizer step: 600
- SHA-256 of `adapter_model.safetensors`
- download URL

The formal Slime/Megatron RL checkpoint is not included because it is about
41 GiB. The reproducible configuration and validation curve are documented in
`docs/rl_design_and_results.md`.
