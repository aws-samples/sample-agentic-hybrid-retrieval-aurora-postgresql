from __future__ import annotations
import http.client
import json
import os
from urllib.parse import urlsplit

API_URL = os.environ.get("RETRIEVAL_API_URL", "").rstrip("/")
ALLOWED_API_SCHEMES = {"http", "https"}


def _parse_api_url():
    if not API_URL:
        return None, "RETRIEVAL_API_URL is not configured"

    parsed = urlsplit(API_URL)
    if parsed.scheme.lower() not in ALLOWED_API_SCHEMES or not parsed.hostname:
        return None, "RETRIEVAL_API_URL must use http or https with a valid host"
    if parsed.username or parsed.password:
        return None, "RETRIEVAL_API_URL must not include credentials"
    if parsed.query or parsed.fragment:
        return None, "RETRIEVAL_API_URL must not include query parameters or fragments"

    return parsed, None


def _post(path: str, payload: dict):
    parsed, error = _parse_api_url()
    if error:
        return {"error": error}

    data = json.dumps(payload).encode("utf-8")
    connection_class = http.client.HTTPSConnection if parsed.scheme.lower() == "https" else http.client.HTTPConnection
    connection = connection_class(parsed.hostname, port=parsed.port, timeout=30)
    request_path = f"{parsed.path.rstrip('/')}{path}"

    try:
        connection.request("POST", request_path, body=data, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        body = response.read().decode("utf-8")
    finally:
        connection.close()

    return json.loads(body)


def lambda_handler(event, context):
    action = event.get("apiPath", "")
    props = event.get("requestBody", {}).get("content", {}).get("application/json", {}).get("properties", [])
    payload = {p.get("name"): p.get("value") for p in props}

    if action.endswith("/searchEvidence"):
        result = _post("/v1/search", {
            "query": payload.get("query", ""),
            "source_systems": payload.get("sourceSystems"),
            "project_key": payload.get("projectKey"),
            "limit": int(payload.get("limit") or 8),
        })
    elif action.endswith("/answerQuestion"):
        result = _post("/v1/agent/answer", {
            "question": payload.get("question", ""),
            "limit": int(payload.get("limit") or 8),
        })
    else:
        result = {"error": f"Unknown action {action}"}

    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup"),
            "apiPath": event.get("apiPath"),
            "httpMethod": event.get("httpMethod"),
            "httpStatusCode": 200,
            "responseBody": {"application/json": {"body": json.dumps(result)}}
        }
    }
