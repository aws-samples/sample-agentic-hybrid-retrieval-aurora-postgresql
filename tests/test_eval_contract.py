import pytest

from scripts.run_eval import validate_query_contract


class _NoDatabaseCall:
    def execute(self, *_args, **_kwargs):
        raise AssertionError("invalid filter shape must fail before Aurora")


class _DatabaseResult:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, *_args, **_kwargs):
        return self

    def fetchall(self):
        return self.rows


def test_predecessor_filter_vocabulary_fails_before_model_or_database_calls():
    queries = [
        {
            "query_id": "RED-001",
            "target_product_id": 2,
            "filters": {
                "subcategory": "Over-Ear Headphones",
                "max_price": 200,
            },
        }
    ]

    with pytest.raises(
        ValueError,
        match="use category_key, integer min_price_cents/max_price_cents",
    ):
        validate_query_contract(_NoDatabaseCall(), queries)


@pytest.mark.parametrize("filters", [None, [], "domain=home_office"])
def test_filters_must_be_a_json_object(filters):
    queries = [
        {
            "query_id": "RED-002",
            "target_product_id": 2,
            "filters": filters,
        }
    ]

    with pytest.raises(
        ValueError,
        match="filters violate the Mosaic SearchFilters contract",
    ):
        validate_query_contract(_NoDatabaseCall(), queries)


def test_empty_query_set_cannot_pass_vacuously():
    with pytest.raises(
        ValueError,
        match="requires at least one query",
    ):
        validate_query_contract(_NoDatabaseCall(), [])


def test_live_target_violation_is_reported_with_the_nearest_fix():
    queries = [
        {
            "query_id": "RED-003",
            "target_product_id": 234001,
            "filters": {
                "domain": "running_fitness",
                "attributes": {"carbon_plate": True},
            },
        }
    ]
    database = _DatabaseResult(
        [
            (
                "RED-003",
                234001,
                "target violates its Mosaic filters",
            )
        ]
    )

    with pytest.raises(
        ValueError,
        match=(
            "RED-003/234001: target violates its Mosaic filters.*"
            "Fix the query filters or target IDs"
        ),
    ):
        validate_query_contract(database, queries)


def test_valid_query_contract_passes():
    queries = [
        {
            "query_id": "GREEN-001",
            "target_product_id": 234002,
            "filters": {
                "domain": "running_fitness",
                "attributes": {"carbon_plate": True},
            },
        }
    ]

    validate_query_contract(_DatabaseResult([]), queries)
