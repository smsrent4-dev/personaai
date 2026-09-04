from app.core.vector_math import cosine_similarity, top_k_by_similarity


def test_identical_vectors_have_similarity_one():
    assert cosine_similarity([1, 0, 0], [1, 0, 0]) == 1.0


def test_orthogonal_vectors_have_similarity_zero():
    assert cosine_similarity([1, 0], [0, 1]) == 0.0


def test_opposite_vectors_have_similarity_negative_one():
    assert cosine_similarity([1, 0], [-1, 0]) == -1.0


def test_zero_vector_returns_zero_not_a_division_error():
    assert cosine_similarity([0, 0], [1, 1]) == 0.0


def test_mismatched_lengths_returns_zero_rather_than_raising():
    assert cosine_similarity([1, 2], [1, 2, 3]) == 0.0


def test_top_k_by_similarity_orders_correctly():
    candidates = [
        {"id": "far", "v": [0, 1]},
        {"id": "near", "v": [1, 0]},
        {"id": "close", "v": [0.9, 0.1]},
    ]
    ranked = top_k_by_similarity([1, 0], candidates, key=lambda c: c["v"], k=2)
    assert [c["id"] for c, _score in ranked] == ["near", "close"]


def test_top_k_respects_k_limit():
    candidates = [{"v": [1, 0]} for _ in range(10)]
    ranked = top_k_by_similarity([1, 0], candidates, key=lambda c: c["v"], k=3)
    assert len(ranked) == 3
