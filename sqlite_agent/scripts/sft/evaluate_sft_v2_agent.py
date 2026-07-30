from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

torch: Any = None

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlite_agent_pkg.agent.parser import parse_json_v2_final, parse_json_v2_tool_call
from sqlite_agent_pkg.agent.protocol import json_v2_tool_result, system_message
from sqlite_agent_pkg.data.task_schema import load_tasks
from sqlite_agent_pkg.env.sqlite_tools import execute_tool
from sqlite_agent_pkg.env.verifier import cache_gold_result, verify_sql


def first_json_span(text: str) -> tuple[int, int, dict[str, Any]] | None:
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
                try:
                    obj = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return None
                return (start, index + 1, obj) if isinstance(obj, dict) else None
    return None


def recover_first_json_object(text: str) -> dict[str, Any] | None:
    span = first_json_span(text)
    return span[2] if span is not None else None


def trim_to_first_json_object(text: str) -> tuple[str, bool, int]:
    span = first_json_span(text)
    if span is None:
        return text, False, 0
    start, end, _ = span
    trimmed = text[start:end]
    leading_or_trailing = text[:start].strip() or text[end:].strip()
    return trimmed, bool(leading_or_trailing), len(text[end:])


class StopAfterFirstJson:
    def __init__(self, tokenizer: Any, prompt_length: int):
        self.tokenizer = tokenizer
        self.prompt_length = prompt_length

    def __call__(self, input_ids: Any, scores: Any, **kwargs: Any) -> bool:
        generated = self.tokenizer.decode(input_ids[0][self.prompt_length :], skip_special_tokens=True)
        return first_json_span(generated) is not None


def normalize_raw_action(obj: dict[str, Any]) -> dict[str, Any] | None:
    if "final_sql" in obj or "sql" in obj and "name" not in obj:
        return None
    name = obj.get("name") or obj.get("tool") or obj.get("function")
    arguments = obj.get("arguments")
    if arguments is None:
        arguments = obj.get("args")
    if arguments is None:
        arguments = obj.get("parameters")
    if not isinstance(name, str):
        return None
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return None
    return {"name": name, "arguments": arguments}


def normalize_raw_final(obj: dict[str, Any]) -> dict[str, Any] | None:
    final_sql = obj.get("final_sql")
    if final_sql is None:
        final_sql = obj.get("sql")
    if not isinstance(final_sql, str):
        return None
    answer = obj.get("answer", "")
    return {"final_sql": final_sql, "answer": str(answer)}


def render_messages(messages: list[dict[str, str]]) -> str:
    return "".join(f"{msg['role'].capitalize()}:\n{msg['content']}\n\n" for msg in messages) + "Assistant:\n"


def compact(text: str, limit: int = 1000) -> str:
    return " ".join(text.split())[:limit]


def setup_wandb_metrics(wandb_module: Any, prefix: str) -> None:
    wandb_module.define_metric("train/global_step")
    wandb_module.define_metric(f"{prefix}/*", step_metric="train/global_step")


def generate_one(
    *,
    model: Any,
    tokenizer: Any,
    messages: list[dict[str, str]],
    max_prompt_tokens: int,
    max_new_tokens: int,
    stop_after_first_json: bool,
) -> str:
    prompt = render_messages(messages)
    encoded = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=max_prompt_tokens).to(model.device)
    stopping_criteria = None
    if stop_after_first_json:
        from transformers import StoppingCriteriaList

        stopping_criteria = StoppingCriteriaList([StopAfterFirstJson(tokenizer, encoded.input_ids.shape[1])])
    with torch.no_grad():
        output = model.generate(
            **encoded,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id,
            stopping_criteria=stopping_criteria,
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
    protocol: str,
    stop_after_first_json: bool,
) -> dict[str, Any]:
    messages: list[dict[str, str]] = [system_message(protocol), {"role": "user", "content": task.question}]
    actions: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    generations: list[str] = []
    parse_failed = False
    protocol_invalid = False
    canonical_protocol = True
    compatibility_parsed = False
    overgenerated = False
    trimmed_tail_chars = 0
    final: dict[str, Any] | None = None
    final_sql: str | None = None
    last_successful_execute_sql: str | None = None

    for _ in range(max_tool_steps):
        content = generate_one(
            model=model,
            tokenizer=tokenizer,
            messages=messages,
            max_prompt_tokens=max_prompt_tokens,
            max_new_tokens=max_new_tokens,
            stop_after_first_json=stop_after_first_json,
        )
        raw_content = content
        content, content_overgenerated, tail_chars = trim_to_first_json_object(raw_content)
        overgenerated = overgenerated or content_overgenerated
        trimmed_tail_chars += tail_chars
        generations.append(compact(raw_content))
        messages.append({"role": "assistant", "content": content})
        if content_overgenerated:
            protocol_invalid = True
            canonical_protocol = False
            compatibility_parsed = True

        final, final_canonical = parse_json_v2_final(content)
        if final is not None:
            canonical_protocol = canonical_protocol and final_canonical
            compatibility_parsed = compatibility_parsed or not final_canonical
        if final is None:
            raw = recover_first_json_object(content)
            if raw is not None:
                final = normalize_raw_final(raw)
                if final is not None:
                    protocol_invalid = True
                    canonical_protocol = False
                    compatibility_parsed = True
        if final is not None:
            final_sql = final.get("final_sql")
            if final_sql != last_successful_execute_sql:
                protocol_invalid = True
                canonical_protocol = False
            break

        action, action_canonical = parse_json_v2_tool_call(content)
        if action is not None:
            canonical_protocol = canonical_protocol and action_canonical
            compatibility_parsed = compatibility_parsed or not action_canonical
        if action is None:
            raw = recover_first_json_object(content)
            if raw is not None:
                action = normalize_raw_action(raw)
                if action is not None:
                    protocol_invalid = True
                    canonical_protocol = False
                    compatibility_parsed = True
        if action is None:
            parse_failed = True
            observations.append({"ok": False, "error": "parse_failed"})
            result_text = json_v2_tool_result({"ok": False, "error": "parse_failed"})
            messages.append({"role": "user", "content": result_text})
            break

        actions.append(action)
        observation = execute_tool(task.db_path, action)
        observations.append(observation)
        if action.get("name") == "execute_sql" and observation.get("ok"):
            args = action.get("arguments") or {}
            sql = args.get("sql")
            if isinstance(sql, str):
                last_successful_execute_sql = sql
        result_text = json_v2_tool_result(observation)
        messages.append({"role": "user", "content": result_text})

    if final_sql and task.gold_result:
        verify = verify_sql(task.db_path, final_sql, task.gold_result)
    elif final_sql:
        gold = cache_gold_result(task.db_path, task.gold_sql)
        verify = verify_sql(task.db_path, final_sql, gold) if gold.get("ok") else {"correct": False, "gold_error": gold}
    else:
        verify = None

    submitted = final_sql is not None
    executable = bool(verify and verify.get("pred_executable"))
    strict_pass = bool(verify and verify.get("header_exact") and verify.get("value_exact"))
    equivalent_output = bool(verify and verify.get("value_exact"))
    budget_exceeded = not submitted and len(actions) >= max_tool_steps

    if parse_failed:
        failure_type = "parse_failed"
    elif protocol_invalid:
        failure_type = "protocol_invalid"
    elif budget_exceeded:
        failure_type = "budget_exceeded"
    elif not submitted:
        failure_type = "no_final"
    elif not executable:
        failure_type = "invalid_sql"
    elif not equivalent_output:
        failure_type = "wrong_result"
    else:
        failure_type = "pass"

    tool_counts = Counter(action.get("name", "unknown") for action in actions)
    return {
        "task_id": task.task_id,
        "db_id": task.db_id,
        "question": task.question,
        "gold_sql": task.gold_sql,
        "difficulty": getattr(task, "answer_spec", None) or {},
        "actions": actions,
        "observations": observations,
        "generations": generations,
        "final": final,
        "final_sql": final_sql,
        "last_successful_execute_sql": last_successful_execute_sql,
        "verify": verify,
        "submitted": submitted,
        "executable": executable,
        "strict_pass": strict_pass,
        "equivalent_output": equivalent_output,
        "protocol_valid": not protocol_invalid and not parse_failed and canonical_protocol,
        "canonical_protocol_valid": not protocol_invalid and not parse_failed and canonical_protocol,
        "compatibility_parsed": compatibility_parsed,
        "overgenerated": overgenerated,
        "trimmed_tail_chars": trimmed_tail_chars,
        "unrecoverable_parse_failed": parse_failed,
        "parse_failed": parse_failed,
        "budget_exceeded": budget_exceeded,
        "tool_steps": len(actions),
        "tool_counts": dict(tool_counts),
        "failure_type": failure_type,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    if total == 0:
        return {"tasks": 0}
    by_db: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_failure = Counter(row["failure_type"] for row in rows)
    tool_counts = Counter()
    for row in rows:
        by_db[str(row["db_id"])].append(row)
        tool_counts.update(row.get("tool_counts", {}))
    total_tool_steps = sum(int(row["tool_steps"]) for row in rows)
    return {
        "tasks": total,
        "strict_pass": sum(row["strict_pass"] for row in rows) / total,
        "equivalent_output": sum(row["equivalent_output"] for row in rows) / total,
        "strict_or_equiv_pass": sum(row["strict_pass"] or row["equivalent_output"] for row in rows) / total,
        "finalization_rate": sum(row["submitted"] for row in rows) / total,
        "sql_executable_rate": sum(row["executable"] for row in rows) / total,
        "protocol_valid_rate": sum(row["protocol_valid"] for row in rows) / total,
        "canonical_protocol_valid_rate": sum(row.get("canonical_protocol_valid", False) for row in rows) / total,
        "compatibility_parse_rate": sum(row.get("compatibility_parsed", False) for row in rows) / total,
        "overgenerated_rate": sum(row.get("overgenerated", False) for row in rows) / total,
        "avg_trimmed_tail_chars": sum(int(row.get("trimmed_tail_chars", 0)) for row in rows) / total,
        "unrecoverable_parse_failed_rate": sum(row.get("unrecoverable_parse_failed", row["parse_failed"]) for row in rows) / total,
        "parse_failed_rate": sum(row["parse_failed"] for row in rows) / total,
        "budget_exceeded_rate": sum(row["budget_exceeded"] for row in rows) / total,
        "wrong_result_rate": by_failure.get("wrong_result", 0) / total,
        "invalid_sql_rate": by_failure.get("invalid_sql", 0) / total,
        "avg_tool_steps": total_tool_steps / total,
        "preview_usage_rate": sum(1 for row in rows if row.get("tool_counts", {}).get("preview_rows", 0) > 0) / total,
        "failure_types": dict(sorted(by_failure.items())),
        "tool_counts": dict(sorted(tool_counts.items())),
        "per_db_strict_or_equiv_pass": {
            db_id: sum(row["strict_pass"] or row["equivalent_output"] for row in items) / len(items)
            for db_id, items in sorted(by_db.items())
        },
    }


def main() -> None:
    global torch
    parser = argparse.ArgumentParser(description="Evaluate the V2 JSON-protocol four-tool SQLite agent with real rollouts.")
    parser.add_argument("--base-model", default="Qwen/Qwen2.5-Coder-3B-Instruct")
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary-output")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-tool-steps", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=192)
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--no-stop-after-first-json", action="store_true")
    parser.add_argument("--wandb-project")
    parser.add_argument("--wandb-run-name")
    parser.add_argument("--wandb-run-id")
    parser.add_argument("--wandb-resume", default="allow")
    parser.add_argument("--wandb-step", type=int)
    parser.add_argument("--wandb-prefix", default="eval_mini")
    parser.add_argument("--protocol", choices=["json_v2"], default="json_v2")
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()

    import torch as torch_module
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch = torch_module

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

    tasks = load_tasks(args.tasks)
    if args.shuffle:
        rng = random.Random(args.seed)
        rng.shuffle(tasks)
    tasks = tasks[: args.limit]

    rows = []
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for task in tasks:
            row = rollout_one(
                model=model,
                tokenizer=tokenizer,
                task=task,
                max_tool_steps=args.max_tool_steps,
                max_prompt_tokens=args.max_prompt_tokens,
                max_new_tokens=args.max_new_tokens,
                protocol=args.protocol,
                stop_after_first_json=not args.no_stop_after_first_json,
            )
            rows.append(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(
                json.dumps(
                    {
                        "task_id": task.task_id,
                        "submitted": row["submitted"],
                        "strict": row["strict_pass"],
                        "equiv": row["equivalent_output"],
                        "failure": row["failure_type"],
                        "steps": row["tool_steps"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    summary = summarize(rows)
    summary["output"] = args.output
    summary["tasks_file"] = args.tasks
    if args.summary_output:
        Path(args.summary_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.summary_output).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.wandb_project:
        import wandb

        run = wandb.init(
            project=args.wandb_project,
            name=args.wandb_run_name,
            id=args.wandb_run_id,
            resume=args.wandb_resume,
            config=vars(args),
        )
        setup_wandb_metrics(wandb, args.wandb_prefix)
        metrics = {f"{args.wandb_prefix}/{key}": value for key, value in summary.items() if isinstance(value, (int, float))}
        if args.wandb_step is not None:
            metrics["train/global_step"] = args.wandb_step
        wandb.log(metrics)
        run.finish()
    print(json.dumps({"summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
