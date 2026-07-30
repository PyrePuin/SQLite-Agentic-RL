from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sqlite_agent_pkg.agent.parser import parse_json_v2_final, parse_json_v2_tool_call
from sqlite_agent_pkg.agent.protocol import json_v2_tool_result, system_message
from sqlite_agent_pkg.data.task_schema import resolve_db_path
from sqlite_agent_pkg.env.sqlite_tools import execute_tool
from sqlite_agent_pkg.rl.reward import compute_sqlite_agent_reward

try:  # Imported only inside THUDM/slime runtime.
    from slime.rollout.sglang_rollout import GenerateState
    from slime.utils.http_utils import post
    from slime.utils.types import Sample
except Exception:  # pragma: no cover
    GenerateState = None
    post = None
    Sample = Any


def render_prompt(question: str) -> str:
    messages = [system_message("json_v2"), {"role": "user", "content": question}]
    return "".join(f"{msg['role'].capitalize()}:\n{msg['content']}\n\n" for msg in messages) + "Assistant:\n"


def compact_json(value: Any, limit: int = 4000) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=repr)
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def sample_metadata(sample: Any) -> dict[str, Any]:
    metadata = _as_dict(getattr(sample, "metadata", None))
    label = _as_dict(getattr(sample, "label", None))
    for key in ("task_id", "db_path", "db_id", "question", "table_names", "gold_sql", "gold_result"):
        if key not in metadata and hasattr(sample, key):
            metadata[key] = getattr(sample, key)
        if key not in metadata and key in label:
            metadata[key] = label[key]
    if "gold_sql" not in metadata:
        metadata["gold_sql"] = label.get("gold_sql") or label.get("ground_truth")
    return metadata


def _first_json_text(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return text.strip()
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
                return text[start : index + 1]
    return text[start:].strip()


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


async def generate(args: Any, sample: Sample, sampling_params: dict[str, Any]) -> Sample:
    """THUDM/slime custom generation entrypoint for V2 four-tool agent rollouts."""
    if GenerateState is None or post is None:
        raise RuntimeError("slime is not installed; generate() must run inside a slime runtime")

    metadata = sample_metadata(sample)
    db_path = resolve_db_path(str(metadata["db_path"]), Path.cwd())
    max_turns = int(os.environ.get("SQLITE_RL_MAX_TOOL_STEPS", "8"))
    observation_limit = int(os.environ.get("SQLITE_RL_OBSERVATION_CHARS", "4000"))
    state = GenerateState(args)
    url = f"http://{args.sglang_router_ip}:{args.sglang_router_port}/generate"

    prompt_text = sample.prompt
    prompt_token_ids = state.tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
    response = ""
    response_token_ids: list[int] = []
    loss_mask: list[int] = []
    actions: list[dict[str, Any]] = []
    final_sql: str | None = None
    last_successful_execute_sql: str | None = None
    parse_failed = False
    protocol_valid = True
    canonical_protocol_valid = True
    budget_exceeded = False

    stop = sampling_params.get("stop") or []
    if isinstance(stop, str):
        stop = [stop]
    sampling_params = {**sampling_params, "stop": list(dict.fromkeys([*stop, "\nObservation:", "\nUser:", "\nAssistant:"]))}

    sample.tokens = list(prompt_token_ids)
    sample.loss_mask = []

    for _ in range(max_turns):
        output = await post(
            url,
            {
                "text": prompt_text + response,
                "sampling_params": sampling_params,
                "return_logprob": True,
                "logprob_start_len": 0,
                "top_logprobs_num": 0,
            },
        )
        if output["meta_info"]["finish_reason"]["type"] == "abort":
            sample.status = Sample.Status.ABORTED
            return sample

        raw_action_text = output["text"]
        action_text = _first_json_text(raw_action_text)
        token_logprobs = output.get("meta_info", {}).get("output_token_logprobs")
        if not token_logprobs:
            sample.status = Sample.Status.ABORTED
            return sample
        action_token_ids = [item[1] for item in token_logprobs]
        action_log_probs = [item[0] for item in token_logprobs]
        response += raw_action_text
        response_token_ids += action_token_ids
        loss_mask += [1] * len(action_token_ids)
        sample.append_response_tokens(args, tokens=action_token_ids, log_probs=action_log_probs, trainable=True, meta_info=output.get("meta_info"))

        final, final_canonical = parse_json_v2_final(action_text)
        if final is not None:
            final_sql = final.get("final_sql")
            canonical_protocol_valid = canonical_protocol_valid and final_canonical
            break

        action, action_canonical = parse_json_v2_tool_call(action_text)
        if action is None:
            parse_failed = True
            protocol_valid = False
            canonical_protocol_valid = False
            observation = {"ok": False, "error": "parse_failed"}
        else:
            canonical_protocol_valid = canonical_protocol_valid and action_canonical
            actions.append(action)
            observation = execute_tool(db_path, action)
            observation = compact_execute_observation(action, observation)
            if action.get("name") == "execute_sql" and observation.get("ok"):
                sql = (action.get("arguments") or {}).get("sql")
                if isinstance(sql, str):
                    last_successful_execute_sql = sql

        observation_text = json_v2_tool_result(observation)
        if len(observation_text) > observation_limit:
            observation_text = observation_text[:observation_limit] + "...<truncated>"
        obs_text = "\nObservation:\n" + observation_text + "\n\nAssistant:\n"
        obs_token_ids = state.tokenizer(obs_text, add_special_tokens=False)["input_ids"]
        response += obs_text
        response_token_ids += obs_token_ids
        loss_mask += [0] * len(obs_token_ids)
        sample.append_response_tokens(args, tokens=obs_token_ids, trainable=False)

        if parse_failed:
            break
    else:
        budget_exceeded = final_sql is None

    final_matches_last_execute = final_sql is not None and final_sql == last_successful_execute_sql
    reward, metrics = compute_sqlite_agent_reward(
        db_path=db_path,
        gold_sql=str(metadata["gold_sql"]),
        gold_result=metadata.get("gold_result"),
        final_sql=final_sql,
        protocol_valid=protocol_valid,
        canonical_protocol_valid=canonical_protocol_valid,
        final_matches_last_execute=final_matches_last_execute,
        parse_failed=parse_failed,
        budget_exceeded=budget_exceeded,
        tool_steps=len(actions),
        max_tool_steps=max_turns,
    )

    metadata.update(
        {
            "sqlite_reward": reward,
            "sqlite_final_metrics": metrics,
            "sqlite_tool_calls": len(actions),
            "sqlite_action_names": [action.get("name") for action in actions],
            "sqlite_final_sql": final_sql,
        }
    )
    sample.metadata = metadata
    sample.tokens = prompt_token_ids + response_token_ids
    sample.response = response
    sample.response_length = len(response_token_ids)
    sample.loss_mask = loss_mask
    sample.status = Sample.Status.COMPLETED
    return sample


async def reward_func(args: Any, sample: Sample, **kwargs: Any) -> float:
    metadata = sample_metadata(sample)
    metrics = _as_dict(metadata.get("sqlite_final_metrics"))
    if "reward" in metrics:
        return float(metrics["reward"])
    return float(metadata.get("sqlite_reward", -0.25))
