from termflow.core.search_chunks import split_source


def test_split_source_returns_ten_ordered_chunks_and_exact_core_coverage():
    source = "\n\n".join(f"paragraph {i} 林雪" for i in range(30))

    chunks = split_source(source)

    assert len(chunks) == 10
    assert [chunk.index for chunk in chunks] == list(range(1, 11))
    assert [(c.core_start, c.core_end) for c in chunks][0][0] == 0
    assert chunks[-1].core_end == len(source)
    assert all(left.core_end == right.core_start for left, right in zip(chunks, chunks[1:]))
    assert "".join(source[c.core_start : c.core_end] for c in chunks) == source


def test_request_chunks_overlap_by_neighbor_paragraph_and_cover_core():
    source = "\n\n".join(f"paragraph {i}" for i in range(20))

    chunks = split_source(source, count=4, overlap_units=1)

    for chunk in chunks:
        assert chunk.request_start <= chunk.core_start
        assert chunk.request_end >= chunk.core_end
        assert chunk.text == source[chunk.request_start : chunk.request_end]
    assert chunks[0].request_start == 0
    assert chunks[-1].request_end == len(source)
    assert chunks[1].request_start < chunks[1].core_start
    assert chunks[1].request_end > chunks[1].core_end


def test_split_source_falls_back_to_lines_and_preserves_windows_newlines():
    source = "林雪\r\n洛川\r\n青云剑诀\r\n" * 5

    chunks = split_source(source, count=5)

    assert "".join(source[c.core_start : c.core_end] for c in chunks) == source
    assert all(c.text == source[c.request_start : c.request_end] for c in chunks)


def test_split_source_handles_single_line_unicode_without_losing_characters():
    source = "林雪🌸洛川" * 5

    chunks = split_source(source, count=5)

    assert len(chunks) == 5
    assert "".join(source[c.core_start : c.core_end] for c in chunks) == source
    assert all(chunk.text == source[chunk.request_start : chunk.request_end] for chunk in chunks)


def test_empty_and_short_sources_have_ten_ranges_without_blank_work():
    assert len(split_source("")) == 10
    chunks = split_source("abc")
    assert len(chunks) == 10
    assert "".join("abc"[c.core_start : c.core_end] for c in chunks) == "abc"
    assert sum(bool(chunk.text) for chunk in chunks) == 3
