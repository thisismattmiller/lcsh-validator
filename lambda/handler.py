"""AWS Lambda entry point (Function URL, payload v2) for the LCSH validator.

POST / with JSON {"heading": "...", "effort": "low|medium|high", "facts_only": false}
GET  /?heading=...
GET  /            -> health / config

Everything under /var/task is read-only in Lambda, so the two SQLite files that are written to
(the id.loc.gov name cache and the rules FTS index, which is rebuilt when its mtime is older than
the rule files) are copied to /tmp at cold start and the package is pointed at them through
LCSH_NAME_CACHE / LCSH_RULES_FTS before it is imported.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import time
from pathlib import Path

TASK_ROOT = Path(os.environ.get("LAMBDA_TASK_ROOT", Path(__file__).resolve().parent))
TMP = Path("/tmp/lcsh")
TMP.mkdir(parents=True, exist_ok=True)
for name, var in (("name_cache.sqlite", "LCSH_NAME_CACHE"), ("rules.sqlite", "LCSH_RULES_FTS")):
    src = TASK_ROOT / "data/derived" / name
    dst = TMP / name
    if src.exists() and not dst.exists():
        shutil.copy(src, dst)  # copy sets mtime to now, so the FTS index is never considered stale
    os.environ.setdefault(var, str(dst))

from lcsh_validator.agent import MODEL, Validator  # noqa: E402  (after the env setup above)
from lcsh_validator.parse import parse_heading  # noqa: E402

MAX_HEADING_CHARS = int(os.environ.get("LCSH_MAX_HEADING", "400"))
EFFORTS = {"low", "medium", "high"}
_validator: Validator | None = None


def get_validator() -> Validator:
    global _validator
    if _validator is None:
        _validator = Validator(model=os.environ.get("LCSH_MODEL", MODEL))
    return _validator


def _response(status: int, body: dict) -> dict:
    # CORS headers come from the Function URL's CORS configuration; adding them here too would
    # duplicate them and browsers reject duplicated Access-Control-Allow-Origin values.
    return {"statusCode": status, "headers": {"content-type": "application/json; charset=utf-8"},
            "body": json.dumps(body, ensure_ascii=False, default=str)}


def _request(event: dict) -> tuple[str, dict]:
    method = (event.get("requestContext", {}).get("http", {}).get("method") or "GET").upper()
    params = dict(event.get("queryStringParameters") or {})
    body = event.get("body")
    if body:
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8", "replace")
        try:
            data = json.loads(body)
            if isinstance(data, dict):
                params.update(data)
        except json.JSONDecodeError:
            params["heading"] = body
    return method, params


def handler(event, context):
    t0 = time.time()
    method, params = _request(event)
    heading = (params.get("heading") or "").strip()
    if not heading:
        # health check doubles as a warm-up: touch the database pages and build the cached system prompt
        # so the first real request on a fresh container does not pay for lazily loaded image layers
        v = get_validator()
        v.analyzer.analyze(parse_heading("Music--Ontario--Toronto"))
        v.system_blocks()
        return _response(200, {"ok": True, "model": v.model, "usage": "POST {\"heading\": \"Taxation--France--Paris\", \"effort\": \"medium\"}",
                               "max_heading_chars": MAX_HEADING_CHARS, "warmup_secs": round(time.time() - t0, 2)})
    if len(heading) > MAX_HEADING_CHARS:
        return _response(400, {"error": f"heading longer than {MAX_HEADING_CHARS} characters"})
    effort = str(params.get("effort") or "medium").lower()
    if effort not in EFFORTS:
        return _response(400, {"error": f"effort must be one of {sorted(EFFORTS)}"})
    v = get_validator()
    try:
        if params.get("facts_only"):
            facts = v.analyzer.analyze(parse_heading(heading))
            return _response(200, {"heading": heading, "facts": facts, "elapsed": round(time.time() - t0, 2)})
        v.effort = effort
        res = v.validate(heading)
    except Exception as e:  # noqa: BLE001
        return _response(500, {"error": f"{type(e).__name__}: {e}", "heading": heading})
    out = res.full_dict()
    out["effort"] = effort
    out["model"] = v.model
    out["elapsed"] = round(time.time() - t0, 2)
    return _response(200, out)
