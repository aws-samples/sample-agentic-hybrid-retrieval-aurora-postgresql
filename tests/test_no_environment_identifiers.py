"""No tracked file names a real AWS account.

This repository is public. Proof records and pages are written from runs in real
accounts, and a sibling workshop published an account ID, a bucket named after it and a
key ARN in an evidence record before anyone noticed. AWS's documented placeholder
accounts stay allowed.
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDERS = {"123456789012", "111122223333", "444455556666", "000000000000"}
# An account inside an ARN, an ECR registry host, or the own-account bucket name.
SCOPED = re.compile(
    r"arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:(\d{12}):"
    r"|(\d{12})\.dkr\.ecr\."
    r"|mosaic-own-account-(\d{12})-"
)
# Prose has no reason to carry a bare twelve-digit number; an account ID is the usual one.
# A period ends a sentence unless a word or digit follows it (1.2, a.b).
BARE = re.compile(r"(?<![\w.-])(\d{12})(?![\w-])(?!\.\w)")


def tracked_text_files() -> list[Path]:
    names = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    files = []
    for name in filter(None, names):
        path = ROOT / name.decode()
        if path.is_file() and b"\0" not in path.read_bytes()[:4096]:
            files.append(path)
    return files


def account_ids(text: str, *, prose: bool) -> set[str]:
    found = {
        group for match in SCOPED.finditer(text) for group in match.groups() if group
    }
    if prose:
        found |= set(BARE.findall(text))
    return found - PLACEHOLDERS


def test_no_tracked_file_names_a_real_account():
    offenders = {}
    for path in tracked_text_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        ids = account_ids(text, prose=path.suffix == ".md")
        if ids:
            offenders[str(path.relative_to(ROOT))] = sorted(ids)
    assert offenders == {}, (
        "Environment identifier rule: these files name AWS accounts; replace each with "
        f"<account> or a documented placeholder such as 123456789012: {offenders}"
    )


def test_the_scan_catches_each_form_and_spares_placeholders():
    leaked = "619700000013"
    assert account_ids(f"arn:aws:kms:us-east-1:{leaked}:key/abc", prose=False) == {
        leaked
    }
    assert account_ids(f"{leaked}.dkr.ecr.us-west-2.amazonaws.com", prose=False) == {
        leaked
    }
    assert account_ids(f"s3://mosaic-own-account-{leaked}-us-east-1/", prose=False) == {
        leaked
    }
    assert account_ids(f"account {leaked} in us-east-1", prose=True) == {leaked}
    assert account_ids(f"Proof account {leaked}.", prose=True) == {leaked}
    assert account_ids(f"version {leaked}.5", prose=True) == set()
    assert account_ids(f"account {leaked} in us-east-1", prose=False) == set()
    assert account_ids("arn:aws:iam::123456789012:role/r", prose=True) == set()
    assert account_ids("2,521,919,722 bytes and 1793384137953 ms", prose=True) == set()
