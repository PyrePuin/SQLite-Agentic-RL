from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlite_agent_pkg.agent.parser import parse_json_v2_final, parse_json_v2_tool_call
from sqlite_agent_pkg.agent.protocol import json_v2_tool_result, system_message
from sqlite_agent_pkg.data.task_schema import load_tasks
from sqlite_agent_pkg.env.sqlite_tools import execute_tool
from sqlite_agent_pkg.rl.reward import compute_sqlite_agent_reward

torch: Any = None


def render_messages(messages: list[dict[str, str]]) -> str:
    return "".join(f"{msg['role'].capitalize()}:\n{msg['content']}\n\n" for msg in messages) + "Assistant:\n"


def first_json_span(text: str) -> tuple[int, int] | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return start, index + 1
    return None


def trim_to_json(text: str) -> tuple[str, bool]:
    span = first_json_span(text)
    if span is None:
        return text.strip(), False
    start, end = span
    return text[start:end], bool(text[:start].strip() or text[end:].strip())


def compact_execute_observation(action: dict[str, Any], observation: dict[str, Any], max_rows: int = 5) -> dict[str, Any]:
    if action.get("name") != "execute_sql" or not observation.get("ok"):
        return observation
    rows = observation.get("rows")
    if not isinstance(rows, list) or len(rows) <= max_rows:
        return observation
    compacted = dict(observation)
    compacted["rows"] = rows[:max_rows]
    compacted["truncated"] = True
    compacted["note"] = "Only the first rows are shown. Use final_sql, not a full row listing, in the final answer."
    return compacted


def generate_one(
    *,
    model: Any,
    tokenizer: Any,
    messages: list[dict[str, str]],
    max_prompt_tokens: int,
    max_new_tokens: int,
    temperature: float,
    top_p: float,
) -> str:
    prompt = render_messages(messages)
    encoded = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=max_prompt_tokens).to(model.device)
    with torch.no_grad():
        output = model.generate(
            **encoded,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=temperature,
            top_p=top_p,
            pad_token_id=tokenizer.pad_token_id,
        )
    return tokenizer.decode(output[0][encoded.input_ids.shape[1] :], skip_special_tokens=True)


def rollout_one(
    *,
    model: Any,
    tokenizer: Any,
    task: Any,
    max_tool_steps: int,
    max_prompt_tokens: int,
    max_new_tokens: int,
    temperature: float,
    top_p: float,
    include_traces: bool = False,
) -> dict[str, Any]:
    messages = [system_message("json_v2"), {"role": "user", "content": task.question}]
    actions: list[dict[str, Any]] = []
    final_sql: str | None = None
    last_successful_execute_sql: str | None = None
    parse_failed = False
    protocol_invalid = False
    canonical_protocol = True
    budget_exceeded = False
    trace: list[dict[str, Any]] = []

    for turn_index in range(max_tool_steps):
        raw = generate_one(
            model=model,
            tokenizer=tokenizer,
            messages=messages,
            max_prompt_tokens=max_prompt_tokens,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
        )
        content, overgenerated = trim_to_json(raw)
        # HF generate has no structured stop hook here, so it often continues
        # with extra role markers after a valid first JSON object. The Slime
        # rollout path stops earlier; keep dry-run scoring aligned with Slime
        # by scoring only the first complete JSON object.
        messages.append({"role": "assistant", "content": content})
        if include_traces:
            trace.append(
                {
                    "turn": turn_index,
                    "raw": raw,
                    "content": content,
                    "overgenerated": overgenerated,
                }
            )

        final, final_canonical = parse_json_v2_final(content)
        if final is not None:
            final_sql = final.get("final_sql")
            canonical_protocol = canonical_protocol and final_canonical
            if include_traces:
                trace[-1]["parsed_as"] = "final"
                trace[-1]["canonical"] = final_canonical
            break

        action, action_canonical = parse_json_v2_tool_call(content)
        if action is None:
            parse_failed = True
            protocol_invalid = True
            if include_traces:
                trace[-1]["parsed_as"] = "parse_failed"
            break
        canonical_protocol = canonical_protocol and action_canonical
        actions.append(action)
        observation = execute_tool(task.db_path, action)
        observation_for_model = compact_execute_observation(action, observation)
        if include_traces:
            trace[-1]["parsed_as"] = "tool_call"
            trace[-1]["canonical"] = action_canonical
            trace[-1]["action"] = action
            trace[-1]["observation"] = observation_for_model
        if action.get("name") == "execute_sql" and observation.get("ok"):
            sql = (action.get("arguments") or {}).get("sql")
            if isinstance(sql, str):
                last_successful_execute_sql = sql
        messages.append({"role": "user", "content": json_v2_tool_result(observation_for_model)})

    if final_sql is None and not parse_failed:
        budget_exceeded = len(actions) >= max_tool_steps
    reward, metrics = compute_sqlite_agent_reward(
        db_path=task.db_path,
        gold_sql=task.gold_sql,
        gold_result=task.gold_result,
        final_sql=final_sql,
        protocol_valid=not protocol_invalid and not parse_failed and canonical_protocol,
        canonical_protocol_valid=not protocol_invalid and not parse_failed and canonical_protocol,
        final_matches_last_execute=final_sql is not None and final_sql == last_successful_execute_sql,
        parse_failed=parse_failed,
        budget_exceeded=budget_exceeded,
        tool_steps=len(actions),
        max_tool_steps=max_tool_steps,
    )
    row = {
        "task_id": task.task_id,
        "db_id": task.db_id,
        "reward": reward,
        "final_sql": final_sql,
        "tool_steps": len(actions),
        **{key: metrics.get(key) for key in [
            "submitted",
            "pred_executable",
            "strict_pass",
            "equivalent_output",
            "protocol_valid",
            "canonical_protocol_valid",
            "parse_failed",
            "budget_exceeded",
            "unsafe_sql",
        ]},
    }
    if include_traces:
        row["trace"] = trace
    return row


def summarize(rows: list[dict[str, Any]], group_size: int) -> dict[str, Any]:
    total = len(rows)
    groups = [rows[i : i + group_size] for i in range(0, len(rows), group_size)]
    variance_groups = sum(len({round(float(row["reward"]), 6) for row in group}) > 1 for group in groups if len(group) == group_size)
    rewards = [float(row["reward"]) for row in rows]
    mean = sum(rewards) / total if total else 0.0
    variance = sum((value - mean) ** 2 for value in rewards) / total if total else 0.0
    return {
        "trajectories": total,
        "groups": len(groups),
        "reward_mean": mean,
        "reward_std": variance**0.5,
        "group_reward_variance_rate": variance_groups / len(groups) if groups else 0.0,
        "strict_or_equiv_pass": sum(bool(row.get("strict_pass") or row.get("equivalent_output")) for row in rows) / total if total else 0.0,
        "finalization_rate": sum(bool(row.get("submitted")) for row in rows) / total if total else 0.0,
        "sql_executable_rate": sum(bool(row.get("pred_executable")) for row in rows) / total if total else 0.0,
        "canonical_protocol_valid_rate": sum(bool(row.get("canonical_protocol_valid")) for row in rows) / total if total else 0.0,
        "parse_failed_rate": sum(bool(row.get("parse_failed")) for row in rows) / total if total else 0.0,
        "budget_exceeded_rate": sum(bool(row.get("budget_exceeded")) for row in rows) / total if total else 0.0,
        "unsafe_sql_rate": sum(bool(row.get("unsafe_sql")) for row in rows) / total if total else 0.0,
        "avg_tool_steps": sum(int(row.get("tool_steps") or 0) for row in rows) / total if total else 0.0,
        "reward_counts": dict(Counter(round(float(row["reward"]), 3) for row in rows)),
    }


def main() -> None:
    global torch
    parser = argparse.ArgumentParser(description="No-update RL dry-run for checkpoint-600 policy.")
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--tasks", default="data/rl/smoke_v1_768/train_tasks.jsonl")
    parser.add_argument("--output", default="logs/rl/dryrun_rollouts.jsonl")
    parser.add_argument("--summary-output", default="logs/rl/dryrun_summary.json")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--group-size", type=int, default=4)
    parser.add_argument("--max-tool-steps", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=192)
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--include-traces", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()

    import torch as torch_module
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch = torch_module
    random.seed(args.seed)
    torch.manual_seed(args.seed)

    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True, local_files_only=args.local_files_only)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
        local_files_only=args.local_files_only,
    )
    model = PeftModel.from_pretrained(model, args.adapter, local_files_only=args.local_files_only)
    model.eval()

    tasks = load_tasks(args.tasks)[: args.limit]
    rows: list[dict[str, Any]] = []
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for task in tasks:
            group = []
            for sample_index in range(args.group_size):
                row = rollout_one(
                    model=model,
                    tokenizer=tokenizer,
                    task=task,
                    max_tool_steps=args.max_tool_steps,
                    max_prompt_tokens=args.max_prompt_tokens,
                    max_new_tokens=args.max_new_tokens,
                    temperature=args.temperature,
                    top_p=args.top_p,
                    include_traces=args.include_traces,
                )
                row["sample_index"] = sample_index
                rows.append(row)
                group.append(row["reward"])
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
            print(json.dumps({"task_id": task.task_id, "rewards": group}, ensure_ascii=False), flush=True)

    summary = summarize(rows, args.group_size)
    Path(args.summary_output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.summary_output).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
