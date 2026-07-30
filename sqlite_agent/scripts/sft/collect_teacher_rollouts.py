from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlite_agent_pkg.agent.protocol import system_message
from sqlite_agent_pkg.agent.rollout import rollout
from sqlite_agent_pkg.env.verifier import verify_sql


API_URL = "https://api.deepseek.com/chat/completions"


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]], *, append: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def choose_question(
    row: dict[str, Any],
    *,
    rng: random.Random,
    english_rate: float,
    language_mode: str,
) -> tuple[str, str] | None:
    question_zh = row.get("question_zh")
    question_en = row.get("question_en")
    if language_mode == "en_only":
        if question_en:
            return "en", question_en
        return None
    if language_mode == "zh_only":
        if question_zh:
            return "zh", question_zh
        return None
    if question_zh and question_en:
        return ("en", question_en) if rng.random() < english_rate else ("zh", question_zh)
    if question_zh:
        return "zh", question_zh
    if question_en:
        return "en", question_en
    return None


def load_completed_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    seen: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            task_id = row.get("task_id")
            if task_id:
                seen.add(str(task_id))
    return seen


def make_generate(
    *,
    api_key: str,
    model: str,
    temperature: float,
    reasoning_effort: str,
    timeout_sec: float,
    max_retries: int,
    retry_sleep_sec: float,
    response_format_json: bool,
) -> Callable[[list[dict[str, str]]], str]:
    def generate(messages: list[dict[str, str]]) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
            "reasoning_effort": reasoning_effort,
        }
        if response_format_json:
            payload["response_format"] = {"type": "json_object"}
        for attempt in range(max_retries + 1):
            req = urllib.request.Request(
                API_URL,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout_sec) as response:
                    body = json.loads(response.read().decode("utf-8"))
                message = body["choices"][0]["message"]
                content = message.get("content", "")
                if isinstance(content, list):
                    text_parts = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_parts.append(str(item.get("text", "")))
                    content = "\n".join(part for part in text_parts if part)
                return str(content)
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError):
                if attempt >= max_retries:
                    raise
                time.sleep(retry_sleep_sec * (attempt + 1))
        raise RuntimeError("unreachable")

    return generate


def collect_one(
    *,
    row: dict[str, Any],
    task_id: str,
    language: str,
    question: str,
    generate: Callable[[list[dict[str, str]]], str],
    model: str,
    max_steps: int,
) -> dict[str, Any]:
    messages = [system_message(), {"role": "user", "content": question}]
    started = time.time()
    error_text: str | None = None
    rollout_result: dict[str, Any] | None = None
    verify_result: dict[str, Any] | None = None
    try:
        rollout_result = rollout(
            db_path=row["db_path"],
            messages=messages,
            generate=generate,
            max_steps=max_steps,
        )
        final = rollout_result.get("final") or {}
        final_sql = final.get("final_sql") or final.get("sql") or ""
        if final_sql:
            verify_result = verify_sql(row["db_path"], str(final_sql), row.get("gold_result") or {})
    except Exception as exc:
        error_text = repr(exc)

    elapsed = round(time.time() - started, 3)
    ok = bool(verify_result and verify_result.get("correct"))
    return {
        "task_id": task_id,
        "pool_id": row.get("pool_id"),
        "db_id": row["db_id"],
        "language": language,
        "question": question,
        "db_path": row["db_path"],
        "gold_sql": row["gold_sql"],
        "gold_result": row.get("gold_result"),
        "answer_spec": row.get("answer_spec"),
        "rollout": rollout_result,
        "verify": verify_result,
        "success": ok,
        "error": error_text,
        "elapsed_sec": elapsed,
        "model": model,
        "max_steps": max_steps,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect real teacher rollouts through the SQLite agent environment.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="deepseek-v4-pro")
    parser.add_argument("--english-rate", type=float, default=0.2)
    parser.add_argument("--language-mode", choices=["mixed", "en_only", "zh_only"], default="mixed")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--timeout-sec", type=float, default=120.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--retry-sleep-sec", type=float, default=3.0)
    parser.add_argument("--sleep-between-tasks-sec", type=float, default=0.0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--no-response-format-json", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is required")

    rng = random.Random(args.seed)
    tasks = iter_jsonl(Path(args.input))

    output_path = Path(args.output)
    completed_ids = load_completed_ids(output_path) if args.resume else set()
    generate = make_generate(
        api_key=api_key,
        model=args.model,
        temperature=args.temperature,
        reasoning_effort=args.reasoning_effort,
        timeout_sec=args.timeout_sec,
        max_retries=args.max_retries,
        retry_sleep_sec=args.retry_sleep_sec,
        response_format_json=not args.no_response_format_json,
    )

    jobs: list[tuple[dict[str, Any], str, str, str]] = []
    for row in tasks:
        task_id = str(row.get("pool_id") or row.get("task_id") or "")
        if task_id in completed_ids:
            continue
        choice = choose_question(row, rng=rng, english_rate=args.english_rate, language_mode=args.language_mode)
        if choice is None:
            continue
        if args.limit is not None and len(jobs) >= args.limit:
            break
        language, question = choice
        jobs.append((row, task_id, language, question))

    processed = 0
    success = 0
    if args.workers <= 1:
        for row, task_id, language, question in jobs:
            record = collect_one(
                row=row,
                task_id=task_id,
                language=language,
                question=question,
                generate=generate,
                model=args.model,
                max_steps=args.max_steps,
            )
            append_jsonl(output_path, record)
            processed += 1
            success += int(record["success"])
            print(
                json.dumps(
                    {
                        "processed": processed,
                        "success": success,
                        "task_id": task_id,
                        "db_id": row["db_id"],
                        "language": language,
                        "ok": record["success"],
                        "elapsed_sec": record["elapsed_sec"],
                        "stop_reason": ((record.get("rollout") or {}).get("stop_reason")),
                        "error": record["error"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if args.sleep_between_tasks_sec > 0:
                time.sleep(args.sleep_between_tasks_sec)
        return

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_job = {
            executor.submit(
                collect_one,
                row=row,
                task_id=task_id,
                language=language,
                question=question,
                generate=generate,
                model=args.model,
                max_steps=args.max_steps,
            ): (row, task_id, language)
            for row, task_id, language, question in jobs
        }
        for future in as_completed(future_to_job):
            row, task_id, language = future_to_job[future]
            record = future.result()
            append_jsonl(output_path, record)
            processed += 1
            success += int(record["success"])
            print(
                json.dumps(
                    {
                        "processed": processed,
                        "success": success,
                        "task_id": task_id,
                        "db_id": row["db_id"],
                        "language": language,
                        "ok": record["success"],
                        "elapsed_sec": record["elapsed_sec"],
                        "stop_reason": ((record.get("rollout") or {}).get("stop_reason")),
                        "error": record["error"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
