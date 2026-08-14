from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_database_recipes_do_not_echo_the_expanded_dsn():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    leaking = [
        (line_number, line)
        for line_number, line in enumerate(makefile.splitlines(), 1)
        if line.startswith("\t")
        and "$(DATABASE_URL)" in line
        and not line.removeprefix("\t").startswith("@")
    ]
    assert not leaking, (
        "Make echoes recipe lines by default; prefix every DSN-bearing command "
        f"with @ so credentials do not reach terminals or logs: {leaking}"
    )
