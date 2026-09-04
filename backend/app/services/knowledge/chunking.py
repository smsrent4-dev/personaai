"""Splits text into overlapping chunks for embedding.

Pure function, no I/O, no AI calls — deliberately kept simple and
dependency-free so it's cheap to unit test exhaustively (see
tests/test_chunking.py) and easy to swap for a smarter splitter
(sentence-boundary aware, token-counted) later without touching
anything that calls it.
"""


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    normalized = " ".join(text.split())  # collapse whitespace/newlines
    if not normalized:
        return []

    if len(normalized) <= chunk_size:
        return [normalized]

    chunks: list[str] = []
    start = 0
    n = len(normalized)

    while start < n:
        end = min(start + chunk_size, n)

        # Prefer breaking at a sentence or word boundary near the end,
        # rather than mid-word, if one exists reasonably close by.
        if end < n:
            boundary = normalized.rfind(". ", start, end)
            if boundary == -1 or boundary < start + int(chunk_size * 0.5):
                boundary = normalized.rfind(" ", start, end)
            if boundary != -1 and boundary > start:
                end = boundary + 1

        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= n:
            break
        start = max(end - overlap, start + 1)  # always make forward progress

    return chunks
