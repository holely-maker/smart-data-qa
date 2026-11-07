"""Intent → SQL。

安全约定：
- 表名、列名只能来自白名单常量，绝不拼接用户文本。
- 过滤值一律使用 ? 占位符参数绑定。
- 比率指标先 SUM 再相除，并用 CASE WHEN 防除零。
"""

from __future__ import annotations

from intent import (
    Intent,
    baseline_time_range,
    default_time_for_comparison,
)
from schema import AS_OF_MONTH, DIMENSIONS, METRICS, TABLE

SUM_SQL = {
    "revenue": "SUM(revenue)",
    "cost": "SUM(cost)",
    "expense": "SUM(expense)",
    "gross_profit": "SUM(revenue) - SUM(cost)",
    "net_profit": "SUM(revenue) - SUM(cost) - SUM(expense)",
    "order_count": "SUM(order_count)",
}

RATIO_SQL = {
    "gross_margin": (
        "CASE WHEN SUM(revenue) = 0 THEN NULL "
        "ELSE (SUM(revenue) - SUM(cost)) * 1.0 / SUM(revenue) END"
    ),
    "net_margin": (
        "CASE WHEN SUM(revenue) = 0 THEN NULL "
        "ELSE (SUM(revenue) - SUM(cost) - SUM(expense)) * 1.0 / SUM(revenue) END"
    ),
    "avg_order_value": (
        "CASE WHEN SUM(order_count) = 0 THEN NULL "
        "ELSE SUM(revenue) * 1.0 / SUM(order_count) END"
    ),
}

GROUP_EXPR = {
    "month": "month",
    "quarter": (
        "substr(month, 1, 4) || '-Q' || "
        "((CAST(substr(month, 6, 2) AS INTEGER) - 1) / 3 + 1)"
    ),
    "product_line": "product_line",
    "region": "region",
    "channel": "channel",
}


def _metric_expr(metric: str, aggregation: str = "sum") -> str:
    if metric not in METRICS:
        raise ValueError(f"不支持的指标：{metric}")
    if metric in RATIO_SQL:
        return RATIO_SQL[metric]
    expression = SUM_SQL[metric]
    if aggregation == "avg":
        return f"({expression}) * 1.0 / COUNT(DISTINCT month)"
    return expression


def _group_expr(dim: str) -> str:
    if dim not in GROUP_EXPR:
        raise ValueError(f"不支持的分组维度：{dim}")
    return GROUP_EXPR[dim]


def _where_clause(intent: Intent) -> tuple[list[str], list]:
    clauses: list[str] = []
    params: list = []

    if intent.time_range is not None:
        clauses.append("month BETWEEN ? AND ?")
        params.extend([intent.time_range.start, intent.time_range.end])

    for dim, values in intent.filters.items():
        if dim not in DIMENSIONS or DIMENSIONS[dim]["is_time"]:
            raise ValueError(f"不支持的过滤维度：{dim}")
        if not values:
            continue
        placeholders = ", ".join("?" for _ in values)
        clauses.append(f"{dim} IN ({placeholders})")
        params.extend(values)

    return clauses, params


def build_sql(intent: Intent) -> tuple[str, list]:
    """返回 (sql, params)。"""
    if not intent.metrics:
        raise ValueError("请至少指定一个指标")

    metrics: list[str] = []
    for metric in intent.metrics:
        if metric not in METRICS:
            raise ValueError(f"不支持的指标：{metric}")
        if metric not in metrics:
            metrics.append(metric)

    dimensions: list[str] = []
    for dim in intent.dimensions:
        if dim not in DIMENSIONS:
            raise ValueError(f"不支持的分组维度：{dim}")
        if dim not in dimensions:
            dimensions.append(dim)

    select_parts = [f"{_group_expr(dim)} AS {dim}" for dim in dimensions]
    select_parts.extend(
        f"{_metric_expr(metric, intent.aggregation)} AS {metric}" for metric in metrics
    )

    sql = f"SELECT {', '.join(select_parts)} FROM {TABLE}"
    clauses, params = _where_clause(intent)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)

    if dimensions:
        sql += " GROUP BY " + ", ".join(_group_expr(dim) for dim in dimensions)
        # 季度趋势只保留完整季度，避免首尾不完整季度拉低/抬高对比。
        if (
            "quarter" in dimensions
            and intent.time_range is not None
            and intent.time_range.months_count() >= 3
        ):
            sql += " HAVING COUNT(DISTINCT month) = 3"
        time_dims = [dim for dim in dimensions if dim in ("month", "quarter")]
        if time_dims:
            sql += f" ORDER BY {_group_expr(time_dims[0])} ASC"
        else:
            sql += f" ORDER BY {metrics[0]} DESC"

    limit = intent.top_n if (intent.top_n and dimensions) else 1000
    sql += " LIMIT ?"
    params.append(limit)

    return sql, params


def build_comparison_queries(
    intent: Intent, as_of: str = AS_OF_MONTH
) -> dict | None:
    """构造当期 / 基期两条查询；基期超出数据范围时返回 None。"""
    if not intent.comparison:
        raise ValueError("对比查询缺少 comparison")

    current = intent.clone()
    current.comparison = None
    current.attribution = None
    current.share = False
    current.top_n = None
    if current.time_range is None:
        current.time_range = default_time_for_comparison(intent.comparison, as_of)

    baseline_range = baseline_time_range(
        current.time_range, intent.comparison, as_of=as_of
    )
    if baseline_range is None:
        return None

    baseline = current.clone()
    baseline.time_range = baseline_range

    current_sql, current_params = build_sql(current)
    baseline_sql, baseline_params = build_sql(baseline)
    return {
        "current_intent": current,
        "baseline_intent": baseline,
        "current_sql": current_sql,
        "current_params": current_params,
        "baseline_sql": baseline_sql,
        "baseline_params": baseline_params,
        "current_range": current.time_range,
        "baseline_range": baseline_range,
    }
