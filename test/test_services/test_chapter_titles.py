from services.chapter_titles import normalize_chapter_title, strip_chapter_ordinal


def test_strip_chapter_ordinal_supports_common_markers_and_separators():
    assert strip_chapter_ordinal("第2章 凪光真人") == "凪光真人"
    assert strip_chapter_ordinal("第一百二十回：旧城夜雨") == "旧城夜雨"
    assert strip_chapter_ordinal("第 3 集 · 重逢") == "重逢"


def test_normalize_chapter_title_uses_a_semantic_fallback():
    assert normalize_chapter_title("第一章", fallback="今天他飞升了吗") == "今天他飞升了吗"
    assert normalize_chapter_title("第1章") == "未命名"
