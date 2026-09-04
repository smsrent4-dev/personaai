import pytest

from app.services.knowledge.chunking import chunk_text


def test_empty_text_returns_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_short_text_is_single_chunk():
    assert chunk_text("hello world") == ["hello world"]


def test_long_text_is_split_into_multiple_chunks():
    long_text = ("The quick brown fox jumps over the lazy dog. " * 50).strip()
    chunks = chunk_text(long_text, chunk_size=200, overlap=40)
    assert len(chunks) > 1
    assert all(len(c) <= 205 for c in chunks)  # small slack for boundary snapping


def test_chunks_cover_the_original_text_content():
    long_text = ("Sentence one. Sentence two. Sentence three. " * 20).strip()
    chunks = chunk_text(long_text, chunk_size=100, overlap=20)
    # every chunk's content should actually appear in the source (no corruption/invention)
    for chunk in chunks:
        assert chunk in long_text


def test_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValueError):
        chunk_text("some text", chunk_size=100, overlap=100)


def test_whitespace_is_normalized():
    messy = "line one\n\n\n   line two\t\ttab   here"
    chunks = chunk_text(messy)
    assert len(chunks) == 1
    assert "\n" not in chunks[0]
    assert "  " not in chunks[0]


def test_always_makes_forward_progress_on_pathological_input():
    # A single run-on "word" with no spaces anywhere near the chunk boundary —
    # regression guard against an infinite loop in the boundary-snapping logic.
    pathological = "x" * 5000
    chunks = chunk_text(pathological, chunk_size=300, overlap=290)
    assert len(chunks) > 1
    assert "".join(chunks).replace("x", "") == ""  # sanity: only ever 'x' characters
