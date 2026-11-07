"""智能问数 Demo —— Streamlit 入口。

启动：
    streamlit run app.py
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

from data_generator import get_db
from engine import Answer, create_engine
from parser import SUPPORTED_EXAMPLES
from schema import METRICS

st.set_page_config(
    page_title="智能问数 Demo",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

WELCOME_ANSWER = {
    "role": "assistant",
    "kind": "welcome",
    "content": (
        "你好，我是经营数据助手。可以问我收入、成本、毛利、毛利率、费用、"
        "净利润、订单量和客单价。\n\n"
        "我会自动生成 SQL、展示图表并给出一句话结论。也支持多轮追问，"
        "例如先问「今年收入是多少？」，再问「那上个月呢」「按区域拆一下」。"
    ),
}


def detect_theme() -> str:
    try:
        theme_type = st.context.theme.type
        return theme_type if theme_type in ("light", "dark") else "light"
    except Exception:
        return "light"


THEME = detect_theme()
PAGE_BG = "#f9f9f7" if THEME == "light" else "#0d0d0d"
SIDEBAR_BG = "#f2f1ed" if THEME == "light" else "#141413"
TEXT_COLOR = "#0b0b0b" if THEME == "light" else "#ffffff"

st.markdown(
    f"""
    <style>
      .block-container {{ max-width: 1080px; padding-top: 3.2rem; padding-bottom: 7rem; }}
      [data-testid="stSidebar"] {{ background: {SIDEBAR_BG}; }}
      [data-testid="stSidebar"] .block-container {{ padding-top: 1.2rem; }}
      .app-title {{ font-size: 1.9rem; font-weight: 700; letter-spacing: -0.02em;
                    color: {TEXT_COLOR}; margin-bottom: 0.1rem; }}
      .app-subtitle {{ color: #898781; font-size: 0.92rem; margin-bottom: 1.2rem; }}
      div[data-testid="stChatMessage"] {{ padding: 0.35rem 0; }}
      div[data-testid="stExpander"] {{ border-radius: 10px; }}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner=False)
def load_db() -> str:
    return str(get_db())


@st.cache_data(show_spinner=False)
def load_overview(db_path: str) -> tuple[int, str, str]:
    with sqlite3.connect(db_path) as conn:
        rows = int(conn.execute("SELECT COUNT(*) FROM fact").fetchone()[0])
        start, end = conn.execute("SELECT MIN(month), MAX(month) FROM fact").fetchone()
    return rows, start, end


db_path = load_db()
engine = create_engine(db_path)
row_count, start_month, end_month = load_overview(db_path)

if "messages" not in st.session_state:
    st.session_state.messages = [WELCOME_ANSWER]
if "intent_state" not in st.session_state:
    st.session_state.intent_state = None


def process_question(question: str) -> None:
    question = question.strip()
    if not question:
        return
    st.session_state.messages.append({"role": "user", "content": question})
    with st.spinner("正在理解问题并查询数据…"):
        answer = engine.run(
            question,
            prev_intent=st.session_state.intent_state,
            theme=THEME,
        )
    if answer.intent is not None and not answer.fallback:
        st.session_state.intent_state = answer.intent
    st.session_state.messages.append({"role": "assistant", "answer": answer})


def render_suggestions(answer: Answer) -> None:
    if not answer.suggestions:
        return
    st.caption("可以试着问：")
    columns = st.columns(2)
    for index, suggestion in enumerate(answer.suggestions[:6]):
        if columns[index % 2].button(
            suggestion,
            key=f"suggest_{id(answer)}_{index}",
            width="stretch",
        ):
            process_question(suggestion)
            st.rerun()


def render_answer(answer: Answer) -> None:
    if answer.mode == "error":
        st.error(answer.conclusion)
        if answer.warning:
            st.caption(f"错误详情：{answer.warning}")
        return

    if answer.mode == "notice":
        st.warning(answer.conclusion)
        render_suggestions(answer)
        return

    st.markdown(answer.conclusion)

    if answer.warning and answer.mode != "error":
        st.caption(f"提示：{answer.warning}")

    if answer.figure is not None:
        st.plotly_chart(
            answer.figure,
            width="stretch",
            config={"displayModeBar": False, "responsive": True},
        )

    if answer.table is not None and not answer.table.empty:
        height = min(420, max(78, 38 * len(answer.table) + 38))
        st.dataframe(
            answer.table,
            hide_index=True,
            width="stretch",
            height=height,
        )

    if answer.fallback:
        render_suggestions(answer)

    if answer.sql_list or answer.metric_defs:
        with st.expander("SQL / 耗时 / 指标口径"):
            st.caption(f"查询耗时：{answer.timing_ms:.1f} ms")
            for label, sql, params in answer.sql_list:
                st.markdown(f"**{label}**")
                st.code(sql, language="sql")
                if params:
                    st.caption("参数：" + "，".join(str(param) for param in params))
            if answer.metric_defs:
                st.markdown("**指标口径**")
                st.dataframe(
                    pd.DataFrame(answer.metric_defs),
                    hide_index=True,
                    width="stretch",
                )


st.markdown('<div class="app-title">📊 智能问数</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="app-subtitle">用自然语言查询收入、成本、毛利与经营指标 · '
    "模拟数据 · 数据截至 2026-10</div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### 数据概览")
    st.markdown(
        f"- 模拟财务数据：**{row_count:,}** 行\n"
        f"- 时间范围：**{start_month} ~ {end_month}**\n"
        f"- 分析维度：产品线 / 区域 / 渠道\n"
        f"- 数据颗粒度：月 × 产品线 × 区域 × 渠道"
    )

    st.divider()
    st.markdown("### 试着问")
    for example_index, example in enumerate(SUPPORTED_EXAMPLES):
        if st.button(
            example,
            key=f"example_{example_index}",
            width="stretch",
        ):
            process_question(example)
            st.rerun()

    st.divider()
    with st.expander("指标口径"):
        for meta in METRICS.values():
            st.markdown(
                f"**{meta['name']}** · {meta['unit']}  \n{meta['definition']}"
            )

    st.divider()
    if st.button("重置对话", width="stretch"):
        st.session_state.messages = [WELCOME_ANSWER]
        st.session_state.intent_state = None
        st.rerun()

    st.caption(
        "这是规则解析版 demo：不调用大模型，SQL 由结构化意图生成。"
        "引擎接口已预留，可替换为 LLM。"
    )

for message in st.session_state.messages:
    if message["role"] == "user":
        with st.chat_message("user", avatar="🧑"):
            st.markdown(message["content"])
    else:
        with st.chat_message("assistant", avatar="📊"):
            if message.get("kind") == "welcome":
                st.markdown(message["content"])
            else:
                render_answer(message["answer"])

question = st.chat_input("请输入你的问题，例如：今年收入是多少？")
if question:
    process_question(question)
    st.rerun()
