"""中文规则解析器：自然语言问题 → Intent。

v1 不依赖大模型，用关键词词典 + 正则把中文问题映射成结构化意图。
后续接 LLM 时，只需要产出同样的 Intent，其他模块无需改动。
"""

from __future__ import annotations

import re
import unicodedata

from intent import (
    Intent,
    ParseResult,
    TimeRange,
    index_to_month,
    month_index,
)
from schema import AS_OF_MONTH, DATA_END, DATA_START, DIMENSIONS

CN_NUM = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

# 长词优先，避免“毛利率”被“毛利”截断、“营业成本”被“成本”截断。
METRIC_KEYWORDS: list[tuple[str, str]] = sorted(
    [
        ("毛利率", "gross_margin"),
        ("净利率", "net_margin"),
        ("客单价", "avg_order_value"),
        ("净利润", "net_profit"),
        ("利润总额", "net_profit"),
        ("营业成本", "cost"),
        ("期间费用", "expense"),
        ("总费用", "expense"),
        ("订单量", "order_count"),
        ("订单数", "order_count"),
        ("销售额", "revenue"),
        ("营业额", "revenue"),
        ("毛利", "gross_profit"),
        ("收入", "revenue"),
        ("营收", "revenue"),
        ("成本", "cost"),
        ("费用", "expense"),
        ("利润", "net_profit"),
        ("单量", "order_count"),
    ],
    key=lambda item: len(item[0]),
    reverse=True,
)

DIM_KEYWORDS: list[tuple[str, str]] = sorted(
    [
        ("产品线", "product_line"),
        ("业务线", "product_line"),
        ("品类", "product_line"),
        ("产品", "product_line"),
        ("区域", "region"),
        ("地区", "region"),
        ("大区", "region"),
        ("渠道", "channel"),
    ],
    key=lambda item: len(item[0]),
    reverse=True,
)

TREND_WORDS = ("趋势", "走势", "变化情况", "变化趋势")

SUPPORTED_EXAMPLES = [
    "今年收入是多少？",
    "那上个月呢",
    "按区域拆一下",
    "近6个月收入趋势",
    "上月毛利率是多少，同比怎么样？",
    "2025年各产品线收入占比",
    "为什么上月毛利下降了？",
    "今年各区域成本排名",
]


def _cn_to_int(token: str) -> int | None:
    token = token.strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    if token == "十":
        return 10
    if "十" in token:
        left, right = token.split("十", 1)
        tens = CN_NUM.get(left, 1) if left else 1
        ones = CN_NUM.get(right, 0) if right else 0
        return tens * 10 + ones
    if token in CN_NUM:
        return CN_NUM[token]
    return None


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


def _year_context(text: str, default_year: int) -> int:
    match = re.search(r"(20\d{2})\s*年", text)
    if match:
        return int(match.group(1))
    if "前年" in text:
        return default_year - 2
    if "去年" in text or "上年" in text:
        return default_year - 1
    if "今年" in text or "本年" in text:
        return default_year
    return default_year


def _quarter_range(year: int, quarter: int) -> TimeRange:
    start_month = (quarter - 1) * 3 + 1
    start = f"{year:04d}-{start_month:02d}"
    end = f"{year:04d}-{start_month + 2:02d}"
    return TimeRange(start, end, "quarter")


def resolve_time(text: str, as_of: str = AS_OF_MONTH) -> TimeRange | None:
    """解析中文时间表达，全部相对 as_of 锚点。"""
    as_of_year = int(as_of[:4])
    as_of_month = int(as_of[5:7])

    # “较上月 / 比去年同期”是对比短语，不当作查询时间。
    time_text = re.sub(
        r"(?:较|比|相比|对比)\s*(?:上月|上个月|去年同期|上年同期|上期)",
        "",
        text,
    )

    def clipped(time_range: TimeRange) -> TimeRange | None:
        return time_range.clipped()

    # 近 N 个月
    match = re.search(
        r"(?:近|最近|过去)\s*([0-9一二两三四五六七八九十]+)\s*个?\s*月",
        time_text,
    )
    if match:
        count = _cn_to_int(match.group(1))
        if count and 1 <= count <= 36:
            start = index_to_month(month_index(as_of) - (count - 1))
            return clipped(TimeRange(start, as_of, "month"))

    # 近 N 年
    match = re.search(
        r"(?:近|最近|过去)\s*([0-9一二两三四五六七八九十]+)\s*年",
        time_text,
    )
    if match:
        years = _cn_to_int(match.group(1))
        if years and 1 <= years <= 5:
            start = index_to_month(month_index(as_of) - (years * 12 - 1))
            return clipped(TimeRange(start, as_of, "month"))

    # 上季度
    if re.search(r"上(?:一)?季度", time_text):
        current_quarter_start_month = (as_of_month - 1) // 3 * 3 + 1
        current_start_index = month_index(f"{as_of_year:04d}-{current_quarter_start_month:02d}")
        previous_start = index_to_month(current_start_index - 3)
        previous_end = index_to_month(current_start_index - 1)
        return clipped(TimeRange(previous_start, previous_end, "quarter"))

    # 本季度
    if re.search(r"本季度|这季度|当前季度|当季", time_text):
        start_month = (as_of_month - 1) // 3 * 3 + 1
        start = f"{as_of_year:04d}-{start_month:02d}"
        return clipped(TimeRange(start, as_of, "quarter"))

    # 第 X 季度 / QX（“前三季度”不在此列）
    match = re.search(r"(?<!前)(?:第\s*)?([1-4一二三四])\s*季度", time_text)
    if not match:
        match = re.search(r"[Qq]\s*([1-4])", time_text)
    if match:
        quarter = _cn_to_int(match.group(1))
        if quarter:
            year = _year_context(time_text, as_of_year)
            return clipped(_quarter_range(year, quarter))

    # 上半年 / 下半年
    if "上半年" in time_text:
        year = _year_context(time_text, as_of_year)
        return clipped(TimeRange(f"{year:04d}-01", f"{year:04d}-06", "month"))
    if "下半年" in time_text:
        year = _year_context(time_text, as_of_year)
        return clipped(TimeRange(f"{year:04d}-07", f"{year:04d}-12", "month"))

    # 本月 / 上月
    if re.search(r"本月|这个月|当月", time_text):
        return TimeRange(as_of, as_of, "single")
    if re.search(r"上个?月", time_text):
        previous = index_to_month(month_index(as_of) - 1)
        return TimeRange(previous, previous, "single")

    # 今年至今
    if re.search(r"今年|本年|年初至今|年至今", time_text):
        return clipped(TimeRange(f"{as_of_year:04d}-01", as_of, "month"))

    # 去年 / 前年
    if "去年" in time_text or "上年" in time_text:
        year = as_of_year - 1
        return clipped(TimeRange(f"{year:04d}-01", f"{year:04d}-12", "year"))
    if "前年" in time_text:
        year = as_of_year - 2
        return clipped(TimeRange(f"{year:04d}-01", f"{year:04d}-12", "year"))

    # 2025年9月
    match = re.search(
        r"(20\d{2})\s*年\s*([0-9一二两三四五六七八九十]{1,3})\s*月份?",
        time_text,
    )
    if match:
        year = int(match.group(1))
        month = _cn_to_int(match.group(2))
        if month and 1 <= month <= 12:
            return clipped(TimeRange(f"{year:04d}-{month:02d}", f"{year:04d}-{month:02d}", "single"))

    # 2025年
    match = re.search(r"(20\d{2})\s*年", time_text)
    if match:
        year = int(match.group(1))
        return clipped(TimeRange(f"{year:04d}-01", f"{year:04d}-12", "year"))

    # 全年 / 整年
    if re.search(r"全年|整年", time_text):
        year = _year_context(time_text, as_of_year)
        return clipped(TimeRange(f"{year:04d}-01", f"{year:04d}-12", "year"))

    # 9月 / 九月（年份默认锚点年）
    match = re.search(
        r"(?<![近\-\d])([0-9一二两三四五六七八九十]{1,3})\s*月份?",
        time_text,
    )
    if match:
        month = _cn_to_int(match.group(1))
        if month and 1 <= month <= 12:
            year = _year_context(time_text, as_of_year)
            return clipped(TimeRange(f"{year:04d}-{month:02d}", f"{year:04d}-{month:02d}", "single"))

    return None


def extract_metrics(text: str) -> list[str]:
    masked = text
    found: list[str] = []
    for keyword, metric in METRIC_KEYWORDS:
        if keyword in masked:
            if metric not in found:
                found.append(metric)
            masked = masked.replace(keyword, "□" * len(keyword))
    return found


def extract_filters(text: str) -> dict[str, list[str]]:
    filters: dict[str, list[str]] = {}
    for dim, meta in DIMENSIONS.items():
        if meta["is_time"]:
            continue
        values = [value for value in meta["values"] if value in text]
        if values:
            filters[dim] = values
    return filters


def extract_dimensions(
    text: str,
    filters: dict[str, list[str]],
    time_range: TimeRange | None,
) -> tuple[list[str], bool, bool]:
    """返回 (维度列表, 是否追加模式, 是否含趋势词)。"""
    dimensions: list[str] = []
    masked = text

    for keyword, dim in DIM_KEYWORDS:
        if keyword not in masked:
            continue
        masked = masked.replace(keyword, "□" * len(keyword))
        # 已经命中具体取值时，该维度是过滤条件，不是分组维度。
        if dim in filters:
            continue
        if dim not in dimensions:
            dimensions.append(dim)

    trend = any(word in text for word in TREND_WORDS)
    # 时间分桶：显式“按月/季度”或趋势类问法。
    wants_quarter = bool(
        re.search(r"按季度|分季度|每季|各季度|季度趋势", text)
        or ("季度" in text and trend)
        or (trend and time_range is not None and time_range.granularity == "quarter")
    )
    wants_month = bool(
        re.search(r"按月|分月|每月|各月|月度|逐月|月份趋势", text)
        or (trend and not wants_quarter)
        or (time_range is not None and time_range.granularity == "quarter" and not dimensions)
    )

    if wants_quarter and "quarter" not in dimensions:
        dimensions.append("quarter")
    elif wants_month and "month" not in dimensions and "quarter" not in dimensions:
        # 单月问题加“趋势”只会得到一个点，交给引擎补默认窗口。
        if time_range is None or time_range.months_count() > 1:
            dimensions.append("month")

    append_mode = bool(re.search(r"再按|再拆|再分|也按|同时按|再加入", text))
    return dimensions, append_mode, trend


def detect_out_of_range_time(text: str, as_of: str = AS_OF_MONTH) -> bool:
    """识别明确超出数据范围的年份 / 月份，避免静默沿用上一轮时间。"""
    years = [int(year) for year in re.findall(r"(20\d{2})\s*年", text)]
    start_year = int(DATA_START[:4])
    end_year = int(DATA_END[:4])
    if any(year < start_year or year > end_year for year in years):
        return True

    for year_text, month_text in re.findall(
        r"(20\d{2})\s*年\s*([0-9]{1,2})\s*月", text
    ):
        month = int(month_text)
        if not 1 <= month <= 12:
            return True
        month_key = f"{int(year_text):04d}-{month:02d}"
        if month_key < DATA_START or month_key > DATA_END:
            return True

    return False


def extract_top_n(text: str) -> int | None:
    match = re.search(r"(?:前|top)\s*([0-9一二两三四五六七八九十]+)", text, re.IGNORECASE)
    if not match:
        return None
    rest = text[match.end() : match.end() + 4]
    # “前三个月”“前三季度”是时间表达，不是 TopN。
    if re.match(r"\s*(?:个)?\s*(?:月|季度)", rest):
        return None
    value = _cn_to_int(match.group(1))
    if value and 1 <= value <= 50:
        return value
    return None


def extract_comparison(text: str) -> str | None:
    if any(word in text for word in ("同比", "去年同期", "较去年", "比去年")):
        return "yoy"
    if any(word in text for word in ("环比", "较上月", "比上月", "较上期", "比上期")):
        return "mom"
    return None


def extract_attribution(text: str) -> str | None:
    if not re.search(r"为什么|为何|原因|怎么会", text):
        return None
    if re.search(r"下降|下滑|减少|降低|回落|跌", text):
        return "down"
    if re.search(r"上涨|上升|增长|提高|提升|涨", text):
        return "up"
    return "auto"


def parse(text: str, as_of: str = AS_OF_MONTH) -> ParseResult:
    """把一条中文问题解析成 ParseResult。无法识别时 fallback=True。"""
    raw = _normalize(text)
    if not raw:
        return ParseResult(fallback=True, raw_text=raw)

    metrics = extract_metrics(raw)
    time_range = resolve_time(raw, as_of)
    filters = extract_filters(raw)
    dimensions, append_mode, trend = extract_dimensions(raw, filters, time_range)

    # 有趋势词但没有时间范围时，默认给最近 6 个月，避免只画出一个点。
    if trend and time_range is None:
        start = index_to_month(month_index(as_of) - 5)
        time_range = TimeRange(start, as_of, "month")

    comparison = extract_comparison(raw)
    share = any(word in raw for word in ("占比", "份额", "构成", "结构", "比重"))
    top_n = extract_top_n(raw)
    attribution = extract_attribution(raw)
    sort_by = "growth" if re.search(r"最快|增速|增幅最大|跌幅最大", raw) else None

    touched: set[str] = set()
    if metrics:
        touched.add("metrics")
    if time_range is not None:
        touched.add("time_range")
    if dimensions:
        touched.add("dimensions")
    if top_n is not None:
        touched.add("top_n")

    aggregation = "sum"
    if re.search(r"平均|均值", raw):
        aggregation = "avg"
        touched.add("aggregation")

    intent = Intent(
        metrics=metrics,
        time_range=time_range,
        dimensions=dimensions,
        filters=filters,
        aggregation=aggregation,
        top_n=top_n,
        comparison=comparison,
        share=share,
        attribution=attribution,
        sort_by=sort_by,
    )

    has_signal = any(
        [
            metrics,
            time_range,
            dimensions,
            filters,
            comparison,
            share,
            top_n is not None,
            attribution,
        ]
    )
    return ParseResult(
        intent=intent,
        touched=touched,
        dimension_mode="append" if append_mode else "replace",
        fallback=not has_signal,
        out_of_range=detect_out_of_range_time(raw, as_of),
        raw_text=raw,
    )
