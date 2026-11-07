"""查询引擎编排层。

v1 使用 RuleEngine（规则解析）；LLMEngine 为预留接口。
替换问答引擎时，只需让新引擎产出同样的 Intent / Answer，其余链路不变。
"""

from __future__ import annotations

import sqlite3
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from attribution import attribute
from intent import Intent, TimeRange, default_time_for_comparison, merge
from parser import SUPPORTED_EXAMPLES, parse
from presenters import (
    attribution_dataframe,
    build_conclusion,
    comparison_dataframe,
    display_dataframe,
    metric_definitions,
    render_chart,
)
from schema import AS_OF_MONTH, DATA_END, DATA_START, DIMENSIONS, METRICS
from sql_builder import build_comparison_queries, build_sql


@dataclass
class Answer:
    question: str
    conclusion: str
    table: pd.DataFrame | None = None
    figure: object | None = None
    # (标签, SQL, 参数)
    sql_list: list[tuple[str, str, list]] = field(default_factory=list)
    timing_ms: float = 0.0
    metric_defs: list[dict] = field(default_factory=list)
    intent: Intent | None = None
    mode: str = "query"  # query | comparison | attribution | fallback | error
    warning: str | None = None
    suggestions: list[str] = field(default_factory=list)
    fallback: bool = False


class QueryEngine(ABC):
    @abstractmethod
    def run(
        self,
        question: str,
        prev_intent: Intent | None = None,
        theme: str = "light",
    ) -> Answer: ...


class RuleEngine(QueryEngine):
    """规则 + 模板引擎：parse → merge → SQL → query → attribution/present。"""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    def _query(
        self, conn: sqlite3.Connection, intent: Intent
    ) -> tuple[pd.DataFrame, str, list, float]:
        sql, params = build_sql(intent)
        started = time.perf_counter()
        df = pd.read_sql_query(sql, conn, params=params)
        elapsed_ms = (time.perf_counter() - started) * 1000
        return df, sql, params, elapsed_ms

    @staticmethod
    def _ensure_time(intent: Intent) -> Intent:
        if intent.time_range is not None:
            return intent
        if intent.comparison == "yoy":
            intent.time_range = default_time_for_comparison("yoy", AS_OF_MONTH)
        else:
            intent.time_range = TimeRange(AS_OF_MONTH, AS_OF_MONTH, "single")
        return intent

    def run(
        self,
        question: str,
        prev_intent: Intent | None = None,
        theme: str = "light",
    ) -> Answer:
        parsed = parse(question, AS_OF_MONTH)
        if parsed.out_of_range and not parsed.fallback:
            return Answer(
                question=question,
                conclusion=(
                    f"当前模拟数据只覆盖 {DATA_START} 至 {DATA_END}，"
                    "请换一个时间范围再问。"
                ),
                intent=prev_intent,
                mode="notice",
                warning="时间超出数据范围",
                suggestions=SUPPORTED_EXAMPLES,
            )
        if parsed.fallback:
            return Answer(
                question=question,
                conclusion=(
                    "抱歉，我还不能理解这个问题。可以试着问收入、成本、毛利、"
                    "费用、净利润、订单量等指标，并带上时间或维度。"
                ),
                intent=prev_intent,
                mode="fallback",
                fallback=True,
                suggestions=SUPPORTED_EXAMPLES,
            )

        merged = merge(prev_intent, parsed)
        if not merged.metrics:
            merged.metrics = ["revenue"]
        merged = self._ensure_time(merged)

        conn = sqlite3.connect(self.db_path)
        try:
            if merged.attribution:
                return self._run_attribution(conn, question, merged, theme)
            if merged.comparison:
                return self._run_comparison(conn, question, merged, theme)
            return self._run_query(conn, question, merged, theme)
        except Exception as exc:  # 演示环境：把失败原因直接展示给用户
            return Answer(
                question=question,
                conclusion=f"查询失败：{exc}",
                intent=merged,
                mode="error",
                warning=str(exc),
            )
        finally:
            conn.close()

    def _run_query(
        self,
        conn: sqlite3.Connection,
        question: str,
        intent: Intent,
        theme: str,
    ) -> Answer:
        df, sql, params, elapsed_ms = self._query(conn, intent)
        if df.empty:
            return Answer(
                question=question,
                conclusion="未查询到符合条件的数据，请尝试调整时间、维度或过滤条件。",
                intent=intent,
                sql_list=[("查询 SQL", sql, params)],
                timing_ms=elapsed_ms,
                metric_defs=metric_definitions(intent.metrics),
                warning="空结果",
            )

        figure = render_chart(intent, df, theme=theme)
        return Answer(
            question=question,
            conclusion=build_conclusion(intent, df),
            table=display_dataframe(intent, df),
            figure=figure,
            sql_list=[("查询 SQL", sql, params)],
            timing_ms=elapsed_ms,
            metric_defs=metric_definitions(intent.metrics),
            intent=intent,
        )

    def _run_comparison(
        self,
        conn: sqlite3.Connection,
        question: str,
        intent: Intent,
        theme: str,
    ) -> Answer:
        # 时间维度不能用于跨期对比：当期 2026-09 与基期 2025-09 的月份桶无法对齐。
        effective = intent.clone()
        effective.dimensions = [
            dim for dim in intent.dimensions if not DIMENSIONS[dim]["is_time"]
        ]

        queries = build_comparison_queries(effective, AS_OF_MONTH)
        if queries is None:
            return Answer(
                question=question,
                conclusion="对比基期超出当前数据范围，暂时无法计算同比 / 环比。",
                intent=effective,
                warning="基期无数据",
                metric_defs=metric_definitions(effective.metrics),
            )

        started = time.perf_counter()
        current_df = pd.read_sql_query(
            queries["current_sql"], conn, params=queries["current_params"]
        )
        baseline_df = pd.read_sql_query(
            queries["baseline_sql"], conn, params=queries["baseline_params"]
        )
        elapsed_ms = (time.perf_counter() - started) * 1000

        if current_df.empty or baseline_df.empty:
            return Answer(
                question=question,
                conclusion="当期或基期没有数据，无法计算对比。",
                intent=effective,
                sql_list=[
                    ("当期查询", queries["current_sql"], queries["current_params"]),
                    ("基期查询", queries["baseline_sql"], queries["baseline_params"]),
                ],
                timing_ms=elapsed_ms,
                metric_defs=metric_definitions(effective.metrics),
                warning="对比数据为空",
            )

        dims = [d for d in effective.dimensions if d in DIMENSIONS]
        metrics = [m for m in effective.metrics if m in METRICS]
        table = self._build_comparison_table(
            current_df, baseline_df, dims, metrics, effective
        )

        comparison = {
            "table": table,
            "dims": dims,
            "metrics": metrics,
            "current_label": queries["current_range"].label(),
            "baseline_label": queries["baseline_range"].label(),
            "comparison": effective.comparison,
            "sort_by": effective.sort_by,
        }
        figure = render_chart(effective, table, comparison=comparison, theme=theme)
        return Answer(
            question=question,
            conclusion=build_conclusion(effective, table, comparison=comparison),
            table=comparison_dataframe(comparison),
            figure=figure,
            sql_list=[
                ("当期查询", queries["current_sql"], queries["current_params"]),
                ("基期查询", queries["baseline_sql"], queries["baseline_params"]),
            ],
            timing_ms=elapsed_ms,
            metric_defs=metric_definitions(metrics),
            intent=effective,
            mode="comparison",
        )

    @staticmethod
    def _build_comparison_table(
        current_df: pd.DataFrame,
        baseline_df: pd.DataFrame,
        dims: list[str],
        metrics: list[str],
        intent: Intent,
    ) -> pd.DataFrame:
        if dims:
            current = current_df[dims + metrics].copy()
            baseline = baseline_df[dims + metrics].copy()
            table = current.merge(
                baseline, on=dims, how="outer", suffixes=("__current", "__baseline")
            )
        else:
            row: dict[str, float] = {}
            for metric in metrics:
                row[f"{metric}__current"] = current_df.iloc[0][metric]
                row[f"{metric}__baseline"] = baseline_df.iloc[0][metric]
            table = pd.DataFrame([row])

        for metric in metrics:
            current_col = f"{metric}__current"
            baseline_col = f"{metric}__baseline"
            if METRICS[metric]["additive"]:
                table[current_col] = table[current_col].fillna(0.0)
                table[baseline_col] = table[baseline_col].fillna(0.0)
            table[f"{metric}__delta"] = table[current_col] - table[baseline_col]
            if METRICS[metric]["kind"] == "percent":
                # 比率指标的变化单位是百分点。
                table[f"{metric}__rate"] = table[f"{metric}__delta"]
            else:
                denominator = table[baseline_col].abs().where(
                    table[baseline_col].abs() > 1e-9
                )
                table[f"{metric}__rate"] = table[f"{metric}__delta"] / denominator

        if dims and len(table) > 1:
            metric = metrics[0]
            if intent.sort_by == "growth":
                sort_col = f"{metric}__rate"
            else:
                sort_col = f"{metric}__current"
            table = table.sort_values(sort_col, ascending=False, na_position="last")
            table = table.reset_index(drop=True)
        return table

    def _run_attribution(
        self,
        conn: sqlite3.Connection,
        question: str,
        intent: Intent,
        theme: str,
    ) -> Answer:
        sqls: list[tuple[str, str, list]] = []
        timing = {"ms": 0.0}

        def get_data(query_intent: Intent) -> pd.DataFrame:
            df, sql, params, elapsed_ms = self._query(conn, query_intent)
            sqls.append(("归因查询", sql, params))
            timing["ms"] += elapsed_ms
            return df

        result = attribute(intent, get_data, AS_OF_MONTH)
        if result is None:
            return Answer(
                question=question,
                conclusion="没有足够的数据做归因分析，请尝试缩小时间范围或指定维度。",
                intent=intent,
                metric_defs=metric_definitions(intent.metrics),
                warning="归因数据不足",
                mode="attribution",
            )

        figure = render_chart(
            intent, result.movers, attribution=result, theme=theme
        )

        # 只展示最终归因用到的 4 条代表性 SQL，避免把候选维度的查询全部抛给用户。
        base_intent = intent.clone()
        base_intent.metrics = [result.analysis_metric]
        base_intent.dimensions = []
        base_intent.top_n = None
        base_intent.comparison = None
        base_intent.attribution = None
        base_intent.share = False
        base_intent.sort_by = None

        current_total = base_intent.clone()
        current_total.time_range = result.current_range
        baseline_total = base_intent.clone()
        baseline_total.time_range = result.baseline_range
        current_group = current_total.clone()
        current_group.dimensions = [result.dimension]
        baseline_group = baseline_total.clone()
        baseline_group.dimensions = [result.dimension]

        representative_sqls = []
        dim_label = DIMENSIONS[result.dimension]["name"]
        for label, query_intent in (
            (f"{result.current_label}汇总", current_total),
            (f"{result.baseline_label}汇总", baseline_total),
            (f"{result.current_label}·按{dim_label}", current_group),
            (f"{result.baseline_label}·按{dim_label}", baseline_group),
        ):
            sql, params = build_sql(query_intent)
            representative_sqls.append((label, sql, params))

        return Answer(
            question=question,
            conclusion=result.narrative,
            table=attribution_dataframe(result),
            figure=figure,
            sql_list=representative_sqls,
            timing_ms=timing["ms"],
            metric_defs=metric_definitions(
                list(dict.fromkeys(intent.metrics + [result.analysis_metric]))
            ),
            intent=intent,
            mode="attribution",
        )


class LLMEngine(QueryEngine):
    """预留接口：接入大模型后，用它把问题解析成同样的 Intent。

    v1 不启用；接入时只需实现 run()，复用 RuleEngine 的 SQL / 展示逻辑。
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    def run(
        self,
        question: str,
        prev_intent: Intent | None = None,
        theme: str = "light",
    ) -> Answer:
        raise NotImplementedError(
            "v1 使用规则引擎。接入大模型时，将问题解析为 Intent 后复用查询与展示链路。"
        )


def create_engine(db_path: str | Path) -> QueryEngine:
    return RuleEngine(db_path)
