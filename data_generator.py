"""生成确定性的模拟财务数据并写入 SQLite。

只依赖标准库，固定随机种子，任何机器上重复运行结果一致。

用法：
    python data_generator.py            # 首次生成，已存在则跳过
    python data_generator.py --force    # 强制重建
"""

from __future__ import annotations

import argparse
import os
import random
import sqlite3
import tempfile
from pathlib import Path

from schema import DATA_END, DATA_START, TABLE

BASE_DIR = Path(__file__).resolve().parent


def _writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".smartdata_write_test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _default_db_path() -> Path:
    override = os.environ.get("SMARTDATA_DB")
    if override:
        return Path(override)
    # Streamlit Cloud 的代码目录可能是只读的，此时回退到临时目录。
    if _writable(BASE_DIR):
        return BASE_DIR / "finance.db"
    return Path(tempfile.gettempdir()) / "smartdata_finance.db"


DEFAULT_DB_PATH = _default_db_path()

PRODUCT_LINES = ["智能硬件", "软件订阅", "数据服务", "云服务"]
REGIONS = ["华东", "华南", "华北", "西南"]
CHANNELS = ["直销", "分销", "线上", "合作伙伴"]

SEASONAL = {
    1: 0.90,
    2: 0.85,
    3: 1.00,
    4: 1.02,
    5: 1.05,
    6: 1.12,
    7: 1.00,
    8: 0.98,
    9: 1.03,
    10: 1.06,
    11: 1.18,
    12: 1.10,
}

PRODUCT_MULT = {"智能硬件": 1.00, "软件订阅": 0.75, "数据服务": 0.55, "云服务": 0.45}
REGION_MULT = {"华东": 1.30, "华南": 1.10, "华北": 1.00, "西南": 0.70}
CHANNEL_MULT = {"直销": 0.50, "分销": 0.25, "线上": 0.15, "合作伙伴": 0.10}
COST_RATIO = {"智能硬件": 0.72, "软件订阅": 0.30, "数据服务": 0.35, "云服务": 0.40}
AVG_ORDER_VALUE = {"智能硬件": 0.5, "软件订阅": 3.0, "数据服务": 2.0, "云服务": 1.0}

# 人为埋入的经营事件，让“同比 / 环比 / 为什么下降”有真实可讲的故事。
EVENT_MULT: dict[tuple[str, str, str], float] = {
    # 2026-09 华东区域明显走弱，是“上月毛利下降”的主要归因。
    ("2026-09", "region", "华东"): 0.82,
    # 同期智能硬件承压。
    ("2026-09", "product_line", "智能硬件"): 0.92,
    # 2026-08 线上大促拉高基数，9 月回落。
    ("2026-08", "channel", "线上"): 1.12,
    # 2026-06 软件订阅推广活动。
    ("2026-06", "product_line", "软件订阅"): 1.16,
    # 去年同期华东基数略低，使同比维度也有差异。
    ("2025-09", "region", "华东"): 0.95,
}


def _month_range(start: str, end: str) -> list[str]:
    start_year, start_month = int(start[:4]), int(start[5:7])
    end_year, end_month = int(end[:4]), int(end[5:7])
    months: list[str] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


def _event_factor(month: str, product_line: str, region: str, channel: str) -> float:
    factor = 1.0
    for (event_month, dim, value), mult in EVENT_MULT.items():
        if event_month != month:
            continue
        actual = {"product_line": product_line, "region": region, "channel": channel}[dim]
        if actual == value:
            factor *= mult
    return factor


def generate_rows(seed: int = 42) -> list[tuple]:
    """生成 月 × 产品线 × 区域 × 渠道 粒度的模拟事实数据。"""
    rng = random.Random(seed)
    months = _month_range(DATA_START, DATA_END)
    rows: list[tuple] = []

    for index, month in enumerate(months):
        growth = 1.015**index
        seasonal = SEASONAL[int(month[5:7])]

        for product_line in PRODUCT_LINES:
            for region in REGIONS:
                for channel in CHANNELS:
                    base = (
                        1200
                        * growth
                        * seasonal
                        * PRODUCT_MULT[product_line]
                        * REGION_MULT[region]
                        * CHANNEL_MULT[channel]
                    )
                    revenue = base * rng.uniform(0.92, 1.08)
                    revenue *= _event_factor(month, product_line, region, channel)

                    cost = revenue * COST_RATIO[product_line] * rng.uniform(0.95, 1.05)
                    expense = revenue * 0.25 * rng.uniform(0.90, 1.10)
                    order_count = max(1, int(revenue / AVG_ORDER_VALUE[product_line]))

                    rows.append(
                        (
                            month,
                            product_line,
                            region,
                            channel,
                            round(revenue, 2),
                            round(cost, 2),
                            round(expense, 2),
                            order_count,
                        )
                    )

    return rows


def init_db(db_path: str | Path = DEFAULT_DB_PATH, force: bool = False) -> Path:
    """创建数据库；已存在且未指定 force 时直接复用。"""
    path = Path(db_path)
    if path.exists() and not force:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    rows = generate_rows()
    with sqlite3.connect(path) as conn:
        conn.execute(
            f"""
            CREATE TABLE {TABLE} (
                month        TEXT    NOT NULL,
                product_line TEXT    NOT NULL,
                region       TEXT    NOT NULL,
                channel      TEXT    NOT NULL,
                revenue      REAL    NOT NULL,
                cost         REAL    NOT NULL,
                expense      REAL    NOT NULL,
                order_count  INTEGER NOT NULL,
                PRIMARY KEY (month, product_line, region, channel)
            )
            """
        )
        conn.execute(f"CREATE INDEX idx_{TABLE}_month ON {TABLE}(month)")
        conn.executemany(
            f"""
            INSERT INTO {TABLE}
                (month, product_line, region, channel, revenue, cost, expense, order_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()

    return path


def get_db(db_path: str | Path = DEFAULT_DB_PATH) -> Path:
    """懒加载：首次调用生成数据库。"""
    return init_db(db_path)


def count_rows(db_path: str | Path = DEFAULT_DB_PATH) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0])


def main() -> None:
    parser = argparse.ArgumentParser(description="生成智能问数 demo 的模拟财务数据")
    parser.add_argument("--force", action="store_true", help="强制重建数据库")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="数据库输出路径")
    args = parser.parse_args()

    path = init_db(args.db, force=args.force)
    total = count_rows(path)
    print(f"数据库已就绪：{path}")
    print(f"数据范围：{DATA_START} ~ {DATA_END}，共 {total} 行")
    print(f"维度：产品线 {len(PRODUCT_LINES)} × 区域 {len(REGIONS)} × 渠道 {len(CHANNELS)}")


if __name__ == "__main__":
    main()
