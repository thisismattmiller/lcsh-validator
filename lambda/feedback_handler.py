"""Feedback Lambda (Function URL): stores one JSON object in S3 per 'Report incorrect validation'.

POST body: {"heading", "comment", "result": <the validation API response>, "page": <url>}
Adds the caller's IP, user agent, timestamp and an id; writes
  s3://$FEEDBACK_BUCKET/reports/YYYY/MM/DD/<timestamp>-<id>.json
A follow-up POST carrying the returned {"id", "key"} (used when the user adds a comment after the
one-click report) rewrites that same object with the comment, so there is still one file per report.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import uuid

import boto3

BUCKET = os.environ["FEEDBACK_BUCKET"]
MAX_BODY = 2_000_000
MAX_COMMENT = 4000
s3 = boto3.client("s3")


def _response(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json; charset=utf-8"}, "body": json.dumps(body)}


def handler(event, context):
    http = event.get("requestContext", {}).get("http", {})
    if (http.get("method") or "GET").upper() != "POST":
        return _response(200, {"ok": True, "usage": "POST {heading, comment, result}"})
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8", "replace")
    if len(body) > MAX_BODY:
        return _response(413, {"error": "report too large"})
    try:
        data = json.loads(body)
        assert isinstance(data, dict)
    except Exception:  # noqa: BLE001
        return _response(400, {"error": "body must be a JSON object"})
    heading = str(data.get("heading") or "").strip()
    if not heading:
        return _response(400, {"error": "heading is required"})
    now = dt.datetime.now(dt.timezone.utc)
    rid = uuid.uuid4().hex[:12]
    key = f"reports/{now:%Y/%m/%d}/{now:%Y%m%dT%H%M%S}-{rid}.json"
    first_received = now.isoformat(timespec="milliseconds")
    prev_key, prev_id = str(data.get("key") or ""), str(data.get("id") or "")
    if prev_key and prev_id and re.fullmatch(r"reports/\d{4}/\d{2}/\d{2}/\d{8}T\d{6}-" + re.escape(prev_id) + r"\.json", prev_key) \
            and re.fullmatch(r"[0-9a-f]{12}", prev_id):
        key, rid = prev_key, prev_id  # update of an earlier report (comment added)
        try:
            old = json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
            first_received = old.get("received", first_received)
        except Exception:  # noqa: BLE001  (missing object: just write it fresh)
            pass
    report = {
        "id": rid,
        "received": first_received,
        "updated": now.isoformat(timespec="milliseconds"),
        "heading": heading,
        "comment": str(data.get("comment") or "")[:MAX_COMMENT],
        "verdict": (data.get("result") or {}).get("verdict") if isinstance(data.get("result"), dict) else None,
        "cost_usd": ((data.get("result") or {}).get("cost") or {}).get("usd") if isinstance(data.get("result"), dict) else None,
        "result": data.get("result"),
        "page": str(data.get("page") or "")[:500],
        "client": {
            "ip": http.get("sourceIp"),
            "user_agent": http.get("userAgent"),
            "country": (event.get("headers") or {}).get("cloudfront-viewer-country"),
        },
    }
    s3.put_object(Bucket=BUCKET, Key=key, Body=json.dumps(report, ensure_ascii=False).encode("utf-8"),
                  ContentType="application/json")
    return _response(200, {"ok": True, "id": rid, "key": key})
