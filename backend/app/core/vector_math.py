"""Vector math for in-app similarity ranking.

Kept dependency-free (no numpy) since this only ever runs over a
candidate set of at most a few hundred rows per request — the DB query
already filters by owner_id/agent_id before this runs.
"""
import math


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def top_k_by_similarity(query_vector: list[float], candidates: list, key, k: int) -> list:
    """candidates: list of arbitrary objects. key: fn(obj) -> embedding list[float].
    Returns the k highest-scoring candidates, each as (obj, score), descending."""
    scored = [(item, cosine_similarity(query_vector, key(item))) for item in candidates]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:k]
