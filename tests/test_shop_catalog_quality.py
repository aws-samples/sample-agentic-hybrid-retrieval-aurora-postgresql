from scripts.shop_catalog_quality import copy_violations


def test_repeated_summary_names_both_products_and_the_fix():
    rows = [
        {
            "product_id": 1,
            "short_description": "Mesh chair with adjustable lumbar and 4D armrests.",
        },
        {
            "product_id": 2,
            "short_description": "Mesh chair with adjustable lumbar and 4D armrests!",
        },
    ]
    errors = copy_violations(rows)
    assert len(errors) == 1
    assert "2 repeats 1" in errors[0]
    assert "write its own factual buying differences" in errors[0]


def test_concrete_differences_and_false_features_are_distinct():
    assert (
        copy_violations(
            [
                {
                    "product_id": 1,
                    "short_description": "Mesh chair with adjustable lumbar and 4D armrests.",
                },
                {
                    "product_id": 2,
                    "short_description": "Oatmeal fabric chair with fixed arms and an oak-clad base.",
                },
            ]
        )
        == []
    )


def test_authoring_notes_cannot_reach_a_shop_card():
    errors = copy_violations(
        [
            {
                "product_id": 2,
                "short_description": "Memory foam footrest with adjustable height—locked spec.",
            }
        ]
    )
    assert any("shopper-copy" in e and "remove authoring" in e for e in errors)


def test_distinct_cards_do_not_hide_duplicate_product_details():
    rows = [
        {
            "product_id": 1,
            "short_description": "Mesh chair with adjustable lumbar and 4D armrests.",
            "long_description": "A mesh chair for long days, with adjustable support.",
        },
        {
            "product_id": 2,
            "short_description": "Oatmeal fabric chair with fixed arms and an oak-clad base.",
            "long_description": "A mesh chair for long days with adjustable support!",
        },
    ]
    errors = copy_violations(rows)
    assert any("detail-copy" in error and "2 repeats 1" in error for error in errors)
