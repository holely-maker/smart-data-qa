"""查询意图的数据模型与多轮合并规则。

Intent 是解析器与 SQL 构建之间的契约：
- parser 产出 ParseResult(intent + touched)
- merge() 把本轮结果合并进上一轮 Intent，实现“那上个月呢”“按区域拆一下”
- sql_builder / engine / attribution 只消费 Intent
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from schema import AS_OF_MONTH, DATA_END, DATA_START


def month_index(month: str) -> int:
    return int(month[:4]) * 12 + int(month[5:7]) - 1


def index_to_month(index: int) -> str:
    year, month = divmod(index, 12)
    return f"{year:04d}-{month + 1:02d}"


@dataclass(frozen=True)
class TimeRange:
    start: str  # YYYY-MM
    end: str  # YYYY-MM
    granularity: str = "month"  # single | month | quarter | year

    def months_count(self) -> int:
        return month_index(self.end) - month_index(self.start) + 1

    def shift_months(self, delta: int) -> "TimeRange":
        return TimeRange(
            index_to_month(month_index(self.start) + delta),
            index_to_month(month_index(self.end) + delta),
            self.granularity,
        )

    def shift_years(self, delta: int) -> "TimeRange":
        return TimeRange(
            f"{int(self.start[:4]) + delta:04d}{self.start[4:]}",
            f"{int(self.end[:4]) + delta:04d}{self.end[4:]}",
            self.granularity,
        )

    def clipped(self) -> "TimeRange | None":
        """裁剪到数据可用区间；完全无交集时返回 None。"""
        start = max(self.start, DATA_START)
        end = min(self.end, DATA_END)
        if start > end:
            return None
        return TimeRange(start, end, self.granularity)

    def label(self) -> str:
        start_year, start_month = int(self.start[:4]), int(self.start[5:7])
        end_year, end_month = int(self.end[:4]), int(self.end[5:7])

        if self.granularity == "quarter" and self.start != self.end:
            quarter = (start_month - 1) // 3 + 1
            if start_year == end_year:
                return f"{start_year}年Q{quarter}"

        if self.start == self.end:
            return f"{start_year}年{start_month}月"
        if start_year == end_year:
            return f"{start_year}年{start_month}-{end_month}月"
        return f"{start_year}年{start_month}月-{end_year}年{end_month}月"


@dataclass
class Intent:
    metrics: list[str] = field(default_factory=list)
    time_range: TimeRange | None = None
    dimensions: list[str] = field(default_factory=list)
    filters: dict[str, list[str]] = field(default_factory=dict)
    aggregation: str = "sum"  # sum | avg
    top_n: int | None = None
    comparison: str | None = None  # yoy | mom
    share: bool = False
    attribution: str | None = None  # down | up | auto
    sort_by: str | None = None  # growth：对比结果按变化率排序

    def clone(self) -> "Intent":
        return deepcopy(self)


@dataclass
class ParseResult:
    intent: Intent = field(default_factory=Intent)
    touched: set[str] = field(default_factory=set)
    dimension_mode: str = "replace"  # replace | append
    fallback: bool = False
    out_of_range: bool = False
    raw_text: str = ""


def merge(prev: Intent | None, parsed: ParseResult) -> Intent:
    """本轮显式命中的字段覆盖，未命中的继承上一轮。"""
    new = parsed.intent
    if prev is None:
        return new.clone()

    merged = prev.clone()
    touched = parsed.touched

    if "metrics" in touched:
        merged.metrics = list(new.metrics)
    if "time_range" in touched:
        merged.time_range = new.time_range
    if "dimensions" in touched:
        if parsed.dimension_mode == "append":
            for dim in new.dimensions:
                if dim not in merged.dimensions:
                    merged.dimensions.append(dim)
        else:
            merged.dimensions = list(new.dimensions)
    if new.filters:
        # 按 key 合并：同 key 覆盖、不同 key 保留。
        for dim, values in new.filters.items():
            merged.filters[dim] = list(values)
    if "aggregation" in touched:
        merged.aggregation = new.aggregation
    if "top_n" in touched:
        merged.top_n = new.top_n

    # 对比 / 占比 / 归因 / 排序不继承，避免“那上个月呢”误带同比。
    merged.comparison = new.comparison
    merged.share = new.share
    merged.attribution = new.attribution
    merged.sort_by = new.sort_by
    return merged


def default_time_for_comparison(comparison: str, as_of: str = AS_OF_MONTH) -> TimeRange:
    """未指定时间时：同比默认今年至今，环比默认当前月。"""
    if comparison == "yoy":
        return TimeRange(f"{int(as_of[:4]):04d}-01", as_of, "month")
    return TimeRange(as_of, as_of, "single")


def baseline_time_range(
    time_range: TimeRange | None,
    comparison: str | None = None,
    *,
    for_attribution: bool = False,
    as_of: str = AS_OF_MONTH,
) -> TimeRange | None:
    """推导对比基期。

    同比：去年同期；环比：上一个等长周期（单月即上月）。
    归因未显式指定对比方式时：单月对比上月；今年至今 / 完整年度对比去年同期。
    """
    if time_range is None:
        if comparison == "yoy":
            current = default_time_for_comparison("yoy", as_of)
            return current.shift_years(-1).clipped()
        current = TimeRange(as_of, as_of, "single")
        return current.shift_months(-1).clipped()

    if comparison == "yoy":
        return time_range.shift_years(-1).clipped()
    if comparison == "mom":
        return time_range.shift_months(-time_range.months_count()).clipped()

    if for_attribution:
        if time_range.granularity == "single":
            return time_range.shift_months(-1).clipped()
        starts_in_january = time_range.start.endswith("-01")
        is_ytd = starts_in_january and time_range.end == as_of
        is_full_year = starts_in_january and time_range.end.endswith("-12")
        if is_ytd or is_full_year:
            return time_range.shift_years(-1).clipped()
        return time_range.shift_months(-time_range.months_count()).clipped()

    return time_range.shift_months(-time_range.months_count()).clipped()
