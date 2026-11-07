# 智能问数 Demo

用自然语言查询收入、成本、毛利、毛利率、费用、净利润、订单量和客单价。
系统会自动生成 SQL、展示图表并给出一句话结论，支持多轮追问、同比 / 环比和维度归因。

> v1 不调用大模型：使用规则 + 模板把中文问题解析成结构化意图。
> 引擎接口已预留（`engine.QueryEngine` / `LLMEngine`），后续可替换为 LLM。

## 快速开始

```bash
pip install -r requirements.txt
python data_generator.py        # 生成模拟数据库 finance.db（首次运行 app 也会自动生成）
streamlit run app.py
```

浏览器打开 Streamlit 提供的地址即可。

## 示例问题

- 今年收入是多少？
- 那上个月呢
- 按区域拆一下
- 近6个月收入趋势
- 上月毛利率是多少，同比怎么样？
- 2025年各产品线收入占比
- 为什么上月毛利下降了？
- 今年各区域成本排名
- 收入同比增长最快的产品线

## 功能

- **问数 + 图表 + 结论**：自然语言 → SQL → 表格、图表和一句话洞察
- **多轮追问**：保留上下文，支持「那上个月呢」「按区域拆一下」「只看华东」
- **同比 / 环比 / 归因**：同期对比、维度下钻，并对波动给出贡献度归因
- **可解释**：展开「SQL / 耗时 / 指标口径」查看生成的 SQL 与指标定义

## 数据说明

- 模拟数据，覆盖 2024-01 至 2026-10，颗粒度为 月 × 产品线 × 区域 × 渠道，共 2,176 行
- 数据以 2026-10 作为“当前月”锚点，所有「本月 / 上月 / 近 N 个月」都相对它解析
- 已埋入若干经营事件（如 2026-09 华东走弱、2026-08 线上大促），便于演示归因
- 金额单位为万元；订单量单位为单；比率为 0-1，展示为百分比

## 项目结构

```
app.py              Streamlit UI
schema.py           维度 / 指标口径 / 白名单
data_generator.py   确定性模拟数据 + SQLite 建库
intent.py           Intent 数据模型 + 多轮合并
parser.py           中文规则解析（指标 / 时间 / 维度 / 对比 / 归因）
sql_builder.py      Intent → SQL（白名单、参数化、除零保护）
attribution.py      维度贡献归因
presenters.py       图表、结论、展示表格
engine.py           QueryEngine / RuleEngine / LLMEngine 预留
formatters.py       中文金额与指标格式化
tests/              pytest 单测
```

## 测试

```bash
pytest -q
```

## 部署到 Streamlit Community Cloud

1. 将仓库推送到 GitHub（`finance.db` 已在 `.gitignore` 中，不会入库）
2. 打开 https://share.streamlit.io ，用 GitHub 账号登录并授权本仓库
3. New app → 选择仓库 → Branch 选 `main` → Main file path 填 `app.py`
4. Python 版本建议选 3.12，点击 Deploy
5. 构建完成后会得到 `https://<app-name>.streamlit.app` 链接，可直接分享

> 公开部署前请确认数据为模拟数据。如需给外部人员使用，建议增加访问密码。

## 后续接入大模型

实现 `LLMEngine.run()`：让模型把问题解析为 `Intent`（指标、时间、维度、过滤、对比方式），
其余 SQL 构建、查询、归因和展示链路无需改动。建议同时保留规则引擎作为兜底。
