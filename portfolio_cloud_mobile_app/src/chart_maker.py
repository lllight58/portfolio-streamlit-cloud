from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src.portfolio_calculator import ASSET_CLASSES, account_asset_class_summary, account_value_summary, asset_class_summary
from src.portfolio_calculator import (
    MAJOR_ASSET_CLASSES,
    account_major_asset_class_summary,
    calculate_allocation_by_major_asset_class,
)
from src.style_config import ASSET_CLASS_COLORS, MAJOR_ASSET_CLASS_COLORS, ORIGIN_DISTINCT_COLORS


def force_pie_colors(fig: go.Figure, color_map: dict[str, str]) -> go.Figure:
    for trace in fig.data:
        raw_labels = getattr(trace, "labels", None)
        labels = list(raw_labels) if raw_labels is not None else []
        if labels:
            trace.marker.colors = [color_map.get(str(label), "rgb(200, 200, 200)") for label in labels]
    return fig


def force_bar_colors(fig: go.Figure, color_map: dict[str, str]) -> go.Figure:
    for trace in fig.data:
        trace_name = str(getattr(trace, "name", "") or "")
        if trace_name in color_map:
            trace.marker.color = color_map[trace_name]
    return fig


def apply_origin_style(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title={"text": f"<b>{title}</b>", "x": 0.02, "xanchor": "left"},
        paper_bgcolor="white",
        plot_bgcolor="white",
        font={"family": "Arial, Malgun Gothic, sans-serif", "size": 14, "color": "#111111"},
        legend={"bgcolor": "rgba(255,255,255,0.9)", "bordercolor": "#333333", "borderwidth": 1},
        margin={"l": 60, "r": 30, "t": 70, "b": 60},
    )
    fig.update_xaxes(showline=True, linewidth=2, linecolor="#111111", gridcolor="#D9D9D9", ticks="outside")
    fig.update_yaxes(showline=True, linewidth=2, linecolor="#111111", gridcolor="#D9D9D9", ticks="outside")
    return fig


def apply_donut_style(fig: go.Figure, title: str) -> go.Figure:
    fig.update_traces(
        textposition="inside",
        textinfo="percent",
        insidetextorientation="radial",
        textfont_size=13,
        marker={"line": {"color": "white", "width": 2}},
        hovertemplate="<b>%{label}</b><br>평가금액: %{value:,.0f}원<br>비중: %{percent}<extra></extra>",
    )
    fig = apply_origin_style(fig, title)
    fig.update_layout(
        height=360,
        margin={"l": 20, "r": 110, "t": 45, "b": 20},
        legend={
            "orientation": "v",
            "yanchor": "middle",
            "y": 0.5,
            "xanchor": "left",
            "x": 1.02,
            "font": {"size": 11},
            "bgcolor": "rgba(255,255,255,0.9)",
            "bordercolor": "#D0D0D0",
            "borderwidth": 1,
        },
        uniformtext={"minsize": 11, "mode": "hide"},
    )
    return fig


def make_asset_donut(calculated: pd.DataFrame) -> go.Figure:
    summary = asset_class_summary(calculated).rename(columns={"자산군": "세부자산군"})
    fig = px.pie(
        summary,
        values="원화 환산 평가금액",
        names="세부자산군",
        hole=0.45,
        color="세부자산군",
        color_discrete_map=ASSET_CLASS_COLORS,
        category_orders={"세부자산군": ASSET_CLASSES},
    )
    return force_pie_colors(apply_donut_style(fig, "전체 포트폴리오 세부자산군 비중"), ASSET_CLASS_COLORS)


def make_major_asset_donut(calculated: pd.DataFrame) -> go.Figure:
    summary = calculate_allocation_by_major_asset_class(calculated)
    fig = px.pie(
        summary,
        values="원화 환산 평가금액",
        names="상위자산군",
        hole=0.45,
        color="상위자산군",
        color_discrete_map=MAJOR_ASSET_CLASS_COLORS,
        category_orders={"상위자산군": MAJOR_ASSET_CLASSES},
    )
    return force_pie_colors(apply_donut_style(fig, "전체 포트폴리오 상위자산군 비중"), MAJOR_ASSET_CLASS_COLORS)


def make_sub_asset_holding_weight_bar(calculated: pd.DataFrame, sub_asset_class: str) -> go.Figure:
    group_column = "세부자산군" if "세부자산군" in calculated.columns else "자산군"
    assets = calculated[calculated[group_column] == sub_asset_class].copy()
    weight_column = "세부자산군 내 비중" if "세부자산군 내 비중" in assets.columns else "자산군 내 비중"
    if assets.empty:
        assets = pd.DataFrame(
            {
                group_column: [sub_asset_class],
                "티커 또는 종목코드": [f"{sub_asset_class} 없음"],
                "종목명": [f"{sub_asset_class} 없음"],
                weight_column: [0],
                "원화 환산 평가금액": [0],
                "수익률": [0],
            }
        )
    if "표시순서" in assets.columns:
        assets = assets.sort_values("표시순서", kind="stable")
    else:
        assets = assets.sort_values(weight_column, ascending=False)
    if "티커 또는 종목코드" not in assets.columns:
        assets["티커 또는 종목코드"] = assets["종목명"]
    fig = px.bar(
        assets,
        x="종목명",
        y=weight_column,
        color="티커 또는 종목코드",
        color_discrete_sequence=ORIGIN_DISTINCT_COLORS,
        text=assets[weight_column].map(lambda v: f"{v:.2%}"),
        custom_data=["티커 또는 종목코드", "원화 환산 평가금액", weight_column],
    )
    fig.update_traces(
        marker_line_color="#111111",
        marker_line_width=1.2,
        hovertemplate="<b>%{customdata[0]}</b><br>%{x}<br>평가금액: %{customdata[1]:,.0f}원<br>"
        + f"{sub_asset_class} 내부 비중: "
        + "%{customdata[2]:.2%}<extra></extra>",
    )
    fig.update_yaxes(tickformat=".0%")
    fig = apply_origin_style(fig, f"{sub_asset_class} 내부 종목 비중")
    fig.update_layout(legend_title_text="티커/종목코드")
    return fig


def make_holding_value_bar(calculated: pd.DataFrame) -> go.Figure:
    data = calculated.sort_values("표시순서", kind="stable") if "표시순서" in calculated.columns else calculated.sort_values("원화 환산 평가금액", ascending=False)
    fig = px.bar(
        data,
        x="종목명",
        y="원화 환산 평가금액",
        color="자산군",
        color_discrete_map=ASSET_CLASS_COLORS,
        text=data["원화 환산 평가금액"].map(lambda v: f"{v:,.0f}원"),
        custom_data=["전체 포트폴리오 내 비중", "수익률"],
    )
    fig = force_bar_colors(fig, ASSET_CLASS_COLORS)
    fig.update_traces(
        marker_line_color="#111111",
        marker_line_width=1.2,
        hovertemplate="<b>%{x}</b><br>평가금액: %{y:,.0f}원<br>전체 비중: %{customdata[0]:.2%}<br>수익률: %{customdata[1]:+.2%}<extra></extra>",
    )
    fig.update_yaxes(tickformat=",")
    return apply_origin_style(fig, "전체 보유자산 평가금액")


def make_asset_value_bar(calculated: pd.DataFrame) -> go.Figure:
    summary = asset_class_summary(calculated).rename(columns={"자산군": "세부자산군"})
    fig = px.bar(
        summary,
        x="세부자산군",
        y="원화 환산 평가금액",
        color="세부자산군",
        color_discrete_map=ASSET_CLASS_COLORS,
        text=summary["원화 환산 평가금액"].map(lambda v: f"{v:,.0f}원"),
        custom_data=["비중"],
    )
    fig = force_bar_colors(fig, ASSET_CLASS_COLORS)
    fig.update_traces(
        marker_line_color="#111111",
        marker_line_width=1.2,
        hovertemplate="<b>%{x}</b><br>평가금액: %{y:,.0f}원<br>비중: %{customdata[0]:.2%}<extra></extra>",
    )
    fig.update_yaxes(tickformat=",")
    return apply_origin_style(fig, "세부자산군별 평가금액")


def make_account_asset_stack_bar(calculated: pd.DataFrame) -> go.Figure:
    summary = account_asset_stack_summary(calculated)
    fig = px.bar(
        summary,
        x="계좌",
        y="평가금액",
        color="세부자산군",
        color_discrete_map=ASSET_CLASS_COLORS,
        category_orders={"세부자산군": ASSET_CLASSES, "계좌": ["새빛 계좌", "희주 계좌"]},
        barmode="stack",
        custom_data=["세부자산군", "계좌 내 비중"],
    )
    fig = force_bar_colors(fig, ASSET_CLASS_COLORS)
    fig.update_traces(
        marker_line_color="#111111",
        marker_line_width=1.2,
        text=None,
        hovertemplate="<b>%{x}</b><br>세부자산군: %{customdata[0]}<br>평가금액: %{y:,.0f}원<br>계좌 내 비중: %{customdata[1]:.2%}<extra></extra>",
    )
    fig.update_yaxes(tickformat=",")
    fig = apply_origin_style(fig, "계좌별 자산군 구성 비교")
    fig.update_layout(
        height=420,
        margin={"l": 40, "r": 30, "t": 50, "b": 40},
        xaxis_title=None,
        yaxis_title="평가금액",
        legend_title_text="자산군",
    )
    return fig


def account_asset_stack_summary(calculated: pd.DataFrame) -> pd.DataFrame:
    if calculated.empty:
        return pd.DataFrame(columns=["계좌", "세부자산군", "평가금액", "계좌 내 비중"])
    rows = []
    group_column = "세부자산군" if "세부자산군" in calculated.columns else "자산군"
    for account, value_column in [("새빛 계좌", "새빛_평가금액"), ("희주 계좌", "희주_평가금액")]:
        if value_column not in calculated.columns:
            continue
        grouped = calculated.groupby(group_column, as_index=False)[value_column].sum().rename(columns={group_column: "세부자산군", value_column: "평가금액"})
        total = grouped["평가금액"].sum()
        grouped["계좌"] = account
        grouped["계좌 내 비중"] = grouped["평가금액"] / total if total else 0.0
        rows.append(grouped)
    if not rows:
        return pd.DataFrame(columns=["계좌", "세부자산군", "평가금액", "계좌 내 비중"])
    result = pd.concat(rows, ignore_index=True)
    result["세부자산군"] = pd.Categorical(result["세부자산군"], categories=ASSET_CLASSES, ordered=True)
    return result.sort_values(["계좌", "세부자산군"]).reset_index(drop=True)


def make_account_asset_donut(calculated: pd.DataFrame, account: str) -> go.Figure:
    summary = account_asset_class_summary(calculated, account).rename(columns={"자산군": "세부자산군"})
    if summary.empty:
        summary = pd.DataFrame({"세부자산군": ["데이터 없음"], "평가금액": [0.0], "비중": [0.0]})
    fig = px.pie(
        summary,
        values="평가금액",
        names="세부자산군",
        hole=0.45,
        color="세부자산군",
        color_discrete_map=ASSET_CLASS_COLORS,
        category_orders={"세부자산군": ASSET_CLASSES},
    )
    return force_pie_colors(apply_donut_style(fig, f"{account} 계좌 세부자산군 비중"), ASSET_CLASS_COLORS)


def make_account_major_asset_donut(calculated: pd.DataFrame, account: str) -> go.Figure:
    summary = account_major_asset_class_summary(calculated, account)
    if summary.empty:
        summary = pd.DataFrame({"상위자산군": ["데이터 없음"], "평가금액": [0.0], "비중": [0.0]})
    fig = px.pie(
        summary,
        values="평가금액",
        names="상위자산군",
        hole=0.45,
        color="상위자산군",
        color_discrete_map=MAJOR_ASSET_CLASS_COLORS,
        category_orders={"상위자산군": MAJOR_ASSET_CLASSES},
    )
    return force_pie_colors(apply_donut_style(fig, f"{account} 계좌 상위자산군 비중"), MAJOR_ASSET_CLASS_COLORS)


def make_all_charts(calculated: pd.DataFrame) -> dict[str, go.Figure]:
    return {
        "asset_donut": make_asset_donut(calculated),
        "major_asset_donut": make_major_asset_donut(calculated),
        "etf_weight_bar": make_sub_asset_holding_weight_bar(calculated, "ETF"),
        "individual_stock_weight_bar": make_sub_asset_holding_weight_bar(calculated, "개별주"),
        "holding_value_bar": make_holding_value_bar(calculated),
        "asset_value_bar": make_asset_value_bar(calculated),
        "account_value_bar": make_account_asset_stack_bar(calculated),
        "saebit_asset_donut": make_account_asset_donut(calculated, "새빛"),
        "heeju_asset_donut": make_account_asset_donut(calculated, "희주"),
        "saebit_major_asset_donut": make_account_major_asset_donut(calculated, "새빛"),
        "heeju_major_asset_donut": make_account_major_asset_donut(calculated, "희주"),
    }


def save_charts_as_png(charts: dict[str, go.Figure], charts_dir: Path) -> tuple[dict[str, Path], list[str]]:
    charts_dir.mkdir(parents=True, exist_ok=True)
    saved: dict[str, Path] = {}
    errors: list[str] = []
    for name, fig in charts.items():
        path = charts_dir / f"{name}.png"
        try:
            fig.write_image(str(path), width=1100, height=650, scale=2)
            saved[name] = path
        except Exception as exc:
            errors.append(f"{name} 그래프 PNG 저장에 실패했습니다. kaleido 설치 상태를 확인해주세요. ({exc})")
    return saved, errors
