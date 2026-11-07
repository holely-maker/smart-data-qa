"""图表、结论与表格展示。

图表遵循 dataviz 规范：
- 分类色按固定槽位分配，不循环生成新色
- 单指标排名用单一蓝色，占比用分类色，归因用蓝/红发散色
- 网格/坐标轴线为细实线，图例常驻，表格始终作为可访问的等价视图
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from attribution import AttributionResult
from formatters import (
    dimension_name,
    format_dim_value,
    format_metric_abs_delta,
    format_metric_delta,
    format_metric_value,
    format_percent,
    metric_name,
)
from intent import Intent
from schema import METRICS

FONT_FAMILY = 'system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif'

PALETTE = {
    "light": {
        "surface": "#fcfcfb",
        "page": "#f9f9f7",
        "text": "#0b0b0b",
        "secondary": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
        "series": [
            "#2a78d6",
            "#008300",
            "#e87ba4",
            "#eda100",
            "#1baf7a",
            "#eb6834",
            "#4a3aa7",
            "#e34948",
        ],
        "comparison": ["#2a78d6", "#eb6834"],
        "positive": "#2a78d6",
        "negative": "#e34948",
    },
    "dark": {
        "surface": "#1a1a19",
        "page": "#0d0d0d",
        "text": "#ffffff",
        "secondary": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
        "series": [
            "#3987e5",
            "#008300",
            "#d55181",
            "#c98500",
            "#199e70",
            "#d95926",
            "#9085e9",
            "#e66767",
        ],
        "comparison": ["#3987e5", "#d95926"],
        "positive": "#3987e5",
        "negative": "#e66767",
    },
}


def _palette(theme: str) -> dict:
    return PALETTE.get(theme, PALETTE["light"])


def _time_dims(intent: Intent) -> list[str]:
    return [d for d in intent.dimensions if d in ("month", "quarter")]


def _value_dims(intent: Intent) -> list[str]:
    return [d for d in intent.dimensions if d in ("product_line", "region", "channel")]


def _axis_format(metric: str) -> tuple[str, str]:
    kind = METRICS[metric]["kind"]
    if kind == "amount":
        return ",.0f", "万元"
    if kind == "percent":
        return ".0%", ""
    if kind == "count":
        return ",.0f", "单"
    if kind == "per_order":
        return ",.2f", "万元/单"
    return ",.0f", ""


def _hover_fmt(metric: str) -> str:
    kind = METRICS[metric]["kind"]
    if kind == "amount":
        return "%{y:,.1f} 万元"
    if kind == "percent":
        return "%{y:.1%}"
    if kind == "count":
        return "%{y:,.0f} 单"
    if kind == "per_order":
        return "%{y:,.2f} 万元/单"
    return "%{y:,.2f}"


def _compact_value(metric: str, value: float) -> str:
    kind = METRICS[metric]["kind"]
    if kind == "amount":
        if abs(value) >= 10000:
            return f"{value / 10000:,.1f}亿"
        return f"{value:,.0f}万"
    if kind == "percent":
        return f"{value * 100:,.1f}%"
    if kind == "count":
        return f"{value:,.0f}"
    if kind == "per_order":
        return f"{value:,.2f}"
    return f"{value:,.1f}"


def _base_figure(theme: str, title: str | None = None) -> go.Figure:
    colors = _palette(theme)
    fig = go.Figure()
    if title:
        fig.update_layout(
            title=dict(
                text=title,
                x=0,
                xanchor="left",
                font=dict(size=15, color=colors["text"], family=FONT_FAMILY),
            )
        )
    fig.update_layout(
        template=None,
        paper_bgcolor=colors["surface"],
        plot_bgcolor=colors["surface"],
        font=dict(family=FONT_FAMILY, color=colors["text"], size=13),
        margin=dict(l=12, r=24, t=56 if title else 20, b=12),
        hoverlabel=dict(
            bgcolor=colors["surface"],
            bordercolor=colors["grid"],
            font=dict(color=colors["text"], family=FONT_FAMILY),
        ),
        showlegend=False,
    )
    fig.update_xaxes(
        showgrid=False,
        showline=True,
        linecolor=colors["axis"],
        linewidth=1,
        ticks="",
        tickfont=dict(color=colors["muted"], size=12, family=FONT_FAMILY),
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor=colors["grid"],
        gridwidth=1,
        zeroline=False,
        showline=False,
        tickfont=dict(color=colors["muted"], size=12, family=FONT_FAMILY),
    )
    return fig


def _bottom_legend(fig: go.Figure, theme: str) -> None:
    colors = _palette(theme)
    fig.update_layout(
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.2,
            xanchor="left",
            x=0,
            font=dict(color=colors["secondary"], size=12, family=FONT_FAMILY),
            bgcolor="rgba(0,0,0,0)",
        ),
        margin=dict(b=64),
    )


def _chart_title(intent: Intent, metrics: list[str], kind: str = "line") -> str:
    period = intent.time_range.label() if intent.time_range else "数据截至 2026-10"
    metric_text = "、".join(metric_name(metric) for metric in metrics)
    dims = _value_dims(intent)
    if kind == "line":
        return f"{period} · {metric_text}趋势"
    if kind == "bar":
        prefix = f"各{dimension_name(dims[0])}" if dims else ""
        return f"{period} · {prefix}{metric_text}"
    if kind == "share":
        prefix = f"各{dimension_name(dims[0])}" if dims else ""
        return f"{period} · {prefix}{metric_text}占比"
    return f"{period} · {metric_text}"


def choose_chart(
    intent: Intent,
    df: pd.DataFrame,
    comparison: dict | None = None,
    attribution: AttributionResult | None = None,
) -> str:
    if attribution is not None:
        return "attribution"
    if comparison is not None:
        return "comparison" if comparison["dims"] and len(comparison["table"]) > 1 else "none"
    if df is None or df.empty:
        return "none"
    if intent.share and _value_dims(intent) and not _time_dims(intent):
        return "pie"
    if _time_dims(intent) and len(df) > 1:
        return "line"
    if _value_dims(intent) and len(df) > 1:
        return "bar"
    return "none"


def _line_chart(intent: Intent, df: pd.DataFrame, theme: str) -> go.Figure | None:
    colors = _palette(theme)
    time_dim = next((d for d in ("month", "quarter") if d in df.columns), None)
    metrics = [m for m in intent.metrics if m in df.columns][:4]
    if time_dim is None or not metrics or len(df) <= 1:
        return None

    x_labels = [format_dim_value(time_dim, value) for value in df[time_dim]]
    fig = _base_figure(theme, _chart_title(intent, metrics, "line"))
    for index, metric in enumerate(metrics):
        fig.add_trace(
            go.Scatter(
                x=x_labels,
                y=df[metric],
                mode="lines+markers",
                name=metric_name(metric),
                line=dict(color=colors["series"][index], width=2),
                marker=dict(
                    size=8,
                    color=colors["series"][index],
                    line=dict(color=colors["surface"], width=2),
                ),
                hovertemplate=f"{metric_name(metric)}：{_hover_fmt(metric)}<extra></extra>",
            )
        )

    tickformat, unit = _axis_format(metrics[0])
    fig.update_yaxes(
        tickformat=tickformat,
        title_text=unit,
        title_font=dict(color=colors["muted"], size=12),
    )
    fig.update_xaxes(type="category")
    if len(df) > 8:
        fig.update_xaxes(tickangle=-30)
    fig.update_layout(hovermode="x unified", showlegend=len(metrics) >= 2, height=380)
    if len(metrics) >= 2:
        _bottom_legend(fig, theme)
    return fig


def _bar_chart(intent: Intent, df: pd.DataFrame, theme: str) -> go.Figure | None:
    colors = _palette(theme)
    value_dims = [d for d in _value_dims(intent) if d in df.columns]
    metrics = [m for m in intent.metrics if m in df.columns]
    if not value_dims or not metrics:
        return None

    dim = value_dims[0]
    metric = metrics[0]
    data = df[[dim, metric]].dropna().sort_values(metric, ascending=True)
    if len(data) <= 1:
        return None

    labels = [format_dim_value(dim, value) for value in data[dim]]
    values = data[metric].tolist()
    fig = _base_figure(theme, _chart_title(intent, [metric], "bar"))
    fig.add_trace(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(color=colors["series"][0], line=dict(width=0)),
            text=[_compact_value(metric, value) for value in values],
            textposition="outside",
            textfont=dict(color=colors["secondary"], size=11, family=FONT_FAMILY),
            cliponaxis=False,
            width=0.55,
            hovertemplate=f"{metric_name(metric)}：{_hover_fmt(metric)}<extra></extra>",
        )
    )
    tickformat, unit = _axis_format(metric)
    fig.update_xaxes(
        tickformat=tickformat,
        title_text=unit,
        title_font=dict(color=colors["muted"], size=12),
        showgrid=True,
        gridcolor=colors["grid"],
        showline=False,
        zeroline=False,
    )
    fig.update_yaxes(showgrid=False, automargin=True)
    fig.update_layout(
        height=max(320, 44 * len(data) + 100),
        margin=dict(l=12, r=110, t=56, b=16),
    )
    return fig


def _pie_chart(intent: Intent, df: pd.DataFrame, theme: str) -> go.Figure | None:
    colors = _palette(theme)
    value_dims = [d for d in _value_dims(intent) if d in df.columns]
    metrics = [m for m in intent.metrics if m in df.columns]
    if not value_dims or not metrics:
        return None

    dim = value_dims[0]
    metric = metrics[0]
    data = df[[dim, metric]].dropna()
    data = data[data[metric] > 0]
    if len(data) < 2 or data[metric].sum() <= 0:
        return None

    if len(data) > 6:
        data = data.sort_values(metric, ascending=False)
        head = data.head(5)
        other_value = data.iloc[5:][metric].sum()
        data = pd.concat(
            [
                head,
                pd.DataFrame({dim: ["其他"], metric: [other_value]}),
            ],
            ignore_index=True,
        )

    unit = METRICS[metric]["unit"]
    fig = _base_figure(theme, _chart_title(intent, [metric], "share"))
    fig.add_trace(
        go.Pie(
            labels=[format_dim_value(dim, value) for value in data[dim]],
            values=data[metric],
            hole=0.45,
            sort=False,
            marker=dict(
                colors=colors["series"][: len(data)],
                line=dict(color=colors["surface"], width=2),
            ),
            textinfo="label+percent",
            textfont=dict(color=colors["text"], size=12, family=FONT_FAMILY),
            hovertemplate="%{label}：%{value:,.1f} "
            + unit
            + "<br>占比 %{percent}<extra></extra>",
        )
    )
    fig.update_layout(height=380, margin=dict(l=12, r=12, t=56, b=12), showlegend=False)
    return fig


def _comparison_chart(comparison: dict, theme: str) -> go.Figure | None:
    colors = _palette(theme)
    table = comparison["table"]
    dims = comparison["dims"]
    if not dims or len(table) <= 1:
        return None

    metric = comparison["metrics"][0]
    current_label = comparison["current_label"]
    baseline_label = comparison["baseline_label"]
    labels = []
    for _, row in table.iterrows():
        labels.append(" / ".join(format_dim_value(dim, row[dim]) for dim in dims))

    current = table[f"{metric}__current"]
    baseline = table[f"{metric}__baseline"]
    fig = _base_figure(
        theme,
        f"{metric_name(metric)}对比 · {current_label} vs {baseline_label}",
    )
    fig.add_trace(
        go.Bar(
            x=labels,
            y=current,
            name=current_label,
            marker_color=colors["comparison"][0],
            width=0.38,
            hovertemplate=f"{current_label}：{_hover_fmt(metric)}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=labels,
            y=baseline,
            name=baseline_label,
            marker_color=colors["comparison"][1],
            width=0.38,
            hovertemplate=f"{baseline_label}：{_hover_fmt(metric)}<extra></extra>",
        )
    )
    tickformat, unit = _axis_format(metric)
    fig.update_yaxes(tickformat=tickformat, title_text=unit)
    fig.update_layout(
        barmode="group",
        bargap=0.35,
        bargroupgap=0.08,
        height=390,
        showlegend=True,
    )
    fig.update_xaxes(type="category")
    if len(labels) > 6:
        fig.update_xaxes(tickangle=-25)
    _bottom_legend(fig, theme)
    return fig


def _attribution_chart(
    attribution: AttributionResult, theme: str
) -> go.Figure | None:
    colors = _palette(theme)
    data = attribution.movers.copy()
    if len(data) <= 1:
        return None

    data = data.sort_values("contribution", ascending=True)
    dim = attribution.dimension
    metric = attribution.analysis_metric
    contributions = data["contribution"].tolist()
    fig = _base_figure(
        theme,
        f"{metric_name(metric)}变化贡献 · {attribution.current_label} vs {attribution.baseline_label}",
    )
    fig.add_trace(
        go.Bar(
            x=contributions,
            y=[format_dim_value(dim, value) for value in data[dim]],
            orientation="h",
            marker_color=[
                colors["negative"] if value < 0 else colors["positive"]
                for value in contributions
            ],
            width=0.55,
            hovertemplate=f"%{{x}} 的{metric_name(metric)}变化<extra></extra>",
        )
    )
    fig.add_vline(x=0, line_width=1, line_color=colors["axis"])
    tickformat, unit = _axis_format(metric)
    fig.update_xaxes(
        tickformat=tickformat,
        title_text=unit,
        title_font=dict(color=colors["muted"], size=12),
        showgrid=True,
        gridcolor=colors["grid"],
        zeroline=False,
    )
    fig.update_yaxes(showgrid=False, automargin=True)
    fig.update_layout(
        height=max(320, 44 * len(data) + 110),
        margin=dict(l=12, r=130, t=56, b=16),
    )
    return fig


def render_chart(
    intent: Intent,
    df: pd.DataFrame,
    comparison: dict | None = None,
    attribution: AttributionResult | None = None,
    theme: str = "light",
) -> go.Figure | None:
    kind = choose_chart(intent, df, comparison, attribution)
    if kind == "attribution":
        return _attribution_chart(attribution, theme)  # type: ignore[arg-type]
    if kind == "comparison":
        return _comparison_chart(comparison, theme)  # type: ignore[arg-type]
    if kind == "line":
        return _line_chart(intent, df, theme)
    if kind == "bar":
        return _bar_chart(intent, df, theme)
    if kind == "pie":
        return _pie_chart(intent, df, theme)
    return None


def _period_label(intent: Intent) -> str:
    return intent.time_range.label() if intent.time_range else "当前数据"


def _scope_label(intent: Intent) -> str:
    """期间 + 过滤条件，让结论明确当前分析口径。"""
    period = _period_label(intent)
    values: list[str] = []
    for dim_values in intent.filters.values():
        values.extend(dim_values)
    if values:
        return f"{period}（{'、'.join(values)}）"
    return period


def _scalar_conclusion(intent: Intent, df: pd.DataFrame, metrics: list[str]) -> str:
    row = df.iloc[0]
    parts = [
        f"{metric_name(metric)}为{format_metric_value(metric, row[metric])}"
        for metric in metrics
    ]
    return f"{_scope_label(intent)}，" + "，".join(parts) + "。"


def _trend_conclusion(
    intent: Intent, df: pd.DataFrame, metrics: list[str], time_dim: str
) -> str:
    metric = metrics[0]
    data = df.dropna(subset=[metric]).sort_values(time_dim)
    if data.empty:
        return "未查询到符合条件的数据。"
    first = data.iloc[0]
    last = data.iloc[-1]
    peak = data.loc[data[metric].idxmax()]
    change = last[metric] - first[metric]
    direction = "上升" if change > 0 else ("下降" if change < 0 else "基本持平")
    rate_text = ""
    if abs(first[metric]) > 1e-9:
        rate_text = f"（{change / abs(first[metric]) * 100:+.1f}%）"

    first_label = format_dim_value(time_dim, first[time_dim])
    last_label = format_dim_value(time_dim, last[time_dim])
    peak_label = format_dim_value(time_dim, peak[time_dim])

    if change == 0:
        change_text = "整体基本持平"
    elif METRICS[metric]["kind"] == "percent":
        change_text = f"变化{format_metric_abs_delta(metric, change)}"
    else:
        change_text = f"累计{direction}{format_metric_abs_delta(metric, change)}{rate_text}"

    text = (
        f"{_scope_label(intent)}，{metric_name(metric)}从{first_label}的"
        f"{format_metric_value(metric, first[metric])}变为{last_label}的"
        f"{format_metric_value(metric, last[metric])}，{change_text}；"
        f"期间最高为{peak_label}的{format_metric_value(metric, peak[metric])}。"
    )
    if len(metrics) > 1:
        extras = "、".join(
            f"{metric_name(m)}期末为{format_metric_value(m, last[m])}"
            for m in metrics[1:]
        )
        text += f"同期，{extras}。"
    return text


def _grouped_conclusion(
    intent: Intent, df: pd.DataFrame, metrics: list[str], dim: str
) -> str:
    metric = metrics[0]
    data = df.dropna(subset=[metric]).sort_values(metric, ascending=False)
    if data.empty:
        return "未查询到符合条件的数据。"

    dim_label = dimension_name(dim)
    top = data.iloc[0]
    bottom = data.iloc[-1]
    prefix = f"{_scope_label(intent)}，按{dim_label}看，"
    top_value = format_dim_value(dim, top[dim])
    bottom_value = format_dim_value(dim, bottom[dim])
    top_metric = format_metric_value(metric, top[metric])
    bottom_metric = format_metric_value(metric, bottom[metric])

    if METRICS[metric]["additive"] and data[metric].sum() > 0:
        total = data[metric].sum()
        share = top[metric] / total * 100
        return (
            f"{prefix}{top_value}的{metric_name(metric)}最高，为{top_metric}，"
            f"占{share:.1f}%；{bottom_value}最低，为{bottom_metric}。"
        )
    return (
        f"{prefix}{metric_name(metric)}最高的是{top_value}（{top_metric}），"
        f"最低的是{bottom_value}（{bottom_metric}）。"
    )


def _share_conclusion(
    intent: Intent, df: pd.DataFrame, metric: str, dim: str
) -> str:
    data = df.dropna(subset=[metric])
    total = data[metric].sum()
    if total <= 0:
        return _grouped_conclusion(intent, df, [metric], dim)

    data = data.assign(_share=data[metric] / total).sort_values(metric, ascending=False)
    top = data.iloc[0]
    dim_label = dimension_name(dim)
    top_value = format_dim_value(dim, top[dim])
    text = (
        f"{_scope_label(intent)}，{metric_name(metric)}中{top_value}占比最高，"
        f"为{format_metric_value(metric, top[metric])}（{top['_share'] * 100:.1f}%）"
    )
    if len(data) > 1:
        second = data.iloc[1]
        text += (
            f"，其次是{format_dim_value(dim, second[dim])}"
            f"（{second['_share'] * 100:.1f}%）"
        )
    return text + "。"


def _comparison_conclusion(comparison: dict) -> str:
    table = comparison["table"]
    dims = comparison["dims"]
    metric = comparison["metrics"][0]
    kind = METRICS[metric]["kind"]
    current_label = comparison["current_label"]
    baseline_label = comparison["baseline_label"]
    comp_word = "同比" if comparison["comparison"] == "yoy" else "环比"

    current_col = f"{metric}__current"
    baseline_col = f"{metric}__baseline"
    delta_col = f"{metric}__delta"
    rate_col = f"{metric}__rate"

    if not dims or len(table) == 1:
        row = table.iloc[0]
        current_value = row[current_col]
        baseline_value = row[baseline_col]
        delta = row[delta_col]
        if kind == "percent":
            return (
                f"{current_label}{metric_name(metric)}为{format_percent(current_value)}，"
                f"较{baseline_label}的{format_percent(baseline_value)}"
                f"{'提高' if delta >= 0 else '下降'}"
                f"{format_metric_abs_delta(metric, delta)}（{comp_word}）。"
            )
        rate = row[rate_col]
        rate_text = f"{rate * 100:+.1f}%" if pd.notna(rate) else "—"
        return (
            f"{current_label}{metric_name(metric)}为{format_metric_value(metric, current_value)}，"
            f"较{baseline_label}的{format_metric_value(metric, baseline_value)}"
            f"{'上升' if delta >= 0 else '下降'}"
            f"{format_metric_abs_delta(metric, delta)}（{rate_text}，{comp_word}）。"
        )

    total_text = ""
    if kind in ("amount", "count"):
        current_total = float(table[current_col].sum())
        baseline_total = float(table[baseline_col].sum())
        delta = current_total - baseline_total
        rate_text = ""
        if abs(baseline_total) > 1e-9:
            rate_text = f"，{delta / abs(baseline_total) * 100:+.1f}%"
        total_text = (
            f"{current_label}{metric_name(metric)}合计"
            f"{format_metric_value(metric, current_total)}，较{baseline_label}"
            f"{'上升' if delta >= 0 else '下降'}"
            f"{format_metric_abs_delta(metric, delta)}{rate_text}。"
        )

    data = table.dropna(subset=[current_col, baseline_col]).copy()
    if data.empty:
        return total_text or "未查询到可对比的数据。"
    if kind == "percent":
        data = data.sort_values(delta_col, ascending=False)
    elif comparison.get("sort_by") == "growth":
        data = data.sort_values(rate_col, ascending=False)
    else:
        data = data.sort_values(current_col, ascending=False)
    best = data.iloc[0]
    worst = data.iloc[-1]

    def row_label(row: pd.Series) -> str:
        return " / ".join(format_dim_value(dim, row[dim]) for dim in dims)

    dim_label = dimension_name(dims[0]) if len(dims) == 1 else "维度组合"
    if kind == "percent":
        best_delta = best[delta_col]
        worst_delta = worst[delta_col]
        best_word = "提升最多" if best_delta >= 0 else "下降最少"
        worst_word = "提升最少" if worst_delta >= 0 else "下降最多"
        detail = (
            f"按{dim_label}看，{row_label(best)}的{metric_name(metric)}{comp_word}{best_word}"
            f"（{format_metric_delta(metric, best_delta)}，"
            f"当前{format_percent(best[current_col])}），"
            f"{row_label(worst)}{comp_word}{worst_word}"
            f"（{format_metric_delta(metric, worst_delta)}，"
            f"当前{format_percent(worst[current_col])}）。"
        )
    else:
        best_rate = best[rate_col]
        worst_rate = worst[rate_col]
        best_rate_text = f"{best_rate * 100:+.1f}%" if pd.notna(best_rate) else "—"
        worst_rate_text = f"{worst_rate * 100:+.1f}%" if pd.notna(worst_rate) else "—"
        best_word = "增幅最大" if pd.notna(best_rate) and best_rate >= 0 else "降幅最小"
        worst_word = "增幅最小" if pd.notna(worst_rate) and worst_rate >= 0 else "降幅最大"
        detail = (
            f"按{dim_label}看，{row_label(best)}的{comp_word}{best_word}"
            f"（{best_rate_text}），{row_label(worst)}的{comp_word}{worst_word}"
            f"（{worst_rate_text}）。"
        )

    return total_text + detail


def build_conclusion(
    intent: Intent,
    df: pd.DataFrame,
    comparison: dict | None = None,
    attribution: AttributionResult | None = None,
) -> str:
    if attribution is not None:
        return attribution.narrative
    if comparison is not None:
        return _comparison_conclusion(comparison)
    if df is None or df.empty:
        return "未查询到符合条件的数据。"

    metrics = [m for m in intent.metrics if m in df.columns]
    if not metrics:
        return "查询完成。"

    value_dims = [d for d in _value_dims(intent) if d in df.columns]
    time_dims = [d for d in _time_dims(intent) if d in df.columns]

    if intent.share and value_dims:
        return _share_conclusion(intent, df, metrics[0], value_dims[0])
    if time_dims and len(df) > 1:
        return _trend_conclusion(intent, df, metrics, time_dims[0])
    if value_dims and len(df) > 1:
        return _grouped_conclusion(intent, df, metrics, value_dims[0])
    return _scalar_conclusion(intent, df, metrics)


def display_dataframe(intent: Intent, df: pd.DataFrame) -> pd.DataFrame:
    display = pd.DataFrame()
    for dim in [d for d in intent.dimensions if d in df.columns]:
        display[dimension_name(dim)] = df[dim].map(
            lambda value, dim=dim: format_dim_value(dim, value)
        )
    metrics = [m for m in intent.metrics if m in df.columns]
    for metric in metrics:
        display[metric_name(metric)] = df[metric].map(
            lambda value, metric=metric: format_metric_value(metric, value)
        )

    if intent.share and metrics and len(display) > 0:
        metric = metrics[0]
        if METRICS[metric]["kind"] in ("amount", "count"):
            total = df[metric].sum()
            if total > 0:
                display["占比"] = df[metric].map(lambda value: format_percent(value / total))
    return display


def comparison_dataframe(comparison: dict) -> pd.DataFrame:
    table = comparison["table"]
    display = pd.DataFrame()
    for dim in comparison["dims"]:
        display[dimension_name(dim)] = table[dim].map(
            lambda value, dim=dim: format_dim_value(dim, value)
        )
    for metric in comparison["metrics"]:
        name = metric_name(metric)
        current = table[f"{metric}__current"]
        baseline = table[f"{metric}__baseline"]
        delta = table[f"{metric}__delta"]
        rate = table[f"{metric}__rate"]
        display[f"{name}(当期)"] = current.map(
            lambda value, metric=metric: format_metric_value(metric, value)
            if pd.notna(value)
            else "—"
        )
        display[f"{name}(基期)"] = baseline.map(
            lambda value, metric=metric: format_metric_value(metric, value)
            if pd.notna(value)
            else "—"
        )
        display[f"{name}变化"] = delta.map(
            lambda value, metric=metric: format_metric_delta(metric, value)
            if pd.notna(value)
            else "—"
        )
        if METRICS[metric]["kind"] != "percent":
            display[f"{name}变化率"] = rate.map(
                lambda value: f"{value * 100:+.1f}%" if pd.notna(value) else "—"
            )
    return display


def attribution_dataframe(attribution: AttributionResult) -> pd.DataFrame:
    data = attribution.movers
    metric = attribution.analysis_metric
    dim = attribution.dimension
    display = pd.DataFrame()
    display[dimension_name(dim)] = data[dim].map(
        lambda value, dim=dim: format_dim_value(dim, value)
    )
    display["当期"] = data["current"].map(
        lambda value: format_metric_value(metric, value)
    )
    display["基期"] = data["baseline"].map(
        lambda value: format_metric_value(metric, value)
    )
    display["贡献"] = data["contribution"].map(
        lambda value: format_metric_delta(metric, value)
    )
    display["占净变化"] = data["share"].map(
        lambda value: f"{value * 100:+.1f}%" if pd.notna(value) else "—"
    )
    return display


def metric_definitions(metrics: list[str]) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for metric in metrics:
        if metric in seen or metric not in METRICS:
            continue
        seen.add(metric)
        meta = METRICS[metric]
        rows.append(
            {
                "指标": meta["name"],
                "口径": meta["definition"],
                "公式": meta["formula"],
                "单位": meta["unit"],
            }
        )
    return rows
