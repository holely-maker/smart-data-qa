"""数据表、维度与指标口径的单一事实来源。

解析器、SQL 构建、图表和 UI 都从这里读取元数据，避免口径分散。
"""

from __future__ import annotations

# 演示数据的时间锚点：最后一个完整自然月。
# 所有“本月 / 上月 / 近 N 个月”都相对这个月份解析，而不是系统时间。
AS_OF_MONTH = "2026-10"
DATA_START = "2024-01"
DATA_END = AS_OF_MONTH

TABLE = "fact"

# 可用于过滤 / 分组的维度。month、quarter 是时间维度，不作为过滤值。
DIMENSIONS: dict[str, dict] = {
    "product_line": {
        "name": "产品线",
        "values": ["智能硬件", "软件订阅", "数据服务", "云服务"],
        "is_time": False,
    },
    "region": {
        "name": "区域",
        "values": ["华东", "华南", "华北", "西南"],
        "is_time": False,
    },
    "channel": {
        "name": "渠道",
        "values": ["直销", "分销", "线上", "合作伙伴"],
        "is_time": False,
    },
    "month": {"name": "月份", "values": [], "is_time": True},
    "quarter": {"name": "季度", "values": [], "is_time": True},
}

# kind 决定数字如何格式化：
#   amount   金额（万元）
#   percent  比率（0-1，展示为 %）
#   count    数量（单）
#   per_order 客单价（万元/单）
#
# additive 表示指标是否可加（可做严格的贡献度归因）。
METRICS: dict[str, dict] = {
    "revenue": {
        "name": "收入",
        "formula": "SUM(revenue)",
        "definition": "期间内所有订单收入合计",
        "unit": "万元",
        "kind": "amount",
        "additive": True,
    },
    "cost": {
        "name": "成本",
        "formula": "SUM(cost)",
        "definition": "期间内营业成本合计",
        "unit": "万元",
        "kind": "amount",
        "additive": True,
    },
    "gross_profit": {
        "name": "毛利",
        "formula": "SUM(revenue) - SUM(cost)",
        "definition": "收入减去营业成本",
        "unit": "万元",
        "kind": "amount",
        "additive": True,
    },
    "gross_margin": {
        "name": "毛利率",
        "formula": "(SUM(revenue) - SUM(cost)) / SUM(revenue)",
        "definition": "毛利占收入的比例，先汇总再相除",
        "unit": "%",
        "kind": "percent",
        "additive": False,
    },
    "expense": {
        "name": "费用",
        "formula": "SUM(expense)",
        "definition": "销售、管理及研发等期间费用合计",
        "unit": "万元",
        "kind": "amount",
        "additive": True,
    },
    "net_profit": {
        "name": "净利润",
        "formula": "SUM(revenue) - SUM(cost) - SUM(expense)",
        "definition": "收入减去成本与期间费用",
        "unit": "万元",
        "kind": "amount",
        "additive": True,
    },
    "net_margin": {
        "name": "净利率",
        "formula": "(SUM(revenue) - SUM(cost) - SUM(expense)) / SUM(revenue)",
        "definition": "净利润占收入的比例，先汇总再相除",
        "unit": "%",
        "kind": "percent",
        "additive": False,
    },
    "order_count": {
        "name": "订单量",
        "formula": "SUM(order_count)",
        "definition": "期间内订单数量合计",
        "unit": "单",
        "kind": "count",
        "additive": True,
    },
    "avg_order_value": {
        "name": "客单价",
        "formula": "SUM(revenue) / SUM(order_count)",
        "definition": "收入合计除以订单量合计",
        "unit": "万元/单",
        "kind": "per_order",
        "additive": False,
    },
}

ALLOWED_TABLE_COLUMNS = {
    "month",
    "product_line",
    "region",
    "channel",
    "revenue",
    "cost",
    "expense",
    "order_count",
}

# 指标口径表（UI 侧边栏展示用）。
METRIC_DEFINITION_ROWS = [
    {
        "指标": meta["name"],
        "口径": meta["definition"],
        "单位": meta["unit"],
    }
    for meta in METRICS.values()
]


def metric_label(metric: str) -> str:
    return METRICS[metric]["name"]


def dimension_label(dim: str) -> str:
    return DIMENSIONS[dim]["name"]
