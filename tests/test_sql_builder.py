import pytest

from intent import Intent, TimeRange
from parser import parse
from sql_builder import build_comparison_queries, build_sql


def test_time_filter_and_params():
    intent = parse("今年收入是多少").intent
    sql, params = build_sql(intent)

    assert "SUM(revenue)" in sql
    assert "month BETWEEN ? AND ?" in sql
    assert params[0] == "2026-01"
    assert params[1] == "2026-10"


def test_ratio_metric_has_zero_guard():
    intent = Intent(
        metrics=["gross_margin"],
        time_range=TimeRange("2026-01", "2026-10"),
    )
    sql, _ = build_sql(intent)

    assert "CASE WHEN SUM(revenue) = 0" in sql
    assert "SUM(revenue) - SUM(cost)" in sql


def test_group_by_and_order():
    intent = parse("2025年各产品线收入").intent
    sql, _ = build_sql(intent)
    assert "GROUP BY product_line" in sql
    assert "ORDER BY revenue DESC" in sql

    intent = parse("近6个月收入趋势").intent
    sql, _ = build_sql(intent)
    assert "GROUP BY month" in sql
    assert "ORDER BY month ASC" in sql


def test_topn_and_filters():
    intent = parse("前5大区域收入").intent
    sql, params = build_sql(intent)
    assert "ORDER BY revenue DESC" in sql
    assert params[-1] == 5

    intent = parse("华东线上收入").intent
    sql, params = build_sql(intent)
    assert "region IN (?)" in sql
    assert "channel IN (?)" in sql
    assert "华东" in params
    assert "线上" in params


def test_whitelist_rejects_unknown_dimension():
    intent = Intent(metrics=["revenue"], filters={"name": ["x"]})
    with pytest.raises(ValueError):
        build_sql(intent)


def test_yoy_baseline():
    intent = parse("上月收入同比").intent
    queries = build_comparison_queries(intent)

    assert queries is not None
    assert queries["current_range"].start == "2026-09"
    assert queries["baseline_range"].start == "2025-09"
