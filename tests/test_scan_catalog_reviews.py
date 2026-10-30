"""A review scan's parts resume from their checkpoints and stop at their boundaries."""

import json

import pytest

from scripts.catalog import scan_catalog_reviews as scan


def checkpoint(work, index, next_byte):
    folder = work / f"p{index}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "Electronics-reviews.json"
    path.write_text(json.dumps({"next_byte": next_byte, "reviews": []}) + "\n")
    return path


def test_a_finished_part_is_not_scanned_again(tmp_path, monkeypatch):
    checkpoint(tmp_path, 0, 500)

    def never(*args, **kwargs):
        raise AssertionError("fetch must not run for a finished part")

    monkeypatch.setattr(scan, "fetch", never)
    assert scan.run_part("Electronics", str(tmp_path), 0, 0, 500, ["P1"], 5) == 0


def test_a_partial_part_resumes_to_its_boundary_not_a_part_length_later(
    tmp_path, monkeypatch
):
    checkpoint(tmp_path, 1, 620)
    budgets = []

    def fetch(category, dest, parents, scan_bytes, per_group, workers):
        budgets.append(scan_bytes)
        return {"next_byte": 620 + scan_bytes}

    monkeypatch.setattr(scan, "fetch", fetch)
    assert scan.run_part("Electronics", str(tmp_path), 1, 500, 1000, ["P1"], 5) == 1
    # The first run gave fetch the whole part length from its start; a resumed part
    # scanned another part length past its boundary.
    assert budgets == [380]


def test_a_new_part_starts_at_its_own_boundary(tmp_path, monkeypatch):
    seen = {}

    def fetch(category, dest, parents, scan_bytes, per_group, workers):
        seen["start"] = json.loads((dest / "Electronics-reviews.json").read_text())[
            "next_byte"
        ]
        seen["budget"] = scan_bytes
        return {"next_byte": 1000}

    monkeypatch.setattr(scan, "fetch", fetch)
    assert scan.run_part("Electronics", str(tmp_path), 1, 500, 1000, ["P1"], 5) == 1
    assert seen == {"start": 500, "budget": 500}


def test_a_checkpoint_past_its_boundary_is_refused_by_name(tmp_path, monkeypatch):
    path = checkpoint(tmp_path, 0, 1925597445)
    monkeypatch.setattr(scan, "fetch", lambda *a, **k: {"next_byte": 0})
    with pytest.raises(ValueError, match=f"past its boundary 962799016; delete {path}"):
        scan.run_part("Electronics", str(tmp_path), 0, 0, 962799016, ["P1"], 5)


def test_a_part_that_stops_short_of_its_boundary_is_reported(tmp_path, monkeypatch):
    checkpoint(tmp_path, 2, 10)
    monkeypatch.setattr(scan, "fetch", lambda *a, **k: {"next_byte": 90})
    with pytest.raises(ValueError, match="part 2 stopped at byte 90, not 100"):
        scan.run_part("Electronics", str(tmp_path), 2, 0, 100, ["P1"], 5)
