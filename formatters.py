"""中文数字与期间格式化。"""

from __future__ import annotations

from schema import DIMENSIONS, METRICS


def format_money(value: float) -> str:
    if value is None:
        return "—"
    if abs(value) >= 10000:
        return f"{value / 10000:,.2f} 亿元"
    return f"{value:,.1f} 万元"


def format_money_delta(value: float) -> str:
    return f"{format_money(value)}" if value >= 0 else f"-{format_money(abs(value))}"


def format_percent(value: float, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value * 100:,.{digits}f}%"


def format_count(value: float) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f} 单"


def format_metric_value(metric: str, value: float) -> str:
    if value is None:
        return "—"
    kind = METRICS[metric]["kind"]
    if kind == "amount":
        return format_money(value)
    if kind == "percent":
        return format_percent(value)
    if kind == "count":
        return format_count(value)
    if kind == "per_order":
        return f"{value:,.2f} 万元/单"
    return f"{value:,.2f}"


def format_metric_delta(metric: str, delta: float) -> str:
    """带正负号的指标变化量。"""
    if delta is None:
        return "—"
    sign = "+" if delta >= 0 else "-"
    absolute = abs(delta)
    kind = METRICS[metric]["kind"]
    if kind == "amount":
        return f"{sign}{format_money(absolute)}"
    if kind == "percent":
        return f"{sign}{absolute * 100:,.1f} 个百分点"
    if kind == "count":
        return f"{sign}{absolute:,.0f} 单"
    if kind == "per_order":
        return f"{sign}{absolute:,.2f} 万元/单"
    return f"{sign}{absolute:,.2f}"


def format_metric_abs_delta(metric: str, value: float) -> str:
    """只要变化幅度、不要符号（用于“下降 123 万元”）。"""
    return format_metric_delta(metric, abs(value)).lstrip("+")


def format_dim_value(dim: str, value) -> str:
    if dim == "month" and isinstance(value, str) and len(value) == 7:
        return f"{value[:4]}年{int(value[5:7])}月"
    if dim == "quarter" and isinstance(value, str) and "-Q" in value:
        return value.replace("-Q", "年Q")
    return str(value)


def dimension_name(dim: str) -> str:
    return DIMENSIONS.get(dim, {}).get("name", dim)


def metric_name(metric: str) -> str:
    return METRICS[metric]["name"]


def metric_unit(metric: str) -> str:
    return METRICS[metric]["unit"]
