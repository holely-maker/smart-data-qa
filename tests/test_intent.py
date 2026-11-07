from intent import merge
from parser import parse


def test_followup_inherits_metric_and_replaces_time():
    prev = parse("今年收入是多少").intent
    parsed = parse("那上个月呢")
    merged = merge(prev, parsed)

    assert merged.metrics == ["revenue"]
    assert merged.time_range.start == "2026-09"
    assert merged.time_range.end == "2026-09"


def test_comparison_is_not_inherited():
    prev = parse("今年收入同比").intent
    assert prev.comparison == "yoy"

    merged = merge(prev, parse("那上个月呢"))
    assert merged.comparison is None


def test_filters_merge_by_key():
    prev = parse("华东收入").intent
    merged = merge(prev, parse("线上渠道收入"))
    assert merged.filters["region"] == ["华东"]
    assert merged.filters["channel"] == ["线上"]


def test_dimension_append_mode():
    prev = parse("按区域拆一下").intent
    parsed = parse("再按渠道")
    assert parsed.dimension_mode == "append"

    merged = merge(prev, parsed)
    assert merged.dimensions == ["region", "channel"]


def test_new_question_replaces_dimensions():
    prev = parse("按区域拆一下").intent
    merged = merge(prev, parse("按产品线拆一下"))
    assert merged.dimensions == ["product_line"]
