from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge a PEFT LoRA adapter into a base HF causal LM checkpoint.")
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()

    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(
        args.base_model,
        trust_remote_code=True,
        local_files_only=args.local_files_only,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
        local_files_only=args.local_files_only,
    )
    model = PeftModel.from_pretrained(model, args.adapter, local_files_only=args.local_files_only)
    merged = model.merge_and_unload()
    merged.save_pretrained(output, safe_serialization=True)
    tokenizer.save_pretrained(output)
    print({"base_model": args.base_model, "adapter": args.adapter, "output": str(output)})


if __name__ == "__main__":
    main()
