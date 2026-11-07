"""同/环比归因：找出最能解释指标波动的维度与取值。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from formatters import (
    dimension_name,
    format_metric_abs_delta,
    format_metric_delta,
    format_metric_value,
    metric_name,
)
from intent import Intent, TimeRange, baseline_time_range
from schema import AS_OF_MONTH, DIMENSIONS, METRICS

# 比率指标不可加，归因时降级到对应的可加指标。
RATIO_FALLBACK = {
    "gross_margin": "gross_profit",
    "net_margin": "net_profit",
    "avg_order_value": "revenue",
}

CANDIDATE_DIMENSIONS = ("region", "product_line", "channel")


@dataclass
class AttributionResult:
    requested_metric: str
    analysis_metric: str
    dimension: str
    current_range: TimeRange
    baseline_range: TimeRange
    current_label: str
    baseline_label: str
    current_total: float
    baseline_total: float
    delta: float
    direction: str
    movers: pd.DataFrame
    narrative: str
    note: str = ""


def _merge_periods(
    current_df: pd.DataFrame, baseline_df: pd.DataFrame, dim: str, metric: str
) -> pd.DataFrame | None:
    if current_df.empty or baseline_df.empty:
        return None
    if dim not in current_df.columns or dim not in baseline_df.columns:
        return None
    if metric not in current_df.columns or metric not in baseline_df.columns:
        return None

    merged = current_df[[dim, metric]].merge(
        baseline_df[[dim, metric]],
        on=dim,
        how="outer",
        suffixes=("_current", "_baseline"),
    )
    merged = merged.fillna(0.0)
    merged["contribution"] = merged[f"{metric}_current"] - merged[f"{metric}_baseline"]
    merged = merged.rename(
        columns={
            f"{metric}_current": "current",
            f"{metric}_baseline": "baseline",
        }
    )
    return merged


def _movers_text(movers: pd.DataFrame, dim: str, delta: float, metric: str) -> str:
    negatives = movers[movers["contribution"] < -1e-9].sort_values("contribution").head(3)
    positives = movers[movers["contribution"] > 1e-9].sort_values(
        "contribution", ascending=False
    ).head(2)

    direction_label = "增幅" if delta > 0 else "降幅"

    def describe(row: pd.Series) -> str:
        value = row[dim]
        contribution = row["contribution"]
        share = row.get("share")
        magnitude = format_metric_delta(metric, contribution)
        if share is None or abs(share) < 1e-6:
            return f"{value}（{magnitude}）"
        if (contribution > 0) == (delta > 0):
            return f"{value}（{magnitude}，占{direction_label}{abs(share) * 100:.1f}%）"
        return f"{value}（{magnitude}，抵消{abs(share) * 100:.1f}%）"

    if delta < 0:
        drivers = negatives
        offsets = positives
    else:
        drivers = positives
        offsets = negatives

    driver_text = "、".join(describe(row) for _, row in drivers.iterrows())
    offset_text = "、".join(describe(row) for _, row in offsets.iterrows())

    if driver_text and offset_text:
        return f"主要由{driver_text}贡献；{offset_text}部分抵消。"
    if driver_text:
        return f"主要由{driver_text}贡献。"
    if offset_text:
        return f"主要受{offset_text}影响。"
    return "各维度贡献较为分散。"


def attribute(
    intent: Intent,
    get_data: Callable[[Intent], pd.DataFrame],
    as_of: str = AS_OF_MONTH,
) -> AttributionResult | None:
    """对上一轮指标做维度归因。

    get_data(intent) 由 engine 注入，返回聚合后的 DataFrame，
    这样归因模块不需要知道数据库连接与 SQL 构建细节。
    """
    if not intent.metrics:
        return None

    requested_metric = intent.metrics[0]
    analysis_metric = RATIO_FALLBACK.get(requested_metric, requested_metric)
    if not METRICS[analysis_metric]["additive"]:
        analysis_metric = "revenue"

    note = ""
    if analysis_metric != requested_metric:
        note = (
            f"{metric_name(requested_metric)}为比率指标，以下从"
            f"{metric_name(analysis_metric)}变动角度归因。"
        )

    current_time = intent.time_range or TimeRange(as_of, as_of, "single")
    baseline_range = baseline_time_range(
        current_time,
        intent.comparison,
        for_attribution=True,
        as_of=as_of,
    )
    if baseline_range is None:
        return None

    current_intent = intent.clone()
    current_intent.metrics = [analysis_metric]
    current_intent.dimensions = []
    current_intent.top_n = None
    current_intent.comparison = None
    current_intent.attribution = None
    current_intent.share = False
    current_intent.sort_by = None
    current_intent.time_range = current_time

    baseline_intent = current_intent.clone()
    baseline_intent.time_range = baseline_range

    current_total_df = get_data(current_intent)
    baseline_total_df = get_data(baseline_intent)
    if current_total_df.empty or baseline_total_df.empty:
        return None

    current_total = float(current_total_df.iloc[0][analysis_metric])
    baseline_total = float(baseline_total_df.iloc[0][analysis_metric])
    delta = current_total - baseline_total

    candidates: list[str] = []
    preferred = [d for d in intent.dimensions if d in CANDIDATE_DIMENSIONS]
    for dim in preferred + list(CANDIDATE_DIMENSIONS):
        if dim in candidates:
            continue
        # 已被过滤到单一取值的维度无法解释差异。
        if len(intent.filters.get(dim, [])) == 1:
            continue
        candidates.append(dim)
    if not candidates:
        candidates = list(CANDIDATE_DIMENSIONS)

    best: tuple[float, str, pd.DataFrame] | None = None
    for dim in candidates:
        current_group = current_intent.clone()
        current_group.dimensions = [dim]
        baseline_group = baseline_intent.clone()
        baseline_group.dimensions = [dim]

        merged = _merge_periods(
            get_data(current_group),
            get_data(baseline_group),
            dim,
            analysis_metric,
        )
        if merged is None or merged.empty:
            continue
        strongest = float(merged["contribution"].abs().max())
        if best is None or strongest > best[0]:
            best = (strongest, dim, merged)

    if best is None:
        return None

    _, best_dim, movers = best
    movers = movers.copy()
    if abs(delta) > 1e-9:
        movers["share"] = movers["contribution"] / delta
    else:
        movers["share"] = None
    movers = movers.sort_values("contribution", ascending=True).reset_index(drop=True)

    direction = "下降" if delta < 0 else ("上升" if delta > 0 else "基本持平")
    change_rate = ""
    if abs(baseline_total) > 1e-9:
        change_rate = f"（{delta / abs(baseline_total) * 100:+.1f}%）"

    if abs(delta) < 1e-9:
        narrative = (
            f"{current_time.label()}的{metric_name(analysis_metric)}与"
            f"{baseline_range.label()}基本持平，各维度无明显贡献差异。"
        )
    else:
        narrative = (
            f"{current_time.label()}的{metric_name(analysis_metric)}为"
            f"{format_metric_value(analysis_metric, current_total)}，"
            f"较{baseline_range.label()}{direction}"
            f"{format_metric_abs_delta(analysis_metric, delta)}{change_rate}。"
            f"按{dimension_name(best_dim)}拆解，"
            + _movers_text(movers, best_dim, delta, analysis_metric)
        )
    if note:
        narrative += f"（{note}）"

    return AttributionResult(
        requested_metric=requested_metric,
        analysis_metric=analysis_metric,
        dimension=best_dim,
        current_range=current_time,
        baseline_range=baseline_range,
        current_label=current_time.label(),
        baseline_label=baseline_range.label(),
        current_total=current_total,
        baseline_total=baseline_total,
        delta=delta,
        direction=direction,
        movers=movers,
        narrative=narrative,
        note=note,
    )
