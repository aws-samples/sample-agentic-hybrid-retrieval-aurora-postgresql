"""Secret-backed settings must fail safely before the database is contacted."""

import json

import boto3
import pytest
from botocore.exceptions import ClientError

from service.config import ConfigurationError, get_settings

ARN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:mosaic-db-AbCdEf"
DSN = "postgresql://runtime:private-sentinel@demo.cluster-test.us-east-1.rds.amazonaws.com/mosaic?sslmode=require"


@pytest.fixture(autouse=True)
def settings_environment(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MOSAIC_DATABASE_SECRET_ARN", ARN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def stub_secret(monkeypatch, response=None, error=None):
    calls = []

    class Secrets:
        def get_secret_value(self, **kwargs):
            calls.append(kwargs)
            if error:
                raise error
            return response

    def client(service, **kwargs):
        assert service == "secretsmanager"
        assert kwargs["region_name"] == "us-east-1"
        assert kwargs["config"].connect_timeout <= 5
        assert kwargs["config"].read_timeout <= 10
        return Secrets()

    monkeypatch.setattr(boto3, "client", client)
    return calls


@pytest.mark.parametrize("value", [DSN, json.dumps({"DATABASE_URL": DSN})])
def test_secret_is_loaded_once_before_settings_are_cached(monkeypatch, value):
    calls = stub_secret(monkeypatch, {"SecretString": value})
    assert get_settings().database_url == DSN
    assert get_settings().database_url == DSN
    assert calls == [{"SecretId": ARN, "VersionStage": "AWSCURRENT"}]


def test_secret_failure_does_not_expose_credentials(monkeypatch):
    stub_secret(
        monkeypatch,
        error=ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": DSN}},
            "GetSecretValue",
        ),
    )
    with pytest.raises(ConfigurationError, match="Database secret rule") as error:
        get_settings()
    assert "private-sentinel" not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize(
    "value",
    [
        "",
        "{}",
        "[]",
        '{"DATABASE_URL": 3}',
        "private-sentinel-invalid",
        "postgresql://u:private-sentinel@localhost/db?sslmode=require",
        DSN.replace("sslmode=require", "sslmode=disable"),
        DSN.replace(".rds.amazonaws.com", ".rds.amazonaws.com.example.org"),
    ],
)
def test_invalid_secret_payload_fails_without_printing_it(monkeypatch, value):
    stub_secret(monkeypatch, {"SecretString": value})
    with pytest.raises(ConfigurationError, match="Database secret rule") as error:
        get_settings()
    assert "private-sentinel" not in str(error.value)


def test_two_database_sources_are_rejected_before_secret_lookup(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DSN)
    monkeypatch.setattr(
        boto3,
        "client",
        lambda *a, **k: pytest.fail("ambiguous config fetched a secret"),
    )
    with pytest.raises(ConfigurationError, match="both"):
        get_settings()


@pytest.mark.parametrize("invalid_arn", ["mosaic-db", DSN])
def test_invalid_secret_arn_fails_before_sdk_work(monkeypatch, invalid_arn):
    monkeypatch.setenv("MOSAIC_DATABASE_SECRET_ARN", invalid_arn)
    monkeypatch.setattr(
        boto3, "client", lambda *a, **k: pytest.fail("invalid ARN reached the SDK")
    )
    with pytest.raises(ConfigurationError, match="secret ARN") as error:
        get_settings()
    assert "private-sentinel" not in str(error.value)


def test_direct_database_url_keeps_the_existing_path(monkeypatch):
    monkeypatch.delenv("MOSAIC_DATABASE_SECRET_ARN")
    monkeypatch.setenv("DATABASE_URL", DSN)
    monkeypatch.setattr(
        boto3, "client", lambda *a, **k: pytest.fail("direct DSN fetched a secret")
    )
    assert get_settings().database_url == DSN
