import numpy as np
import pytest

from scripts.promote_catalog_corrections import validate_vectors


def test_vector_bundle_requires_exact_identity_text_and_nonzero_values():
    ids = np.array([7])
    hashes = np.array(["a" * 64], dtype="S64")
    expected = {7: {"text_sha256": "a" * 64}}
    vectors = np.ones((1, 4), dtype=np.float32)
    validate_vectors(ids, hashes, vectors, expected, 4)
    with pytest.raises(ValueError, match="text rule"):
        validate_vectors(ids, hashes, vectors, {7: {"text_sha256": "b" * 64}}, 4)
    with pytest.raises(ValueError, match="text rule"):
        validate_vectors(np.array([8]), hashes, vectors, expected, 4)
    with pytest.raises(ValueError, match="value rule"):
        validate_vectors(ids, hashes, np.zeros((1, 4)), expected, 4)
    with pytest.raises(ValueError, match="shape rule"):
        validate_vectors(ids, hashes, vectors, expected, 3)
    # A price-only correction does not invalidate a matching text vector.
    validate_vectors(
        ids, hashes, vectors, {7: {**expected[7], "price_cents": 12345}}, 4
    )
