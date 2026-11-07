import pytest

from data_generator import init_db
from engine import RuleEngine


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("data") / "finance.db"
    return init_db(path, force=True)


@pytest.fixture(scope="module")
def engine(db_path):
    return RuleEngine(db_path)


def test_query_and_followups(engine):
    first = engine.run("今年收入是多少")
    assert first.mode == "query"
    assert first.fallback is False
    assert first.table is not None
    assert len(first.table) == 1
    assert first.intent.time_range.start == "2026-01"
    assert first.sql_list

    second = engine.run("那上个月呢", prev_intent=first.intent)
    assert second.intent.metrics == ["revenue"]
    assert second.intent.time_range.start == "2026-09"

    third = engine.run("按区域拆一下", prev_intent=second.intent)
    assert "区域" in third.table.columns
    assert len(third.table) == 4
    assert third.figure is not None


def test_trend_and_share(engine):
    trend = engine.run("近6个月收入趋势")
    assert trend.figure is not None
    assert "月份" in trend.table.columns
    assert len(trend.table) == 6

    share = engine.run("2025年各产品线收入占比")
    assert "占比" in share.table.columns
    assert share.table["占比"].notna().all()


def test_comparison(engine):
    answer = engine.run("上月收入同比")
    assert answer.mode == "comparison"
    assert answer.table is not None
    assert "同比" in answer.conclusion
    assert len(answer.sql_list) == 2


def test_attribution(engine):
    answer = engine.run("为什么上月毛利下降了")
    assert answer.mode == "attribution"
    assert answer.table is not None
    assert len(answer.table) >= 3
    assert "下降" in answer.conclusion or "上升" in answer.conclusion
    assert len(answer.sql_list) == 4


def test_comparison_drops_inherited_month_dimension(engine):
    trend = engine.run("近6个月收入趋势")
    assert "月份" in trend.table.columns

    answer = engine.run("上月毛利率是多少，同比怎么样？", prev_intent=trend.intent)
    assert answer.mode == "comparison"
    assert answer.table is not None
    assert "月份" not in answer.table.columns
    assert "同比" in answer.conclusion


def test_out_of_range_returns_notice(engine):
    answer = engine.run("2023年收入是多少")
    assert answer.mode == "notice"
    assert "2024-01" in answer.conclusion
    assert "2026-10" in answer.conclusion


def test_ratio_and_fallback(engine):
    ratio = engine.run("上月毛利率是多少")
    assert "%" in ratio.conclusion
    assert "CASE WHEN SUM(revenue) = 0" in ratio.sql_list[0][1]

    fallback = engine.run("今天天气怎么样")
    assert fallback.fallback is True
    assert fallback.suggestions
