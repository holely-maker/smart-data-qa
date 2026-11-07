from intent import TimeRange
from parser import parse, resolve_time
from schema import AS_OF_MONTH


def test_relative_months():
    assert resolve_time("本月收入", AS_OF_MONTH) == TimeRange("2026-10", "2026-10", "single")
    assert resolve_time("上月收入", AS_OF_MONTH) == TimeRange("2026-09", "2026-09", "single")
    assert resolve_time("近3个月收入", AS_OF_MONTH) == TimeRange("2026-08", "2026-10", "month")
    assert resolve_time("近6个月收入", AS_OF_MONTH) == TimeRange("2026-05", "2026-10", "month")
    assert resolve_time("近三个月收入", AS_OF_MONTH) == TimeRange("2026-08", "2026-10", "month")


def test_year_and_quarter():
    assert resolve_time("今年收入", AS_OF_MONTH) == TimeRange("2026-01", "2026-10", "month")
    assert resolve_time("去年收入", AS_OF_MONTH) == TimeRange("2025-01", "2025-12", "year")
    assert resolve_time("2025年收入", AS_OF_MONTH) == TimeRange("2025-01", "2025-12", "year")
    assert resolve_time("第三季度收入", AS_OF_MONTH) == TimeRange("2026-07", "2026-09", "quarter")
    assert resolve_time("去年第三季度收入", AS_OF_MONTH) == TimeRange(
        "2025-07", "2025-09", "quarter"
    )
    assert resolve_time("2025年9月收入", AS_OF_MONTH) == TimeRange(
        "2025-09", "2025-09", "single"
    )


def test_comparison_phrase_is_not_query_time():
    # “较上月”是基期描述，不应把查询时间改成上月。
    assert resolve_time("本月收入较上月增长", AS_OF_MONTH) == TimeRange(
        "2026-10", "2026-10", "single"
    )
    assert resolve_time("收入较上月增长", AS_OF_MONTH) is None


def test_metric_long_keyword_wins():
    result = parse("上月毛利率是多少")
    assert result.intent.metrics == ["gross_margin"]
    assert result.intent.time_range == TimeRange("2026-09", "2026-09", "single")

    result = parse("营业成本和毛利")
    assert result.intent.metrics == ["cost", "gross_profit"]


def test_dimensions_and_filters():
    result = parse("按区域拆一下")
    assert result.intent.dimensions == ["region"]
    assert result.intent.metrics == []
    assert not result.fallback

    result = parse("只看华东")
    assert result.intent.filters == {"region": ["华东"]}
    assert result.intent.dimensions == []

    result = parse("华东线上收入")
    assert result.intent.filters == {"region": ["华东"], "channel": ["线上"]}


def test_share_topn_comparison_growth():
    result = parse("2025年各产品线收入占比")
    assert result.intent.dimensions == ["product_line"]
    assert result.intent.share is True
    assert result.intent.time_range == TimeRange("2025-01", "2025-12", "year")

    result = parse("前5大区域收入")
    assert result.intent.top_n == 5
    assert result.intent.dimensions == ["region"]

    result = parse("收入同比增长最快的产品线")
    assert result.intent.comparison == "yoy"
    assert result.intent.dimensions == ["product_line"]
    assert result.intent.sort_by == "growth"


def test_out_of_range_time_is_flagged():
    assert parse("2023年收入").out_of_range is True
    assert parse("2026年11月收入").out_of_range is True
    assert parse("2025年收入").out_of_range is False
    assert parse("今年收入").out_of_range is False


def test_attribution_and_fallback():
    result = parse("为什么上月毛利下降了")
    assert result.intent.metrics == ["gross_profit"]
    assert result.intent.attribution == "down"
    assert result.intent.time_range == TimeRange("2026-09", "2026-09", "single")

    result = parse("你好")
    assert result.fallback is True
