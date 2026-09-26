"""The held-out ESCI corpus excludes every tuning query and carries human labels only."""

from __future__ import annotations

from scripts import prepare_esci_held_out as held_out


def case(query_id: int, labels: dict[int, str]) -> dict:
    return {
        "query_id": query_id,
        "query": f"query {query_id}",
        "filters": {"domain": "consumer_electronics", "category_key": "headphones"},
        "judgments": [
            {
                "asin": f"B{pid:09d}",
                "product_id": pid,
                "esci_label": label,
                "example_id": pid * 10,
            }
            for pid, label in labels.items()
        ],
    }


def test_tuning_queries_are_dropped_and_labels_become_human_graded_judgments():
    cases = [
        case(1, {10: "E", 11: "I"}),
        case(2, {12: "S", 13: "C"}),
        case(3, {14: "I"}),
    ]
    records = held_out.held_out_records(cases, "reviews-2023-v2", {2}, ({10}, {12}))
    assert [r["esci_query_id"] for r in records] == [1, 3]
    first = records[0]
    assert (
        first["query_id"] == "ESCI-1"
        and first["cohort_intent"] == "esci_shopping_query"
    )
    assert (
        first["cohort_category"] == "headphones"
        and first["dataset_id"] == "reviews-2023-v2"
    )
    assert [
        (j["product_id"], j["grade"], j["status"], j["anchor_overlap"])
        for j in first["judgments"]
    ] == [
        (10, 3, "esci_human", "mission"),
        (11, 0, "esci_human", "none"),
    ]
    assert (
        first["hard_negative_ids"] == [11]
        and first["expect_no_relevant_results"] is False
    )
    assert first["source"]["license"] == "Apache-2.0"
    assert records[1]["expect_no_relevant_results"] is True
    assert records[1]["hard_negative_ids"] == [14]


def test_tuning_ids_come_from_the_committed_subset(tmp_path):
    path = tmp_path / "subset.json"
    path.write_text('{"queries": [{"query_id": 7}, {"query_id": 9}]}')
    assert held_out.tuning_query_ids(path) == {7, 9}
