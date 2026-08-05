from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from app.db import close_pool, get_owner_conn

LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
RDS_REGION = re.compile(
    r"\.([a-z]{2}(?:-gov)?-[a-z]+-\d)\.rds\.amazonaws\.com$",
    re.IGNORECASE,
)


def version_tuple(value: str | bytes | None) -> tuple[int, ...]:
    if isinstance(value, bytes):
        value = value.decode("ascii")
    match = re.search(r"(\d+(?:\.\d+)*)", value or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def target_kind(*, host: str, is_aurora: bool) -> str:
    if is_aurora:
        return "aurora"
    if host in LOCAL_DATABASE_HOSTS or host.startswith("/"):
        return "local"
    return "unsupported-remote"


def rds_region(host: str) -> str | None:
    match = RDS_REGION.search(host)
    return match.group(1).lower() if match else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate PostgreSQL server version."
    )
    parser.add_argument("--min-version", default="18.3")
    parser.add_argument(
        "--exact-version",
        help="Require this exact major/minor version instead of a minimum.",
    )
    parser.add_argument(
        "--test-target",
        action="store_true",
        help=(
            "Require a disposable _test database on Aurora in the requested AWS "
            "region or on loopback. Remote non-Aurora PostgreSQL is rejected."
        ),
    )
    parser.add_argument("--aws-region", default="us-east-1")
    args = parser.parse_args()

    with get_owner_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT current_setting('server_version'),
                       current_database(),
                       to_regprocedure('aurora_version()') IS NOT NULL
                """
            )
            actual, database_name, is_aurora = cur.fetchone()
            host = conn.info.host or ""

    actual_version = version_tuple(actual)
    if args.exact_version and actual_version != version_tuple(args.exact_version):
        print(
            f"PostgreSQL server version is {actual}; expected exactly "
            f"{args.exact_version}.",
            file=sys.stderr,
        )
        return 1
    if not args.exact_version and actual_version < version_tuple(args.min_version):
        print(
            f"PostgreSQL server version is {actual}; "
            f"expected >= {args.min_version}.",
            file=sys.stderr,
        )
        return 1

    kind = target_kind(host=host, is_aurora=is_aurora)
    if args.test_target:
        if not database_name.endswith("_test"):
            print(
                f"Database is {database_name}; test targets must end in _test.",
                file=sys.stderr,
            )
            return 1
        if kind == "unsupported-remote":
            print(
                f"Remote test host {host} is not Aurora PostgreSQL.",
                file=sys.stderr,
            )
            return 1
        if kind == "aurora":
            actual_region = rds_region(host)
            if actual_region != args.aws_region:
                print(
                    f"Aurora test host is in {actual_region or 'an unknown region'}; "
                    f"expected {args.aws_region}.",
                    file=sys.stderr,
                )
                return 1

    expected = (
        f"exactly {args.exact_version}"
        if args.exact_version
        else f">= {args.min_version}"
    )
    target = f"{kind} database {database_name}"
    if kind == "aurora":
        target += f" in {rds_region(host) or 'unknown-region'}"
    print(f"PostgreSQL target OK: {actual} ({expected}); {target}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        close_pool()
