import hashlib
from pathlib import Path

PUBLIC = Path(__file__).resolve().parents[1] / "ui" / "public"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_landing_hero_is_the_unmodified_source_asset():
    hero = PUBLIC / "assets/images/mosaic/hero-editorial-mosaic.webp"
    assert (
        digest(hero)
        == "57aced551056a574340e081d9162d25b339f99f122ba0db0449e3517dec24044"
    )
