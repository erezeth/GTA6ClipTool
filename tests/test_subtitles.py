from core.subtitles import group_words, write_ass


def test_group_words_splits_on_gap_and_length():
    words = [
        {"start": 0.0, "end": 0.3, "text": "halo"},
        {"start": 0.3, "end": 0.6, "text": "semua"},
        {"start": 0.6, "end": 0.9, "text": "ini"},
        {"start": 2.0, "end": 2.3, "text": "klip"},
        {"start": 2.3, "end": 2.6, "text": "baru"},
    ]
    chunks = group_words(words, max_words=4, max_gap=0.7)
    assert [c["text"] for c in chunks] == ["halo semua ini", "klip baru"]
    assert chunks[0]["start"] == 0.0 and chunks[0]["end"] == 0.9


def test_group_words_respects_max_words():
    words = [{"start": i, "end": i + 0.5, "text": f"w{i}"} for i in range(7)]
    chunks = group_words(words, max_words=3, max_gap=1.0, max_chars=99, max_dur=99)
    assert len(chunks) == 3


def test_write_ass_escapes_and_positions(tmp_path):
    path = write_ass([{"start": 0.0, "end": 1.5, "text": "a{b}c"}], tmp_path / "s.ass")
    text = path.read_text(encoding="utf-8")
    assert "Dialogue: 0,0:00:00.00,0:00:01.50,Default,,0,0,0,,{\\pos(540,980)}a(b)c" in text
    assert "PlayResY: 1920" in text


def test_write_ass_custom_x_and_size(tmp_path):
    path = write_ass([{"start": 0.0, "end": 1.0, "text": "halo"}], tmp_path / "s.ass",
                     pos_x=0.25, font_size=90)
    text = path.read_text(encoding="utf-8")
    assert "{\\pos(270,980)}halo" in text
    assert ",Arial,90," in text
