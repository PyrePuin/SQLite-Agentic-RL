from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


API_URL = "https://api.deepseek.com/chat/completions"
VERDICTS = {"prefer_gold", "prefer_prediction", "both_ok_but_different", "both_bad", "uncertain"}


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


def summarize_result(result: dict[str, Any] | None, *, max_rows: int = 5) -> dict[str, Any] | None:
    if not result:
        return None
    out = {
        "ok": result.get("ok"),
        "columns": result.get("columns"),
        "row_count": result.get("row_count"),
        "rows_preview": (result.get("rows") or [])[:max_rows],
        "error": result.get("error"),
    }
    if "sql" in result:
        out["sql"] = result.get("sql")
    return out


def make_messages(row: dict[str, Any]) -> list[dict[str, str]]:
    pred_sql = (((row.get("rollout") or {}).get("final") or {}).get("final_sql") or "")
    pred_result = ((row.get("verify") or {}).get("pred_result")) or None
    gold_result = row.get("gold_result")
    user_payload = {
        "question": row.get("question"),
        "language": row.get("language"),
        "db_id": row.get("db_id"),
        "gold_sql": row.get("gold_sql"),
        "gold_result_summary": summarize_result(gold_result),
        "pred_sql": pred_sql,
        "pred_result_summary": summarize_result(pred_result),
        "strict_verify": row.get("verify"),
    }
    system = (
        "You are auditing a Text-to-SQL example where strict execution matching may disagree with the natural-language question. "
        "Judge whether the gold SQL or the predicted SQL better satisfies the question semantics. "
        "Be conservative. Prefer the prediction only if it clearly matches the question better than the gold SQL. "
        "Return only JSON with keys verdict, confidence, reason_short, reason. "
        "Allowed verdict values: prefer_gold, prefer_prediction, both_ok_but_different, both_bad, uncertain."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
    ]


def call_judge(
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout_sec: float,
    max_retries: int,
    retry_sleep_sec: float,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0.0,
        "reasoning_effort": "medium",
        "response_format": {"type": "json_object"},
    }
    last_error: Exception | None = None
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
            message = body["choices"][0]["message"]["content"]
            if isinstance(message, list):
                message = "\n".join(
                    str(item.get("text", ""))
                    for item in message
                    if isinstance(item, dict) and item.get("type") == "text"
                )
            obj = json.loads(str(message))
            verdict = str(obj.get("verdict", "uncertain"))
            if verdict not in VERDICTS:
                obj["verdict"] = "uncertain"
            return obj
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            time.sleep(retry_sleep_sec * (attempt + 1))
    raise RuntimeError(f"judge_request_failed: {last_error!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit strict-fail rollout rows with an LLM judge.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="deepseek-v4-pro")
    parser.add_argument("--timeout-sec", type=float, default=120.0)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--retry-sleep-sec", type=float, default=3.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--strict-fail-only", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is required")

    rows = iter_jsonl(Path(args.input))
    if args.strict_fail_only:
        rows = [row for row in rows if not row.get("success")]
    if args.limit is not None:
        rows = rows[: args.limit]

    for idx, row in enumerate(rows, start=1):
        started = time.time()
        error_text = None
        judge = None
        try:
            judge = call_judge(
                api_key=api_key,
                model=args.model,
                messages=make_messages(row),
                timeout_sec=args.timeout_sec,
                max_retries=args.max_retries,
                retry_sleep_sec=args.retry_sleep_sec,
            )
        except Exception as exc:
            error_text = repr(exc)
        record = {
            "task_id": row.get("task_id"),
            "db_id": row.get("db_id"),
            "question": row.get("question"),
            "language": row.get("language"),
            "gold_sql": row.get("gold_sql"),
            "pred_sql": (((row.get("rollout") or {}).get("final") or {}).get("final_sql") or ""),
            "strict_success": row.get("success"),
            "judge": judge,
            "judge_error": error_text,
            "elapsed_sec": round(time.time() - started, 3),
            "source_input": args.input,
        }
        append_jsonl(Path(args.output), record)
        print(
            json.dumps(
                {
                    "processed": idx,
                    "task_id": record["task_id"],
                    "strict_success": record["strict_success"],
                    "verdict": None if judge is None else judge.get("verdict"),
                    "judge_error": error_text,
                    "elapsed_sec": record["elapsed_sec"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
