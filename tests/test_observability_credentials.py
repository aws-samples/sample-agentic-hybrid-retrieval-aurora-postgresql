"""Exercise the runtime exporter's recovery after a metadata credential miss."""

from unittest.mock import Mock

import pytest
from botocore.credentials import Credentials

requests = pytest.importorskip(
    "requests",
    reason="The requests client is part of the agentcore-observability extra.",
)
auth = pytest.importorskip(
    "amazon.opentelemetry.distro.exporter.otlp.aws.common.aws_auth_session",
    reason="Run with --extra agentcore-observability to test the runtime exporter.",
)


def test_export_retries_missing_credentials_and_signs_when_they_become_available(
    monkeypatch,
):
    """A transient metadata miss must not leave later exports unsigned forever."""
    provider = Mock()
    provider.get_credentials.side_effect = [
        None,
        Credentials("test-access-key", "test-secret-key", "test-token"),
    ]
    transmitted_headers = []

    def capture_request(_session, **kwargs):
        transmitted_headers.append(dict(kwargs.get("headers") or {}))
        return Mock(status_code=200)

    monkeypatch.setattr(requests.Session, "request", capture_request)
    session = auth.AwsAuthSession(
        aws_region="us-east-1", service="xray", session=provider
    )
    for _ in range(3):
        session.request("POST", "https://xray.us-east-1.amazonaws.com/v1/traces")

    assert "Authorization" not in transmitted_headers[0]
    assert "Authorization" in transmitted_headers[1]
    assert "Authorization" in transmitted_headers[2]
    assert provider.get_credentials.call_count == 2
