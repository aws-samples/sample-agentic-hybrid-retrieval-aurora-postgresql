"""The downloaded folder preserves the canonical skill's relative references."""

import io
import zipfile

from fastapi.testclient import TestClient

from service import main


def test_download_contains_the_complete_canonical_skill():
    response = TestClient(main.app).get("/api/skill-package")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    package = main.ROOT / "skills" / "mosaic-hybrid-retrieval"
    expected = {
        "SKILL.md",
        "references/http-api.md",
        "references/composition.md",
        "references/adapting.md",
    }
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {
            f"mosaic-hybrid-retrieval/{name}" for name in expected
        }
        for name in expected:
            assert (
                archive.read(f"mosaic-hybrid-retrieval/{name}")
                == (package / name).read_bytes()
            )


def test_missing_skill_reports_what_to_restore(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    response = TestClient(main.app).get("/api/skill-package")
    assert response.status_code == 503
    assert "restore skills/mosaic-hybrid-retrieval" in response.json()["detail"]


def test_download_excludes_references_outside_the_package(tmp_path, monkeypatch):
    package = tmp_path / "skills" / "mosaic-hybrid-retrieval"
    references = package / "references"
    references.mkdir(parents=True)
    (package / "SKILL.md").write_text("Portable instructions")
    (references / "included.md").write_text("Canonical reference")
    outside = tmp_path / "private.md"
    outside.write_text("Outside the skill")
    (references / "outside.md").symlink_to(outside)
    monkeypatch.setattr(main, "ROOT", tmp_path)

    response = TestClient(main.app).get("/api/skill-package")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {
            "mosaic-hybrid-retrieval/SKILL.md",
            "mosaic-hybrid-retrieval/references/included.md",
        }
