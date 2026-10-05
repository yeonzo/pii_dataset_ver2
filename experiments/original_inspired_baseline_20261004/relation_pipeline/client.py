"""Responses API transport with explicit model routing, key rotation and budgets."""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

from .common import StageFailure, digest, fail, load_keys, now, read_json, redact
from .schemas import validate

API_URL = "https://api.openai.com/v1/responses"


def build_body(cfg: dict, task: str, system: str, payload: dict, schema: dict) -> dict:
    model = cfg["review_model" if task == "review" else "generation_model"]
    body = {"model": model, "instructions": system,
            "input": [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            "max_output_tokens": cfg["max_output_tokens"][task], "store": False,
            "text": {"format": {"type": "json_schema", "name": task + "_result", "strict": True, "schema": schema}}}
    if model.startswith("gpt-5"):
        body["reasoning"] = {"effort": cfg["review_reasoning_effort"]}
    else:
        body["temperature"] = .65
    return body


class Client:
    def __init__(self, config: dict, store):
        self.config, self.store = config, store
        self.keys = load_keys()
        if not self.keys:
            fail("MISSING_API_KEY", "Set OPENAI_API_KEY_1/2 in environment or private .env", fatal=True)

    def request(self, candidate: str, stage: int, task: str, system: str, payload: dict, schema: dict) -> dict:
        cfg, db = self.config, self.store
        body = build_body(cfg, task, system, payload, schema)
        model, limit = body["model"], body["max_output_tokens"]
        encoded = json.dumps(body, ensure_ascii=False).encode()
        cache_path = self.store.run_dir / "candidates" / candidate / "api" / ("cache_"+digest(body)+".json")
        if cache_path.exists():
            cached_result = read_json(cache_path)
            validate(cached_result,schema)
            db.event(candidate,stage,"llm_response_reused",{"task":task,"input_hash":digest(body)})
            return cached_result
        for retry in range(2):
            usage = db.db.execute("SELECT COUNT(*), COALESCE(SUM(estimated_cost_usd),0) FROM api_calls").fetchone()
            candidate_calls = db.db.execute("SELECT COUNT(*) FROM api_calls WHERE candidate_id=?", (candidate,)).fetchone()[0]
            if candidate_calls >= cfg["max_provider_requests_per_candidate"]:
                fail("CANDIDATE_CALL_LIMIT", "Candidate request cap reached", "STOP_CANDIDATE")
            if usage[0] >= cfg["run_request_budget"]:
                fail("RUN_REQUEST_BUDGET", "Run request budget reached", "STOP_RUN", True)
            pricing = cfg["pricing_per_million_tokens"][model]
            # Byte count is a conservative input upper estimate; reserve one full response.
            reserve = (len(encoded) * pricing["input"] + limit * pricing["output"]) / 1_000_000
            if usage[1] + reserve > cfg["run_cost_budget_usd"]:
                fail("RUN_COST_BUDGET", "Not enough remaining cost budget for the next response", "STOP_RUN", True)
            slot, key = self.keys[usage[0] % len(self.keys)]
            call_id = db.execute("INSERT INTO api_calls(candidate_id,stage,task,model,key_slot,status,started_at,estimated_cost_usd) VALUES(?,?,?,?,?,'running',?,?)", (candidate, stage, task, model, slot, now(), reserve)).lastrowid
            db.save_artifact(candidate, f"api/request_{call_id:05d}.json", {"mode":"live", "task":task, "body":body}, private=True)
            request = urllib.request.Request(API_URL, data=encoded, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=cfg["request_timeout_seconds"]) as response:
                    raw = json.loads(response.read())
                tokens = raw.get("usage") or {}
                ninput = tokens.get("input_tokens", 0)
                cached = (tokens.get("input_tokens_details") or {}).get("cached_tokens", 0)
                noutput = tokens.get("output_tokens", 0)
                cost = ((ninput - cached) * pricing["input"] + cached * pricing["cached_input"] + noutput * pricing["output"]) / 1_000_000
                db.execute("UPDATE api_calls SET status='completed',finished_at=?,input_tokens=?,cached_input_tokens=?,output_tokens=?,estimated_cost_usd=?,request_id=? WHERE id=?", (now(), ninput, cached, noutput, cost, raw.get("id"), call_id))
                db.save_artifact(candidate, f"api/call_{call_id:05d}.json", raw, private=True)
                if raw.get("status") != "completed":
                    fail("RESPONSE_INCOMPLETE", str(raw.get("incomplete_details") or raw.get("error") or raw.get("status")), "RETRY_RESPONSE")
                texts = []
                for item in raw.get("output", []):
                    for part in item.get("content", []):
                        if part.get("type") == "refusal":
                            fail("MODEL_REFUSAL", part.get("refusal", "refused"), "STOP_CANDIDATE")
                        if part.get("type") == "output_text":
                            texts.append(part["text"])
                try:
                    result = json.loads("".join(texts))
                except (ValueError, TypeError):
                    fail("RESPONSE_JSON", "Response contains no valid JSON object", "RETRY_RESPONSE")
                try:
                    validate(result, schema)
                except StageFailure as exc:
                    if task == "review" and isinstance(result, dict):
                        exc.review_response = result
                    raise
                db.save_artifact(candidate, "api/"+cache_path.name, result, private=True)
                return result
            except urllib.error.HTTPError as exc:
                try:
                    error = json.loads(exc.read()).get("error", {})
                except ValueError:
                    error = {}
                code = str(error.get("code") or f"HTTP_{exc.code}")
                message = redact(error.get("message", code))
                db.execute("UPDATE api_calls SET status='error',finished_at=?,error_code=?,estimated_cost_usd=0 WHERE id=?", (now(), code, call_id))
                db.event(candidate, stage, "provider_error", {"code": code, "message": message, "key_slot": slot})
                transient = exc.code in (429, 500, 502, 503, 504) and code not in ("insufficient_quota", "billing_hard_limit_reached")
                if transient and retry == 0:
                    time.sleep(2)
                    continue
                fail("PROVIDER_" + code, message, "STOP_RUN" if not transient else "STOP_CANDIDATE", not transient)
            except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
                db.execute("UPDATE api_calls SET status='error',finished_at=?,error_code='NETWORK_ERROR' WHERE id=?", (now(), call_id))
                if retry == 0:
                    time.sleep(2)
                    continue
                fail("NETWORK_ERROR", redact(exc), "STOP_CANDIDATE")
            except (json.JSONDecodeError, UnicodeDecodeError):
                db.execute("UPDATE api_calls SET status='error',finished_at=?,error_code='INVALID_PROVIDER_JSON' WHERE id=?", (now(), call_id))
                fail("INVALID_PROVIDER_JSON", "Provider response was not readable JSON; cost reservation retained", "RETRY_RESPONSE")
        raise AssertionError("unreachable")
