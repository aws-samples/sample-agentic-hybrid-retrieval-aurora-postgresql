"""Regression coverage for the standalone package validation entrypoint."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "checks"


def _validator_module():
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(
            "package_validation",
            SCRIPTS / "validate_package.py",
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


def test_package_validator_failure_is_explicit_and_actionable() -> None:
    """A failed catalog package rule must survive optimized Python execution."""
    validator = _validator_module()

    with pytest.raises(
        ValueError, match="Catalog parts rule: found 0; fix: restore the contract"
    ):
        validator.require(
            False,
            "Catalog parts rule",
            0,
            "restore the contract",
        )
