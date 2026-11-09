"""A Bedrock call that never answers ends a search in seconds, with an instruction to rerun.

On the 9 November test event one reranking call sent no response; the shared client's
60-second read timeout held Lab 1's handoff for 61 s before its retry answered. Search
calls (the query embedding and reranking) now wait 10 s per attempt, model calls keep
60 s, and a search that still gets no answer says what happened and what to do.
"""

from __future__ import annotations

import io
import json
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar
from urllib.error import HTTPError

import boto3
import pytest
from botocore.exceptions import ReadTimeoutError
from fastapi import HTTPException

from scripts.prove_lab import LabValidationError, _request
from service import bedrock, main
from service.config import get_settings
from service.embeddings import BedrockEmbeddingProvider
from service.model_runtime import BedrockTimeoutError, model_runtime_error
from service.models import SearchRequest
from service.rerank import BedrockReranker

RERUN = (
    "This search stopped: Amazon Bedrock's reranking call did not answer within 10 "
    "seconds, even after retrying. Nothing is wrong with your work. Run the same "
    "command or search again."
)
#: How long the stand-in endpoint holds a request before giving up on the client.
HOLD_SECONDS = 5


class _Unanswered(BaseHTTPRequestHandler):
    """Reads each request and never answers it, like the event's hung call."""

    requests: ClassVar[list[str]] = []
    release: ClassVar[threading.Event] = threading.Event()

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers["Content-Length"]))
        type(self).requests.append(self.path)
        type(self).release.wait(HOLD_SECONDS)

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture
def unanswered_endpoint(monkeypatch):
    """Point every Bedrock client at a local endpoint that never answers."""
    _Unanswered.requests = []
    _Unanswered.release = threading.Event()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Unanswered)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{server.server_address[1]}"
    real_client = boto3.client

    def local_client(service_name, *args, **kwargs):
        kwargs["endpoint_url"] = endpoint
        kwargs.setdefault("aws_access_key_id", "test")
        kwargs.setdefault("aws_secret_access_key", "test")
        return real_client(service_name, *args, **kwargs)

    monkeypatch.setattr(boto3, "client", local_client)
    monkeypatch.setattr(bedrock, "_clients", {})
    monkeypatch.setattr(bedrock, "SEARCH_READ_TIMEOUT_SECONDS", 0.3)
    two_attempts = replace(get_settings(), bedrock_max_attempts=2)
    monkeypatch.setattr(bedrock, "get_settings", lambda: two_attempts)
    yield _Unanswered
    _Unanswered.release.set()
    server.shutdown()


def test_search_calls_wait_ten_seconds_and_model_calls_sixty():
    search = bedrock.client_config(search_step=True)
    model = bedrock.client_config()

    assert (search.read_timeout, model.read_timeout) == (10, 60)
    assert search.retries == model.retries
    assert search.connect_timeout == model.connect_timeout


def test_a_search_client_is_separate_from_the_model_client(monkeypatch):
    monkeypatch.setattr(bedrock, "_clients", {})

    search = bedrock.get_bedrock_client(
        "bedrock-runtime", "us-east-1", search_step=True
    )
    model = bedrock.get_bedrock_client("bedrock-runtime", "us-east-1")

    assert search is not model
    assert search.meta.config.read_timeout == 10
    assert model.meta.config.read_timeout == 60
    assert (
        bedrock.get_bedrock_client("bedrock-runtime", "us-east-1", search_step=True)
        is search
    )


def test_the_rerun_instruction_is_the_sentence_the_guide_quotes():
    assert bedrock.search_timeout_message("reranking") == RERUN


@pytest.mark.parametrize("step", ["reranking", "embedding"])
def test_an_unanswered_search_call_stops_with_the_rerun_instruction(
    unanswered_endpoint, step
):
    started = time.monotonic()
    with pytest.raises(BedrockTimeoutError) as caught:
        if step == "reranking":
            BedrockReranker(get_settings()).rerank("quiet headphones", ["a", "b"], 2)
        else:
            BedrockEmbeddingProvider(get_settings()).embed_query("quiet headphones")
    elapsed = time.monotonic() - started

    assert len(unanswered_endpoint.requests) == 2
    assert elapsed < HOLD_SECONDS
    assert str(caught.value) == (
        f"This search stopped: Amazon Bedrock's {step} call did not answer within 0.3 "
        "seconds, even after retrying. Nothing is wrong with your work. Run the same "
        "command or search again."
    )
    assert isinstance(caught.value.__cause__, ReadTimeoutError)


def test_the_error_classifier_keeps_the_rerun_instruction():
    try:
        raise BedrockTimeoutError(RERUN) from ReadTimeoutError(
            endpoint_url="http://bedrock"
        )
    except BedrockTimeoutError as error:
        timed_out = error
    wrapped = RuntimeError("search_products failed")
    wrapped.__cause__ = timed_out

    assert model_runtime_error(timed_out) is timed_out
    assert model_runtime_error(wrapped) is timed_out


def test_the_search_route_returns_the_rerun_instruction(monkeypatch):
    def unanswered(_request):
        raise BedrockTimeoutError(RERUN)

    monkeypatch.setattr(main, "search_with_telemetry", unanswered)

    with pytest.raises(HTTPException) as caught:
        main.search(SearchRequest(query="quiet headphones"))

    assert (caught.value.status_code, caught.value.detail) == (503, RERUN)


def test_lab_commands_print_the_api_sentence_not_its_json(monkeypatch):
    def refused(*_args, **_kwargs):
        body = io.BytesIO(json.dumps({"detail": RERUN}).encode())
        raise HTTPError(
            "http://127.0.0.1:8000/api/search", 503, "Unavailable", {}, body
        )

    monkeypatch.setattr("scripts.prove_lab.urlopen", refused)

    with pytest.raises(LabValidationError) as caught:
        _request("http://127.0.0.1:8000", "/api/search", {"query": "quiet headphones"})

    assert str(caught.value) == f"/api/search returned HTTP 503: {RERUN}"
