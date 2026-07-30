from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def render_message(message: dict[str, Any]) -> str:
    role = str(message["role"]).strip().capitalize()
    return f"{role}:\n{message['content']}\n\n"


def percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    index = min(len(values) - 1, int(round((len(values) - 1) * pct)))
    return sorted(values)[index]


def summarize(values: list[int], max_length: int) -> dict[str, Any]:
    return {
        "count": len(values),
        "p50": percentile(values, 0.50),
        "p90": percentile(values, 0.90),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": max(values) if values else 0,
        "over_max_length": sum(value > max_length for value in values),
        "over_max_length_rate": (sum(value > max_length for value in values) / len(values)) if values else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect token length distribution for formal SFT message JSONL.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--input", default="data/sft/v2_json/sft_v2_json_5486.jsonl")
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--output")
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True, local_files_only=args.local_files_only)
    rows = read_jsonl(Path(args.input))
    lengths: list[int] = []
    by_variant: dict[str, list[int]] = defaultdict(list)
    truncated_by_variant: Counter[str] = Counter()
    longest: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        text = ""
        for message in row["messages"]:
            text += render_message(message)
        if tokenizer.bos_token_id is not None:
            length = 1
        else:
            length = 0
        length += len(tokenizer(text, add_special_tokens=False).input_ids)
        if tokenizer.eos_token_id is not None:
            length += 1
        variant = str(row.get("variant", "unknown"))
        lengths.append(length)
        by_variant[variant].append(length)
        if length > args.max_length:
            truncated_by_variant[variant] += 1
        longest.append({"index": index, "id": row.get("id"), "variant": variant, "db_id": row.get("db_id"), "tokens": length})

    longest.sort(key=lambda item: int(item["tokens"]), reverse=True)
    summary = {
        "input": args.input,
        "model": args.model,
        "max_length": args.max_length,
        "overall": summarize(lengths, args.max_length),
        "by_variant": {variant: summarize(values, args.max_length) for variant, values in sorted(by_variant.items())},
        "truncated_by_variant": dict(sorted(truncated_by_variant.items())),
        "longest": longest[:30],
    }
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
