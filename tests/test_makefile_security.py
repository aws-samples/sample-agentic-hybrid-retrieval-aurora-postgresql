from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_database_recipes_never_expand_the_dsn():
    """`make -n` and `make --trace` print recipes after make-variable expansion.

    An `@` prefix silences the normal echo but not those two, so a recipe that
    interpolates `$(DATABASE_URL)` prints the Aurora password the first time a
    facilitator asks make what it is about to do. Recipes read the DSN from the
    exported environment by name instead.
    """
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    leaking = [
        (line_number, line)
        for line_number, line in enumerate(makefile.splitlines(), 1)
        if line.startswith("\t") and "$(DATABASE_URL)" in line
    ]
    assert not leaking, (
        "recipes must reference $$DATABASE_URL by name, never expand "
        f"$(DATABASE_URL) into recipe text: {leaking}"
    )
    assert "\nexport DATABASE_URL\n" in makefile
