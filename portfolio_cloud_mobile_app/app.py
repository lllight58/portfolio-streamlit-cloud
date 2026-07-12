from __future__ import annotations

import os
import html
import hmac
import re
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
except Exception:
    pass

from src import db
from src.chart_maker import make_all_charts
from src.excel_manager import settings_to_dict
from src.formatters import format_percent, format_quantity_for_display, infer_currency, parse_number
from src.portfolio_calculator import (
    ASSET_CLASSES,
    CAPITAL_FLOW_TYPES,
    MARKETS,
    TRANSACTION_COLUMNS,
    BUY_TRANSACTION_COLUMNS,
    account_asset_class_summary,
    account_value_summary,
    append_capital_flow,
    calculate_allocation_by_major_asset_class,
    calculate_portfolio,
    current_invested_principal,
    infer_major_asset_class,
    infer_market,
    normalize_capital_flows,
    normalize_holdings,
    normalize_sub_asset_class,
)
from src import price_fetcher
from src.repositories import holdings_repository as holdings_repo
from src.repositories.holdings_repository import (
    delete_holdings_by_selectors,
    delete_holdings_by_row_ids,
    ensure_row_ids,
    update_holdings_sort_order,
)
from src import symbol_resolver


APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
DEFAULT_EXCEL_PATH = ROOT_DIR / "portfolio.xlsx"
APP_TITLE = "포트폴리오"
MOBILE_MENUS = ["홈", "자산", "매수", "원금", "가격", "공시", "설정"]
DESKTOP_MENUS = ["대시보드", "자산 입력", "추가매수", "투자원금", "시세 업데이트", "주요 공시", "설정", "Excel 가져오기/내보내기"]
QUANTITY_COLUMNS = ["새빛_보유수량", "희주_보유수량", "합산_보유수량", "보유수량"]
QUANTITY_RAW_PREFIX = "__raw_"
BENCHMARK_RETURN_METHOD = getattr(price_fetcher, "BENCHMARK_RETURN_METHOD", "after_tax_total_return_krw_v2")
DIVIDEND_TAX_RATE = getattr(price_fetcher, "DIVIDEND_TAX_RATE", 0.154)
fetch_all_prices = price_fetcher.fetch_all_prices
fetch_benchmark_after_tax_total_return = getattr(
    price_fetcher,
    "fetch_benchmark_after_tax_total_return",
    price_fetcher.fetch_benchmark_return,
)
BENCHMARK_RETURN_NOTE = (
    "기준: 원금 투입시점 반영 · 2026년 1~7월은 매월 1일 360만원 추가투자 가정 · "
    "7월 10일 이후는 실제 추가입금 기록 반영 · 배당세 15.4% 차감 후 재투자"
)
BENCHMARK_SYNTHETIC_CUTOFF = pd.Timestamp("2026-07-10")
BENCHMARK_SYNTHETIC_MONTHLY_AMOUNT = 3_600_000.0
PROFIT_COLOR = "#D93025"
LOSS_COLOR = "#1A73E8"
NEUTRAL_COLOR = "#333333"
ASSET_CLASS_TABLE_BG_COLORS = {
    "ETF": "rgba(255, 102, 102, 0.22)",
    "개별주": "rgba(255, 153, 153, 0.25)",
    "미국채권": "rgba(109, 192, 255, 0.25)",
    "국내채권": "rgba(159, 214, 255, 0.28)",
    "한국리츠": "rgba(143, 214, 122, 0.25)",
    "암호화폐": "rgba(183, 227, 168, 0.28)",
    "달러": "rgba(191, 191, 191, 0.35)",
}
SYMBOL_NAME_CACHE = {
    "US:MEDP": "Medpace Holdings, Inc.",
    "CRYPTO:BTC": "Bitcoin",
    "CRYPTO:ETH": "Ethereum",
    "FX:USDKRW": "미국 달러 현금",
    "FX:USD": "미국 달러 현금",
}
APP_TIMEZONE = ZoneInfo("Asia/Seoul")
UTC_TIMEZONE = ZoneInfo("UTC")
DATA_CACHE_TTL_SECONDS = 30
DEFAULT_APP_PASSWORD = "92837"


@dataclass(frozen=True)
class AppSecurityLookupResult:
    market: str
    symbol: str
    name: str
    success: bool
    source: str
    reason: str = ""


st.set_page_config(page_title="포트폴리오", page_icon=str(APP_DIR / "assets" / "Yadon.ico"), layout="wide")


def main() -> None:
    apply_mobile_style()
    require_app_password()
    ensure_benchmark_return_method_state()
    st.title(APP_TITLE)
    init_error = None
    try:
        initialize_database_cached()
    except Exception as exc:
        init_error = exc
        st.error(f"DB 초기화 실패: {exc}")
        st.info(
            "Streamlit Cloud에 배포한 앱도 이전 데이터를 보려면 App settings > Secrets에 "
            "DATABASE_BACKEND=supabase와 SUPABASE_POOLER_DATABASE_URL을 반드시 넣어야 합니다. "
            "로컬 .env 파일은 Streamlit Cloud에 자동 반영되지 않습니다."
        )
    if getattr(db, "supabase_config_missing", lambda: False)():
        st.warning(
            "Supabase DB URL이 설정되지 않아 임시 로컬 저장소로 실행 중입니다. "
            "기존 데이터를 보려면 Streamlit Cloud Secrets에 SUPABASE_POOLER_DATABASE_URL을 설정하세요."
        )

    mode = st.radio(
        "화면 모드",
        ["모바일 앱 모드", "PC 넓은 화면 모드"],
        index=0 if st.session_state.get("screen_mode", "모바일 앱 모드") == "모바일 앱 모드" else 1,
        horizontal=True,
        key="screen_mode",
        label_visibility="collapsed",
    )
    if mode == "PC 넓은 화면 모드":
        menu = st.selectbox("메뉴 선택", DESKTOP_MENUS)
    else:
        menu = render_mobile_nav()

    if init_error and menu not in {"설정"}:
        st.stop()

    if mode == "PC 넓은 화면 모드":
        render_desktop_menu(menu)
    else:
        render_mobile_menu(menu)


def render_desktop_menu(menu: str) -> None:
    if menu == "대시보드":
        show_dashboard()
    elif menu == "자산 입력":
        show_holdings_editor()
    elif menu == "추가매수":
        show_bulk_buy()
    elif menu == "투자원금":
        show_capital_flows()
    elif menu == "시세 업데이트":
        show_price_update()
    elif menu == "주요 공시":
        show_disclosures()
    elif menu == "설정":
        show_settings()
    else:
        show_excel_tools()


def render_mobile_menu(menu: str) -> None:
    if menu == "홈":
        show_mobile_dashboard()
    elif menu == "자산":
        show_mobile_holdings_editor()
    elif menu == "매수":
        show_mobile_bulk_buy()
    elif menu == "원금":
        show_mobile_capital_flows()
    elif menu == "가격":
        show_price_update()
    elif menu == "공시":
        show_disclosures()
    else:
        show_mobile_settings()


def require_app_password() -> None:
    expected_password = app_secret("APP_PASSWORD")
    if not expected_password:
        st.error("앱 입장 비밀번호가 설정되어 있지 않습니다.")
        st.info("Streamlit Cloud Secrets 또는 로컬 .env에 APP_PASSWORD를 설정한 뒤 앱을 재시작하세요.")
        st.stop()

    if st.session_state.get("authenticated"):
        return

    st.title(APP_TITLE)
    st.subheader("입장 비밀번호")
    entered_password = st.text_input("비밀번호", type="password", label_visibility="collapsed")
    if st.button("입장", type="primary", use_container_width=True):
        if hmac.compare_digest(entered_password, expected_password):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    st.stop()


def app_secret(key: str) -> str:
    try:
        value = st.secrets.get(key)
    except Exception:
        value = None
    if value is not None and str(value).strip():
        return str(value).strip()
    env_value = os.getenv(key, "").strip()
    if env_value:
        return env_value
    if key == "APP_PASSWORD":
        return DEFAULT_APP_PASSWORD
    return ""


def ensure_benchmark_return_method_state() -> None:
    if st.session_state.get("benchmark_return_method") == BENCHMARK_RETURN_METHOD:
        return
    st.session_state.pop("benchmark_return", None)
    st.session_state.pop("benchmark_error", None)
    st.session_state["benchmark_return_method"] = BENCHMARK_RETURN_METHOD


def render_mobile_nav() -> str:
    selected = st.radio(
        "모바일 메뉴",
        MOBILE_MENUS,
        horizontal=True,
        key="mobile_menu",
        label_visibility="collapsed",
    )
    st.markdown('<div class="mobile-bottom-spacer"></div>', unsafe_allow_html=True)
    return selected


def load_core() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    tables = load_tables_cached(("holdings", "prices", "capital_flows"))
    holdings = tables["holdings"]
    prices = tables["prices"]
    capital_flows = tables["capital_flows"]
    calculated = calculate_portfolio_cached(holdings, prices)
    return holdings, prices, capital_flows, calculated


def load_mobile_dashboard_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, str], pd.DataFrame, pd.DataFrame]:
    tables = load_tables_cached(("holdings", "prices", "capital_flows", "settings", "portfolio_snapshots"))
    holdings = tables["holdings"]
    prices = tables["prices"]
    calculated = calculate_portfolio_cached(holdings, prices)
    settings_values = settings_to_dict(tables["settings"])
    return calculated, tables["capital_flows"], tables["portfolio_snapshots"], settings_values, holdings, prices


@st.cache_data(ttl=3600, show_spinner=False)
def initialize_database_cached() -> bool:
    db.initialize_database()
    return True


@st.cache_data(ttl=DATA_CACHE_TTL_SECONDS, show_spinner=False)
def load_table_cached(table_name: str) -> pd.DataFrame:
    return db.read_table(table_name)


@st.cache_data(ttl=DATA_CACHE_TTL_SECONDS, show_spinner=False)
def load_tables_cached(table_names: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    return db.read_tables(table_names)


@st.cache_data(ttl=DATA_CACHE_TTL_SECONDS, show_spinner=False)
def calculate_portfolio_cached(holdings: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    return calculate_portfolio(holdings, prices)


@st.cache_data(ttl=DATA_CACHE_TTL_SECONDS, show_spinner=False)
def make_all_charts_cached(calculated: pd.DataFrame) -> dict:
    return make_all_charts(calculated)


def clear_app_cache() -> None:
    st.cache_data.clear()


def clear_cached_tables(*table_names: str) -> None:
    for table_name in table_names:
        try:
            load_table_cached.clear(table_name)
        except TypeError:
            load_table_cached.clear()
        except Exception:
            load_table_cached.clear()
    try:
        load_tables_cached.clear()
    except Exception:
        pass
    try:
        calculate_portfolio_cached.clear()
    except Exception:
        pass
    try:
        make_all_charts_cached.clear()
    except Exception:
        pass
    if "capital_flows" in table_names:
        st.session_state.pop("benchmark_return", None)
        st.session_state.pop("benchmark_error", None)


def sync_after_holdings_mutation(*extra_tables: str) -> None:
    clear_cached_tables("holdings", *extra_tables)
    st.session_state.pop("holdings_editor_df", None)


def save_holding_row(holdings: pd.DataFrame, row_id: str, values: dict[str, object]) -> tuple[pd.DataFrame, str]:
    upsert_func = getattr(holdings_repo, "upsert_holding_row", None)
    if callable(upsert_func):
        return upsert_func(holdings, row_id, values)
    return upsert_holding_row_fallback(holdings, row_id, values)


def upsert_holding_row_fallback(holdings: pd.DataFrame, row_id: str, values: dict[str, object]) -> tuple[pd.DataFrame, str]:
    normalized = normalize_holdings(holdings)
    target = materialize_holding_values(values)
    target_row_id = str(row_id or "").strip()
    row_ids = normalized["row_id"].fillna("").astype(str)

    if target_row_id and target_row_id in set(row_ids):
        mask = row_ids == target_row_id
        for column, value in target.items():
            normalized.loc[mask, column] = value
        saved_row_id = target_row_id
    else:
        next_order = int(normalized["표시순서"].map(parse_number).max() or 0) + 1 if not normalized.empty else 1
        saved_row_id = f"mobile-{datetime.now():%Y%m%d%H%M%S%f}"
        target.update({"표시순서": next_order, "sort_order": next_order, "row_id": saved_row_id})
        normalized = pd.concat([normalized, pd.DataFrame([target])], ignore_index=True)

    return normalize_holdings(normalized), saved_row_id


def materialize_holding_values(values: dict[str, object]) -> dict[str, object]:
    target = values.copy()
    sub_asset_class = str(target.get("세부자산군", target.get("자산군", "")) or "")
    target["세부자산군"] = sub_asset_class
    target["상위자산군"] = infer_major_asset_class(sub_asset_class)
    target["자산군"] = sub_asset_class
    target["새빛_보유수량"] = parse_number(target.get("새빛_보유수량"))
    target["희주_보유수량"] = parse_number(target.get("희주_보유수량"))
    target["합산_보유수량"] = target["새빛_보유수량"] + target["희주_보유수량"]
    target["보유수량"] = target["합산_보유수량"]
    target["평균단가"] = parse_number(target.get("평균단가"))
    return target


SecurityLookupResult = AppSecurityLookupResult


def normalize_symbol(market: str, symbol: str) -> str:
    normalize_func = getattr(symbol_resolver, "normalize_symbol", None)
    if callable(normalize_func):
        return str(normalize_func(market, symbol))
    return "".join(str(symbol or "").split()).upper()


def lookup_security(market: str, symbol: str, asset_class: str | None = None, sub_asset_class: str | None = None) -> AppSecurityLookupResult:
    lookup_func = getattr(symbol_resolver, "lookup_security", None)
    if callable(lookup_func):
        result = lookup_func(market, symbol, asset_class, sub_asset_class)
        return AppSecurityLookupResult(
            str(getattr(result, "market", market) or "").upper(),
            str(getattr(result, "symbol", normalize_symbol(market, symbol)) or ""),
            str(getattr(result, "name", "") or ""),
            bool(getattr(result, "success", False)),
            str(getattr(result, "source", "symbol_resolver") or "symbol_resolver"),
            str(getattr(result, "reason", "") or ""),
        )

    normalized_market = str(market or "").strip().upper()
    normalized_symbol = normalize_symbol(normalized_market, symbol)
    get_name_func = getattr(symbol_resolver, "get_security_name", None)
    if not normalized_symbol:
        return AppSecurityLookupResult(normalized_market, "", "", False, "input", "empty_symbol")
    if callable(get_name_func):
        try:
            name = str(get_name_func(normalized_market, normalized_symbol, asset_class, sub_asset_class) or "")
            success = bool(name and name != normalized_symbol)
            return AppSecurityLookupResult(
                normalized_market,
                normalized_symbol,
                name or normalized_symbol,
                success,
                "legacy_get_security_name",
                "" if success else "metadata_name_missing",
            )
        except Exception as exc:
            return AppSecurityLookupResult(normalized_market, normalized_symbol, "", False, "legacy_get_security_name", type(exc).__name__)
    return AppSecurityLookupResult(normalized_market, normalized_symbol, normalized_symbol, False, "symbol_resolver_unavailable", "lookup_function_missing")


PLOTLY_CONFIG = {
    "displayModeBar": False,
    "scrollZoom": False,
    "doubleClick": False,
    "staticPlot": False,
    "responsive": True,
}


def render_chart(fig) -> None:
    if fig is None:
        return
    try:
        fig.update_layout(dragmode=False)
    except Exception:
        pass
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)


def show_dashboard() -> None:
    perf = []
    started = time.perf_counter()
    holdings, prices, capital_flows, calculated = load_core()
    perf.append(("대시보드 데이터 로딩", time.perf_counter() - started))
    settings_started = time.perf_counter()
    settings = load_table_cached("settings")
    settings_values = settings_to_dict(settings)
    perf.append(("설정 조회", time.perf_counter() - settings_started))
    principal = current_invested_principal(capital_flows)
    total_value = float(calculated["원화 환산 평가금액"].sum()) if "원화 환산 평가금액" in calculated.columns else 0.0
    profit = total_value - principal
    return_rate = (profit / principal) if principal else 0.0
    snapshot_started = time.perf_counter()
    yearly_return = calculate_this_year_return(load_table_cached("portfolio_snapshots"), total_value, return_rate)
    perf.append(("스냅샷 조회", time.perf_counter() - snapshot_started))
    benchmark_return = st.session_state.get("benchmark_return")
    benchmark_error = st.session_state.get("benchmark_error")

    st.subheader("대시보드")
    for label, value, delta in [
        ("전체 포트폴리오 총 평가금액", format_krw(total_value), None),
        ("투자원금", format_krw(principal), None),
        ("평가손익", format_krw(profit), format_percent(return_rate)),
        ("누적수익률", format_percent(return_rate), None),
        ("올해 수익률", format_percent(yearly_return), None),
        ("벤치마크 YTD 수익률(원화)", format_percent(benchmark_return) if benchmark_return is not None else "미조회", None),
        ("새빛 계좌 총 평가금액", format_krw(float(calculated.get("새빛_평가금액", pd.Series(dtype=float)).sum())), None),
        ("희주 계좌 총 평가금액", format_krw(float(calculated.get("희주_평가금액", pd.Series(dtype=float)).sum())), None),
    ]:
        st.metric(label, value, delta=delta)
    st.caption(BENCHMARK_RETURN_NOTE)
    if benchmark_error:
        st.caption(benchmark_error)
    if st.button("벤치마크 원화 YTD 수익률 조회", use_container_width=True):
        with st.spinner("벤치마크 원화 기준 수익률을 조회하는 중입니다."):
            st.session_state["benchmark_return"], st.session_state["benchmark_error"] = fetch_dashboard_benchmark(
                settings_values, capital_flows
            )
        st.rerun()
    render_return_history_section(load_table_cached("portfolio_snapshots"), total_value, return_rate, settings_values)

    if calculated.empty:
        st.info("자산 데이터가 없습니다. Excel 가져오기 또는 자산 입력에서 데이터를 추가하세요.")
        return

    chart_started = time.perf_counter()
    charts = make_all_charts_cached(calculated)
    perf.append(("차트 생성", time.perf_counter() - chart_started))
    render_chart(charts["major_asset_donut"])
    render_chart(charts["asset_donut"])
    render_chart(charts["etf_weight_bar"])
    render_chart(charts["individual_stock_weight_bar"])
    render_chart(charts["holding_value_bar"])
    render_chart(charts["asset_value_bar"])

    with st.expander("계좌별 상세분석", expanded=True):
        c1, c2 = st.columns(2)
        c1.metric("새빛 계좌 총 평가금액", format_krw(float(calculated.get("새빛_평가금액", pd.Series(dtype=float)).sum())))
        c2.metric("희주 계좌 총 평가금액", format_krw(float(calculated.get("희주_평가금액", pd.Series(dtype=float)).sum())))
        render_chart(charts["account_value_bar"])
        render_chart(charts["saebit_asset_donut"])
        render_chart(charts["heeju_asset_donut"])
        with st.expander("계좌별 상위자산군 비중"):
            render_chart(charts["saebit_major_asset_donut"])
            render_chart(charts["heeju_major_asset_donut"])

    display_calculated = build_dashboard_holdings_table(calculated)
    render_colored_holdings_table(display_calculated)
    with st.expander("상세 보유자산 전체 보기"):
        st.dataframe(display_calculated, use_container_width=True, hide_index=True, column_config=number_column_config())
    render_performance_debug(settings_values, perf)


def show_mobile_dashboard() -> None:
    calculated, capital_flows, snapshots, settings_values, _, prices = load_mobile_dashboard_data()
    principal = current_invested_principal(capital_flows)
    total_value = float(calculated["원화 환산 평가금액"].sum()) if "원화 환산 평가금액" in calculated.columns else 0.0
    profit = total_value - principal
    return_rate = (profit / principal) if principal else 0.0
    yearly_return = calculate_this_year_return(snapshots, total_value, return_rate)
    saebit_value = float(calculated.get("새빛_평가금액", pd.Series(dtype=float)).sum())
    heeju_value = float(calculated.get("희주_평가금액", pd.Series(dtype=float)).sum())
    benchmark_return = st.session_state.get("benchmark_return")
    benchmark_error = st.session_state.get("benchmark_error")
    benchmark_name = benchmark_label(settings_values)

    render_home_title(prices)
    metrics = [
        ("총 평가금액", format_krw(total_value), None),
        ("투자원금", format_krw(principal), None),
        ("평가손익", format_krw(profit), profit),
        ("누적수익률", format_percent(return_rate), return_rate),
        ("올해 수익률", format_percent(yearly_return), yearly_return),
        ("벤치마크 YTD 수익률(원화)", format_percent(benchmark_return) if benchmark_return is not None else "미조회", benchmark_return),
        ("새빛 계좌", format_krw(saebit_value), None),
        ("희주 계좌", format_krw(heeju_value), None),
    ]
    render_mobile_metric_grid(metrics)
    st.caption(f"벤치마크: {benchmark_name}")
    st.caption(BENCHMARK_RETURN_NOTE)
    if benchmark_error:
        st.caption(benchmark_error)
    if st.button("벤치마크 원화 YTD 수익률 조회", use_container_width=True):
        with st.spinner("벤치마크 원화 기준 수익률을 조회하는 중입니다."):
            st.session_state["benchmark_return"], st.session_state["benchmark_error"] = fetch_dashboard_benchmark(
                settings_values, capital_flows
            )
        st.rerun()
    render_return_history_section(snapshots, total_value, return_rate, settings_values)

    if calculated.empty:
        st.info("자산 데이터가 없습니다. 자산 메뉴 또는 Excel 업로드로 데이터를 추가하세요.")
        return

    with st.expander("그래프", expanded=False):
        if st.button("그래프 불러오기", use_container_width=True):
            st.session_state["mobile_charts_loaded"] = True
        if st.session_state.get("mobile_charts_loaded"):
            charts = make_all_charts_cached(calculated)
            chart_items = [
                ("상위자산군 비중", "major_asset_donut"),
                ("세부자산군 비중", "asset_donut"),
                ("ETF 내부 종목 비중", "etf_weight_bar"),
                ("개별주 내부 종목 비중", "individual_stock_weight_bar"),
                ("계좌별 자산군 구성", "account_value_bar"),
                ("새빛 계좌 자산군 비중", "saebit_asset_donut"),
                ("희주 계좌 자산군 비중", "heeju_asset_donut"),
            ]
            for label, key in chart_items:
                st.markdown(f"#### {label}")
                render_chart(charts.get(key))
        else:
            st.caption("첫 화면 속도를 위해 그래프는 필요할 때만 불러옵니다.")

    st.markdown("### 보유 종목")
    display_calculated = build_dashboard_holdings_table(calculated)
    render_mobile_colored_holdings_table(display_calculated)
    for _, row in display_calculated.iterrows():
        title = f"{row.get('티커 또는 종목코드', '')} | {row.get('종목명', '')}"
        with st.expander(title):
            detail_columns = [
                "자산군",
                "시장",
                "평가금액",
                "전체 포트폴리오 내 비중",
                "평가손익",
                "수익률",
                "새빛_보유수량_표시",
                "희주_보유수량_표시",
                "합산_보유수량_표시",
                "평균단가_표시",
            ]
            for column in detail_columns:
                if column in row.index:
                    st.write(f"{column.replace('_표시', '')}: {row.get(column)}")
    render_performance_debug(settings_values, [])


def render_home_title(prices: pd.DataFrame) -> None:
    updated_at = latest_price_update_text(prices)
    update_text = f"가격 업데이트: {updated_at}" if updated_at else "가격 업데이트: -"
    st.markdown(f"**홈**  ·  {update_text}")


def latest_price_update_text(prices: pd.DataFrame) -> str:
    if prices is None or prices.empty or "마지막 가격 업데이트 시각" not in prices.columns:
        return ""
    values = prices["마지막 가격 업데이트 시각"].dropna().astype(str).str.strip()
    values = values[values != ""]
    if values.empty:
        return ""
    parsed_values = []
    for value in values:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.tz_localize(UTC_TIMEZONE)
        parsed_values.append(parsed.tz_convert(APP_TIMEZONE))
    if parsed_values:
        latest = max(parsed_values)
        return latest.strftime("%Y-%m-%d %H:%M")
    return values.iloc[-1]


def render_mobile_metric_grid(metrics: list[tuple[str, str, object]]) -> None:
    for start in range(0, len(metrics), 2):
        columns = st.columns(2)
        for column, metric in zip(columns, metrics[start : start + 2]):
            label, value, signed = metric
            delta = None
            if signed is not None and label not in {"평가손익"}:
                delta = value if str(value).strip() not in {"미조회", "-"} else None
            with column:
                st.metric(label, value, delta=delta)


def render_mobile_colored_holdings_table(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("표시할 보유 종목 데이터가 없습니다.")
        return

    header_cells = "".join(f"<th>{label}</th>" for label in ["티커", "종목명", "평가금액", "전체비중", "수익률"])
    body_rows = []
    for _, row in df.iterrows():
        asset_class = str(row.get("자산군", row.get("세부자산군", "")) or "")
        bg = ASSET_CLASS_TABLE_BG_COLORS.get(asset_class, "rgba(255, 255, 255, 1)")
        symbol = str(row.get("티커 또는 종목코드", "") or "")
        values = [
            symbol,
            str(row.get("종목명", "") or ""),
            str(row.get("평가금액", "") or ""),
            str(row.get("전체 포트폴리오 내 비중", "") or ""),
            str(row.get("수익률", "") or ""),
        ]
        cells = []
        for label, value in zip(["티커", "종목명", "평가금액", "전체비중", "수익률"], values):
            style = ""
            align = "right" if label in {"평가금액", "전체비중", "수익률"} else "left"
            if label == "수익률":
                style = signed_value_style(row.get("수익률_numeric"))
            cells.append(f"<td style='text-align:{align}; {style}'>{html.escape(value)}</td>")
        body_rows.append(f"<tr style='background:{bg};'>{''.join(cells)}</tr>")

    st.markdown(
        f"""
        <div class="mobile-holdings-table-wrap">
          <table class="mobile-holdings-table mobile-compact-holdings-table">
            <thead><tr>{header_cells}</tr></thead>
            <tbody>{''.join(body_rows)}</tbody>
          </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_mobile_holdings_editor() -> None:
    st.markdown("### 자산")
    holdings = normalize_holdings(load_table_cached("holdings"))
    message = st.session_state.pop("mobile_holdings_message", None)
    if message:
        st.success(message)

    task_options = ["자산 수정", "새 자산 추가", "표시 순서 변경"] if not holdings.empty else ["새 자산 추가"]
    selected_task = st.radio(
        "자산 작업 선택",
        task_options,
        horizontal=True,
        key="mobile_asset_task",
        label_visibility="collapsed",
    )

    if selected_task == "새 자산 추가":
        render_mobile_holding_form(holdings, None, "new")
        return

    if holdings.empty:
        st.info("등록된 자산이 없습니다.")
        return

    if selected_task == "표시 순서 변경":
        render_holdings_order_controls(holdings, context="mobile")
        return

    labels = mobile_holding_labels(holdings)
    label_options = list(labels.keys())
    selected_row_id = st.session_state.pop("mobile_selected_holding_row_id", "")
    selected_index_value = 0
    if selected_row_id:
        for option_index, label in enumerate(label_options):
            row_index = labels[label]
            if str(holdings.loc[row_index].get("row_id", "") or "") == selected_row_id:
                selected_index_value = option_index
                st.session_state["mobile_selected_holding"] = label
                break
    selected_label = st.selectbox("수정할 자산 선택", label_options, index=selected_index_value, key="mobile_selected_holding")
    selected_index = labels.get(selected_label)
    if selected_index is not None:
        row = holdings.loc[selected_index]
        row_id = str(row.get("row_id", "") or f"row-{selected_index}")
        symbol = str(row.get("티커 또는 종목코드", "") or "")
        name = str(row.get("종목명", "") or "")
        sub_asset = str(row.get("세부자산군", row.get("자산군", "")) or "")
        with st.container(border=True):
            st.write(f"**{symbol} | {name}**")
            st.caption(f"{sub_asset} · {row.get('시장', '')} · {row.get('통화', '')}")
            st.caption(
                "새빛: "
                f"{format_quantity_for_display(row.get('새빛_보유수량'), sub_asset, row.get('시장', ''), symbol)}"
                " · 희주: "
                f"{format_quantity_for_display(row.get('희주_보유수량'), sub_asset, row.get('시장', ''), symbol)}"
            )
            st.caption(f"평균단가: {format_number_for_display(row.get('평균단가'), 2)}")
        with st.container(border=True):
            render_mobile_holding_form(holdings, row, row_id)
            if st.button("선택 자산 삭제", key=f"mobile_delete_holding_{row_id}", use_container_width=True):
                db.backup_database("before_mobile_holding_delete")
                delete_holdings_by_row_ids([row_id])
                sync_after_holdings_mutation()
                st.session_state.pop("mobile_selected_holding", None)
                st.session_state["mobile_holdings_message"] = f"{symbol} 자산을 삭제했습니다."
                st.rerun()

def mobile_holding_labels(holdings: pd.DataFrame) -> dict[str, int]:
    labels: dict[str, int] = {}
    seen: dict[str, int] = {}
    for idx, row in holdings.iterrows():
        symbol = str(row.get("티커 또는 종목코드", "") or "")
        name = str(row.get("종목명", "") or "")
        base = f"{symbol} | {name}" if name else symbol
        if not base.strip(" |"):
            base = f"이름 없는 자산 {idx + 1}"
        seen[base] = seen.get(base, 0) + 1
        label = base if seen[base] == 1 else f"{base} ({seen[base]})"
        labels[label] = int(idx)
    return labels


def initialize_mobile_holding_state(row: pd.Series, key_prefix: str, asset_value: str, market_value: str) -> None:
    defaults = {
        f"mh_asset_{key_prefix}": asset_value,
        f"mh_market_{key_prefix}": market_value,
        f"mh_symbol_{key_prefix}": str(row.get("티커 또는 종목코드", "") or ""),
        f"mh_name_{key_prefix}": str(row.get("종목명", "") or ""),
        f"mh_saebit_{key_prefix}": format_quantity_for_display(
            row.get("새빛_보유수량", 0), asset_value, market_value, row.get("티커 또는 종목코드", "")
        )
        if not row.empty
        else "",
        f"mh_heeju_{key_prefix}": format_quantity_for_display(
            row.get("희주_보유수량", 0), asset_value, market_value, row.get("티커 또는 종목코드", "")
        )
        if not row.empty
        else "",
        f"mh_avg_{key_prefix}": format_number_for_display(row.get("평균단가", ""), 2),
        f"mh_memo_{key_prefix}": str(row.get("메모", "") or ""),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_mobile_holding_state(key_prefix: str) -> None:
    prefixes = [
        "mh_asset",
        "mh_market",
        "mh_symbol",
        "mh_name",
        "mh_saebit",
        "mh_heeju",
        "mh_avg",
        "mh_memo",
        "mh_currency",
        "mh_lookup_status",
    ]
    for prefix in prefixes:
        st.session_state.pop(f"{prefix}_{key_prefix}", None)


def on_mobile_holding_class_change(key_prefix: str) -> None:
    sub_asset = st.session_state.get(f"mh_asset_{key_prefix}", "")
    current_market = st.session_state.get(f"mh_market_{key_prefix}", "")
    market = infer_market(sub_asset, current_market)
    st.session_state[f"mh_market_{key_prefix}"] = market
    symbol = st.session_state.get(f"mh_symbol_{key_prefix}", "")
    st.session_state[f"mh_currency_{key_prefix}"] = infer_currency(market, sub_asset, symbol)


def on_mobile_holding_market_change(key_prefix: str) -> None:
    sub_asset = st.session_state.get(f"mh_asset_{key_prefix}", "")
    market = st.session_state.get(f"mh_market_{key_prefix}", "")
    symbol = normalize_symbol(market, st.session_state.get(f"mh_symbol_{key_prefix}", ""))
    st.session_state[f"mh_symbol_{key_prefix}"] = symbol
    st.session_state[f"mh_currency_{key_prefix}"] = infer_currency(market, sub_asset, symbol)


def on_mobile_holding_symbol_change(key_prefix: str) -> None:
    market = st.session_state.get(f"mh_market_{key_prefix}", "")
    symbol = normalize_symbol(market, st.session_state.get(f"mh_symbol_{key_prefix}", ""))
    st.session_state[f"mh_symbol_{key_prefix}"] = symbol
    lookup_mobile_holding_name(key_prefix)


def lookup_mobile_holding_name(key_prefix: str) -> None:
    sub_asset = st.session_state.get(f"mh_asset_{key_prefix}", "")
    market = st.session_state.get(f"mh_market_{key_prefix}", "")
    symbol = normalize_symbol(market, st.session_state.get(f"mh_symbol_{key_prefix}", ""))
    if not symbol:
        st.session_state[f"mh_name_{key_prefix}"] = ""
        st.session_state.pop(f"mh_lookup_status_{key_prefix}", None)
        return
    result = lookup_security_remote(market, symbol, sub_asset)
    st.session_state[f"mh_name_{key_prefix}"] = result.name or result.symbol or ""
    st.session_state[f"mh_lookup_status_{key_prefix}"] = result


def render_mobile_holding_form(holdings: pd.DataFrame, row: pd.Series | None, key_prefix: str) -> None:
    is_new = row is None
    row = pd.Series(dtype=object) if row is None else row
    asset_value = normalize_sub_asset_class(row.get("세부자산군", row.get("자산군", "ETF")) or "ETF")
    market_value = infer_market(asset_value, row.get("시장", "US"))
    initialize_mobile_holding_state(row, key_prefix, asset_value, market_value)
    sub_asset = st.selectbox(
        "세부자산군",
        ASSET_CLASSES,
        key=f"mh_asset_{key_prefix}",
        on_change=on_mobile_holding_class_change,
        args=(key_prefix,),
    )
    st.text_input("상위자산군", value=infer_major_asset_class(sub_asset), disabled=True, key=f"mh_major_display_{key_prefix}")
    market = st.selectbox(
        "시장",
        MARKETS,
        key=f"mh_market_{key_prefix}",
        on_change=on_mobile_holding_market_change,
        args=(key_prefix,),
    )
    symbol = st.text_input(
        "티커_또는_종목코드",
        key=f"mh_symbol_{key_prefix}",
        on_change=on_mobile_holding_symbol_change,
        args=(key_prefix,),
    ).strip().upper()
    currency = infer_currency(market, sub_asset, symbol)
    st.session_state[f"mh_currency_{key_prefix}"] = currency
    name = st.text_input("종목명", key=f"mh_name_{key_prefix}")
    lookup_status = st.session_state.get(f"mh_lookup_status_{key_prefix}")
    if isinstance(lookup_status, SecurityLookupResult):
        if lookup_status.success:
            st.caption(f"조회 성공: {lookup_status.source}")
        else:
            st.warning(f"조회 실패: 데이터소스={lookup_status.source}, 원인={lookup_status.reason or 'not_found'}")
    st.text_input("통화", value=currency, disabled=True, key=f"mh_currency_display_{key_prefix}")
    saebit_qty = st.text_input("새빛_보유수량", key=f"mh_saebit_{key_prefix}")
    heeju_qty = st.text_input("희주_보유수량", key=f"mh_heeju_{key_prefix}")
    avg_price = st.text_input("평균단가", key=f"mh_avg_{key_prefix}")
    memo = st.text_area("메모", key=f"mh_memo_{key_prefix}", height=80)
    if st.button("종목명 다시 조회", key=f"mh_lookup_{key_prefix}", use_container_width=True):
        lookup_mobile_holding_name(key_prefix)
        st.rerun()
    submitted = st.button("자산 저장" if not is_new else "새 자산 저장", key=f"mh_save_{key_prefix}", type="primary", use_container_width=True)
    if not submitted:
        return
    if not symbol:
        st.error("티커_또는_종목코드를 입력하세요.")
        return
    updated, saved_row_id = save_holding_row(
        holdings,
        str(row.get("row_id", "") or ""),
        {
            "세부자산군": sub_asset,
            "시장": market,
            "티커 또는 종목코드": symbol,
            "종목명": name or "종목명이 검색되지 않습니다",
            "새빛_보유수량": parse_number_from_display(saebit_qty) or 0,
            "희주_보유수량": parse_number_from_display(heeju_qty) or 0,
            "평균단가": parse_number_from_display(avg_price) or 0,
            "통화": currency,
            "메모": memo,
        },
    )
    db.backup_database("before_mobile_holding_save")
    db.write_table("holdings", updated)
    sync_after_holdings_mutation()
    st.session_state["mobile_selected_holding_row_id"] = saved_row_id
    st.session_state["mobile_holdings_message"] = "자산 데이터를 저장했습니다."
    clear_mobile_holding_state(key_prefix)
    st.rerun()


def upsert_mobile_holding(holdings: pd.DataFrame, row_id: str, values: dict[str, object]) -> pd.DataFrame:
    updated, _ = save_holding_row(holdings, row_id, values)
    return prepare_holdings(updated)


def show_mobile_bulk_buy() -> None:
    st.markdown("### 매수")
    st.caption("원금 반영 없이 보유수량, 평균단가, 거래내역만 저장합니다.")
    holdings = normalize_holdings(load_table_cached("holdings"))
    holdings_lookup = {str(row.get("티커 또는 종목코드", "")).upper(): row for _, row in holdings.iterrows()}
    if "mobile_buy_row_ids" not in st.session_state:
        st.session_state["mobile_buy_row_ids"] = [f"mbuy-{datetime.now():%H%M%S%f}"]

    rows = []
    for number, row_id in enumerate(st.session_state["mobile_buy_row_ids"], start=1):
        with st.container(border=True):
            top, remove = st.columns([3, 1])
            top.caption(f"{number}번째 매수")
            if remove.button("입력행 삭제", key=f"mobile_delete_buy_{row_id}", use_container_width=True):
                st.session_state["mobile_buy_row_ids"] = [item for item in st.session_state["mobile_buy_row_ids"] if item != row_id] or [f"mbuy-{datetime.now():%H%M%S%f}"]
                st.rerun()
            account = st.selectbox("매수계좌", ["새빛", "희주"], key=f"mobile_buy_account_{row_id}")
            symbol = st.text_input("티커_또는_종목코드", key=f"mobile_buy_symbol_{row_id}").strip().upper()
            matched = holdings_lookup.get(symbol)
            asset_class, market, currency, name, lookup_status = buy_defaults_from_symbol(symbol, matched)
            st.caption(f"종목명: {name or '-'}")
            st.caption(f"자산군/시장/통화: {asset_class} / {market} / {currency}")
            if matched is None and lookup_status is not None:
                if lookup_status.success:
                    st.caption(f"신규 티커 조회 성공: {lookup_status.source}")
                else:
                    st.warning(f"신규 티커 조회 실패: 데이터소스={lookup_status.source}, 원인={lookup_status.reason or 'not_found'}")
            if matched is not None:
                st.caption(
                    "현재 보유수량: "
                    f"새빛 {format_quantity_for_display(matched.get('새빛_보유수량'), asset_class, market, symbol)} / "
                    f"희주 {format_quantity_for_display(matched.get('희주_보유수량'), asset_class, market, symbol)}"
                )
                st.caption(f"평균단가: {format_number_for_display(matched.get('평균단가'), 2)}")
            quantity = st.text_input("추가매수수량", key=f"mobile_buy_quantity_{row_id}", placeholder="예: 1 또는 0.12345678")
            price = st.text_input("추가매수단가", key=f"mobile_buy_price_{row_id}", placeholder="예: 123.45 또는 78.9012")
            rows.append(
                {
                    "매수계좌": account,
                    "티커 또는 종목코드": symbol,
                    "종목명": name or symbol,
                    "자산군": asset_class,
                    "시장": market,
                    "통화": currency,
                    "매수수량": parse_number_from_display(quantity) or 0,
                    "매수단가": parse_number_from_display(price) or 0,
                    "메모": "",
                }
            )
    add_col, reset_col = st.columns(2)
    if add_col.button("매수 종목 추가", key="mobile_add_buy_row_button", use_container_width=True):
        st.session_state["mobile_buy_row_ids"].append(f"mbuy-{datetime.now():%H%M%S%f}")
        st.rerun()
    if reset_col.button("입력 초기화", key="mobile_reset_buy_rows_button", use_container_width=True):
        st.session_state["mobile_buy_row_ids"] = [f"mbuy-{datetime.now():%H%M%S%f}"]
        st.rerun()
    if st.button("추가매수 일괄 반영", type="primary", use_container_width=True):
        result = apply_buys(pd.DataFrame(rows))
        sync_after_holdings_mutation("transactions", "buy_transactions")
        st.success(f"{result}건의 추가매수를 반영했습니다.")
    render_buy_transaction_revert_section(context="mobile")


def show_mobile_capital_flows() -> None:
    st.markdown("### 원금")
    flows = normalize_capital_flows(load_table_cached("capital_flows"))
    st.metric("현재 투자원금", f"{current_invested_principal(flows):,.0f}원")
    if st.session_state.pop("clear_mobile_capital_inputs", False):
        st.session_state["mobile_capital_amount_input"] = ""
        st.session_state["mobile_capital_memo_input"] = ""
    with st.container(border=True):
        flow_type = st.radio("유형", ["추가입금", "초기원금"], horizontal=True, key="mobile_capital_flow_type")
        amount_text = st.text_input("금액", key="mobile_capital_amount_input", placeholder="예: 1000000")
        amount = parse_integer_amount(amount_text)
        if amount is not None:
            st.caption(f"입력금액: {amount:,}원")
        memo = st.text_input("메모", key="mobile_capital_memo_input")
        if st.button("투자원금 기록", type="primary", use_container_width=True):
            if amount is None:
                st.error("금액을 입력하세요.")
                st.stop()
            updated = append_capital_flow(flows, flow_type, amount, memo=memo)
            db.backup_database("before_mobile_capital_flow_save")
            db.write_table("capital_flows", updated)
            clear_cached_tables("capital_flows")
            st.session_state["clear_mobile_capital_inputs"] = True
            st.rerun()
    st.markdown("### 기록")
    if flows.empty:
        st.info("투자원금 기록이 없습니다.")
        return
    recent_flows = flows.tail(5).sort_index(ascending=False)
    st.caption("최근 5개 기록만 표시합니다.")
    for idx, row in recent_flows.iterrows():
        with st.container(border=True):
            st.write(f"{row.get('일시', '')} · {row.get('유형', '')}")
            st.write(f"{format_integer_amount(row.get('금액'))}원")
            if row.get("메모", ""):
                st.caption(str(row.get("메모", "")))
            if st.button("삭제", key=f"mobile_delete_capital_{idx}", use_container_width=True):
                updated = delete_capital_flow_by_index(flows, int(idx))
                db.backup_database("before_mobile_capital_flow_delete")
                db.write_table("capital_flows", updated)
                clear_cached_tables("capital_flows")
                st.rerun()


def format_session_number_input(key: str) -> None:
    st.session_state[key] = format_amount_input_text(st.session_state.get(key, ""))


def show_mobile_settings() -> None:
    st.markdown("### 설정")
    tab_db, tab_excel = st.tabs(["DB", "Excel"])
    with tab_db:
        show_settings()
    with tab_excel:
        show_excel_tools()


def safe_index(options: list[str], value: str) -> int:
    try:
        return options.index(value)
    except ValueError:
        return 0


def show_holdings_editor() -> None:
    st.subheader("자산 입력")
    holdings = normalize_holdings(load_table_cached("holdings"))
    st.caption("변경사항은 Excel이 아니라 모바일 앱 DB에 저장됩니다.")
    holdings_message = st.session_state.pop("holdings_editor_message", None)
    if holdings_message:
        st.success(holdings_message)
    if "holdings_editor_df" not in st.session_state:
        st.session_state["holdings_editor_df"] = prepare_holdings_editor_df(holdings)
    if st.button("입력 종목 자동완성", use_container_width=True):
        st.session_state["holdings_editor_df"] = autocomplete_holdings(st.session_state.get("holdings_editor_df", holdings), holdings)
        st.success("세부자산군/시장/티커 기준으로 자동완성을 적용했습니다.")
        st.rerun()
    edited = st.data_editor(
        st.session_state.get("holdings_editor_df", holdings),
        key="holdings_editor",
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_order=[
            "상위자산군",
            "세부자산군",
            "시장",
            "티커 또는 종목코드",
            "종목명",
            "새빛_보유수량",
            "희주_보유수량",
            "합산_보유수량",
            "평균단가",
            "통화",
            "메모",
        ],
        column_config={
            "세부자산군": st.column_config.SelectboxColumn("세부자산군", options=ASSET_CLASSES),
            "시장": st.column_config.SelectboxColumn("시장", options=MARKETS),
            "통화": st.column_config.SelectboxColumn("통화", options=["KRW", "USD"]),
            "새빛_보유수량": st.column_config.TextColumn("새빛_보유수량"),
            "희주_보유수량": st.column_config.TextColumn("희주_보유수량"),
            "합산_보유수량": st.column_config.TextColumn("합산_보유수량"),
            "평균단가": st.column_config.NumberColumn("평균단가", format="%,.2f"),
        },
        disabled=["합산_보유수량"],
    )
    latest = autocomplete_holdings(edited, holdings)
    if not dataframes_equal(latest, st.session_state.get("holdings_editor_df", holdings)):
        st.session_state["holdings_editor_df"] = latest
        st.rerun()
    if st.button("자산 변경사항 DB 저장", type="primary", use_container_width=True):
        normalized = prepare_holdings(materialize_holdings_editor_df(st.session_state.get("holdings_editor_df", latest)))
        db.backup_database("before_holdings_save")
        db.write_table("holdings", normalized)
        st.session_state["holdings_editor_df"] = prepare_holdings_editor_df(normalized)
        sync_after_holdings_mutation()
        st.session_state["holdings_editor_message"] = "자산 데이터를 DB에 저장했습니다."
        st.rerun()

    render_holdings_delete_controls(holdings)
    render_holdings_order_controls(holdings, context="desktop")


def render_holdings_delete_controls(holdings: pd.DataFrame) -> None:
    st.divider()
    st.subheader("자산 삭제")
    if holdings.empty:
        st.info("삭제할 자산이 없습니다.")
        return

    label_to_selector = holding_selector_map(holdings)
    selected_labels = st.multiselect("삭제할 자산 선택", list(label_to_selector.keys()), key="delete_holding_labels")
    selected_selectors = [label_to_selector[label] for label in selected_labels]

    if st.button("선택 자산 삭제", use_container_width=True, disabled=not selected_selectors):
        st.session_state["pending_delete_selectors"] = selected_selectors
        st.session_state["pending_delete_labels"] = selected_labels

    pending_selectors = st.session_state.get("pending_delete_selectors", [])
    if pending_selectors:
        st.warning(
            "선택한 자산을 삭제하시겠습니까?\n\n"
            "삭제하면 holdings에서 해당 자산이 제거됩니다.\n"
            "거래내역 transactions는 기록 보존을 위해 기본적으로 삭제하지 않습니다."
        )
        for label in st.session_state.get("pending_delete_labels", []):
            st.caption(f"- {label}")

        c1, c2 = st.columns(2)
        if c1.button("삭제 확정", type="primary", use_container_width=True):
            db.backup_database("before_holdings_delete")
            deleted_count = delete_holdings_by_selectors(pending_selectors)
            st.session_state.pop("pending_delete_selectors", None)
            st.session_state.pop("pending_delete_labels", None)
            st.session_state.pop("holdings_editor_df", None)
            sync_after_holdings_mutation()
            st.session_state["holdings_editor_message"] = f"선택한 자산 {deleted_count}건을 삭제했습니다."
            st.rerun()
        if c2.button("삭제 취소", use_container_width=True):
            st.session_state.pop("pending_delete_selectors", None)
            st.session_state.pop("pending_delete_labels", None)
            st.info("삭제를 취소했습니다.")


def render_holdings_order_controls(holdings: pd.DataFrame, context: str = "desktop") -> None:
    st.divider()
    st.subheader("자산 표시 순서 변경")
    st.caption("위/아래 버튼으로 원하는 순서를 만든 뒤 순서 저장 버튼을 누르세요.")

    order_items = build_asset_order_items(holdings)
    if not order_items:
        render_asset_order_empty_diagnostics(holdings)
        return

    if len(order_items) == 1:
        st.info("순서 변경할 자산이 1개뿐입니다.")
        st.markdown(f"- {order_items[0]['label']}")
        return

    sorted_items = render_asset_order_sortable(order_items, context)
    if sorted_items is None:
        sorted_items = render_asset_order_fallback(order_items, context)

    if st.button("순서 저장", key=f"{context}_save_asset_order", use_container_width=True):
        order_items = [
            {"row_id": item["id"], "sort_order": index}
            for index, item in enumerate(sorted_items)
            if item.get("id")
        ]
        db.backup_database("before_holdings_order_save")
        updated_count = update_holdings_sort_order(order_items)
        st.session_state.pop("holdings_editor_df", None)
        sync_after_holdings_mutation()
        message = f"자산 표시 순서를 저장했습니다. ({updated_count}건)"
        if context == "mobile":
            st.session_state["mobile_holdings_message"] = message
        else:
            st.session_state["holdings_editor_message"] = message
        st.rerun()


def render_mobile_asset_order_editor(assets_df: pd.DataFrame | None) -> None:
    order_df = build_asset_order_df(assets_df)

    st.caption("DEBUG: mobile asset order section rendered - 2026-06-30")
    st.caption(f"DEBUG: assets rows = {0 if assets_df is None else len(assets_df)}")
    st.caption(f"DEBUG: order rows = {len(order_df)}")

    if order_df.empty:
        st.warning("표시할 자산이 없습니다. 자산 데이터 로딩 또는 필터 조건을 확인하세요.")
        render_asset_order_empty_diagnostics(assets_df)
        return

    fallback_state_key = "mobile_holdings_order_ids"
    original_ids = order_df["id"].astype(str).tolist()
    state_ids = [row_id for row_id in st.session_state.get(fallback_state_key, original_ids) if row_id in set(original_ids)]
    state_ids += [row_id for row_id in original_ids if row_id not in state_ids]
    if state_ids != original_ids:
        order_df = (
            order_df.assign(_state_order=order_df["id"].astype(str).map({row_id: index for index, row_id in enumerate(state_ids)}))
            .sort_values(["_state_order", "label"], kind="stable")
            .drop(columns=["_state_order"])
            .reset_index(drop=True)
        )

    editable_df = order_df[["display_order", "label", "id"]].copy()
    editable_df["display_order"] = range(1, len(editable_df) + 1)
    edited = st.data_editor(
        editable_df,
        key="mobile_asset_order_editor",
        hide_index=True,
        disabled=["label", "id"],
        column_config={
            "display_order": st.column_config.NumberColumn(
                "표시순서",
                min_value=1,
                max_value=len(editable_df),
                step=1,
            ),
            "label": st.column_config.TextColumn("자산"),
            "id": st.column_config.TextColumn("ID"),
        },
        use_container_width=True,
    )

    fallback_items = [{"id": str(row["id"]), "label": str(row["label"])} for _, row in editable_df.iterrows()]
    st.caption("드래그 또는 숫자 편집이 불편하면 아래 버튼으로도 순서를 바꿀 수 있습니다.")
    button_items = render_asset_order_fallback(fallback_items, "mobile")

    if st.button("순서 저장", key="mobile_save_asset_order", use_container_width=True):
        button_ids = [item["id"] for item in button_items]
        if isinstance(edited, pd.DataFrame) and not edited.empty:
            saved_df = edited.copy()
            saved_df["display_order"] = saved_df["display_order"].map(parse_number).astype(int)
            saved_df = saved_df.sort_values(["display_order", "label"], kind="stable").reset_index(drop=True)
            ordered_ids = saved_df["id"].astype(str).tolist()
        else:
            ordered_ids = button_ids
        if button_ids != editable_df["id"].astype(str).tolist() and ordered_ids == editable_df["id"].astype(str).tolist():
            ordered_ids = button_ids
        updated_count = save_asset_display_order(ordered_ids)
        clear_asset_cache_if_exists()
        st.session_state["mobile_holdings_message"] = f"자산 표시 순서를 저장했습니다. ({updated_count}건)"
        st.success("자산 표시 순서를 저장했습니다.")
        st.rerun()


def build_asset_order_df(assets_df: pd.DataFrame | None) -> pd.DataFrame:
    if assets_df is None or assets_df.empty:
        return pd.DataFrame(columns=["id", "label", "display_order"])

    df = normalize_holdings(assets_df).copy()
    if "sort_order" not in df.columns:
        df["sort_order"] = None
    order_values = df["sort_order"].map(parse_number)
    fallback_order = pd.Series(range(len(df)), index=df.index)
    df["display_order"] = order_values.where(order_values >= 0, fallback_order)

    rows = []
    for idx, row in df.iterrows():
        asset_id = str(row.get("row_id", "") or "").strip()
        if not asset_id:
            continue

        ticker = str(row.get("티커 또는 종목코드", "") or "").strip()
        name = str(row.get("종목명", "") or "").strip()
        asset_class = str(row.get("세부자산군", row.get("자산군", "")) or "").strip()
        market = str(row.get("시장", "") or "").strip()

        label_parts = []
        if ticker:
            label_parts.append(ticker)
        if name and name != ticker:
            label_parts.append(name)
        meta_parts = [value for value in [asset_class, market] if value]
        if meta_parts:
            label_parts.append(f"[{' / '.join(meta_parts)}]")

        rows.append(
            {
                "id": asset_id,
                "label": " ".join(label_parts).strip() or f"자산 {asset_id}",
                "display_order": int(row.get("display_order") if pd.notna(row.get("display_order")) else idx),
            }
        )

    order_df = pd.DataFrame(rows, columns=["id", "label", "display_order"])
    if order_df.empty:
        return order_df
    return order_df.sort_values(["display_order", "label"], kind="stable").reset_index(drop=True)


def save_asset_display_order(ordered_ids: list[str]) -> int:
    order_items = [
        {"row_id": str(asset_id), "sort_order": display_order}
        for display_order, asset_id in enumerate(ordered_ids)
        if str(asset_id).strip()
    ]
    db.backup_database("before_mobile_holdings_order_save")
    return update_holdings_sort_order(order_items)


def clear_asset_cache_if_exists() -> None:
    for key in [
        "assets_df",
        "holdings_df",
        "asset_order_df",
        "mobile_holdings_order_ids",
        "holdings_sortable_order",
        "mobile_holdings_sortable_order",
        "desktop_holdings_sortable_order",
    ]:
        st.session_state.pop(key, None)
    sync_after_holdings_mutation()


def build_asset_order_items(assets_df: pd.DataFrame | None) -> list[dict[str, str]]:
    if assets_df is None or assets_df.empty:
        return []

    df = normalize_holdings(assets_df).copy()
    if "sort_order" not in df.columns:
        df["sort_order"] = range(len(df))
    sort_values = df["sort_order"].map(parse_number)
    df["sort_order"] = sort_values.where(sort_values >= 0, range(len(df)))

    sort_cols = ["sort_order"]
    for column in ["세부자산군", "티커 또는 종목코드", "종목명"]:
        if column in df.columns:
            sort_cols.append(column)
    df = df.sort_values(sort_cols, kind="stable").reset_index(drop=True)

    items: list[dict[str, str]] = []
    seen_labels: dict[str, int] = {}
    for index, row in df.iterrows():
        row_id = str(row.get("row_id", "") or "").strip()
        if not row_id:
            row_id = f"row-{index}"
        ticker = str(row.get("티커 또는 종목코드", "") or "").strip()
        name = str(row.get("종목명", "") or "").strip()
        asset_class = str(row.get("세부자산군", row.get("자산군", "")) or "").strip()
        market = str(row.get("시장", "") or "").strip()

        label_parts = []
        if ticker:
            label_parts.append(ticker)
        if name and name != ticker:
            label_parts.append(name)
        suffix_parts = [value for value in [asset_class, market] if value]
        if suffix_parts:
            label_parts.append(f"[{' / '.join(suffix_parts)}]")
        base_label = " ".join(label_parts).strip() or f"자산 {row_id}"

        seen_labels[base_label] = seen_labels.get(base_label, 0) + 1
        label = base_label if seen_labels[base_label] == 1 else f"{base_label} ({seen_labels[base_label]})"
        items.append({"id": row_id, "label": label})
    return items


def render_asset_order_sortable(order_items: list[dict[str, str]], context: str) -> list[dict[str, str]] | None:
    return None


def render_asset_order_fallback(order_items: list[dict[str, str]], context: str) -> list[dict[str, str]]:
    state_key = f"{context}_holdings_order_ids"
    item_by_id = {item["id"]: item for item in order_items}
    current_ids = [item["id"] for item in order_items]
    state_ids = [row_id for row_id in st.session_state.get(state_key, current_ids) if row_id in item_by_id]
    missing_ids = [row_id for row_id in current_ids if row_id not in state_ids]
    ordered_ids = state_ids + missing_ids
    st.session_state[state_key] = ordered_ids

    for index, row_id in enumerate(ordered_ids):
        item = item_by_id[row_id]
        cols = st.columns([0.14, 0.14, 0.72])
        if cols[0].button("↑", key=f"{context}_order_up_{row_id}", disabled=index == 0):
            ordered_ids[index - 1], ordered_ids[index] = ordered_ids[index], ordered_ids[index - 1]
            st.session_state[state_key] = ordered_ids
            st.rerun()
        if cols[1].button("↓", key=f"{context}_order_down_{row_id}", disabled=index == len(ordered_ids) - 1):
            ordered_ids[index + 1], ordered_ids[index] = ordered_ids[index], ordered_ids[index + 1]
            st.session_state[state_key] = ordered_ids
            st.rerun()
        cols[2].markdown(f"{index + 1}. {item['label']}")
    return [item_by_id[row_id] for row_id in ordered_ids]


def render_asset_order_empty_diagnostics(holdings: pd.DataFrame | None) -> None:
    total_count = 0 if holdings is None else len(holdings)
    normalized_count = 0
    if holdings is not None and not holdings.empty:
        normalized_count = len(normalize_holdings(holdings))
    st.info("표시할 자산이 없습니다.")
    st.caption(f"현재 불러온 전체 자산 수: {total_count}")
    st.caption(f"필터 적용 후 자산 수: {normalized_count}")
    st.caption("사용 중인 계좌 필터: 없음")
    st.caption("사용 중인 자산군 필터: 없음")


def holding_label_map(holdings: pd.DataFrame) -> dict[str, str]:
    return {label: str(selector.get("row_id", "")) for label, selector in holding_selector_map(holdings).items()}


def holding_selector_map(holdings: pd.DataFrame) -> dict[str, dict[str, str]]:
    normalized = normalize_holdings(holdings)
    labels: dict[str, dict[str, str]] = {}
    seen: dict[str, int] = {}
    for _, row in normalized.iterrows():
        row_id = str(row.get("row_id", "") or "").strip()
        symbol = str(row.get("티커 또는 종목코드", "") or "").strip()
        name = str(row.get("종목명", "") or "").strip()
        base_label = f"{symbol} | {name}" if name else symbol
        if not base_label.strip(" |"):
            base_label = "이름 없는 자산"
        seen[base_label] = seen.get(base_label, 0) + 1
        label = base_label if seen[base_label] == 1 else f"{base_label} ({seen[base_label]})"
        labels[label] = {"row_id": row_id, "market": str(row.get("시장", "") or ""), "symbol": symbol}
    return labels


def show_bulk_buy() -> None:
    st.subheader("추가매수")
    st.caption("원금 반영 없이 보유수량, 평균단가, 거래내역만 DB에 반영합니다.")
    holdings = normalize_holdings(load_table_cached("holdings"))
    holdings_lookup = {str(row.get("티커 또는 종목코드", "")).upper(): row for _, row in holdings.iterrows()}
    if "buy_row_ids" not in st.session_state:
        st.session_state["buy_row_ids"] = [f"buy-{datetime.now():%H%M%S%f}"]
    rows = []
    for row_number, row_id in enumerate(st.session_state["buy_row_ids"], start=1):
        with st.container(border=True):
            head_col, delete_col = st.columns([3, 1])
            head_col.caption(f"{row_number}번째 추가매수")
            if delete_col.button("삭제", key=f"delete_buy_row_{row_id}", use_container_width=True):
                st.session_state["buy_row_ids"] = [value for value in st.session_state["buy_row_ids"] if value != row_id]
                if not st.session_state["buy_row_ids"]:
                    st.session_state["buy_row_ids"] = [f"buy-{datetime.now():%H%M%S%f}"]
                for field in ["account", "symbol", "quantity", "price", "memo"]:
                    st.session_state.pop(f"buy_{field}_{row_id}", None)
                st.rerun()
            c1, c2 = st.columns([1, 2])
            account = c1.selectbox("매수계좌", ["새빛", "희주"], key=f"buy_account_{row_id}")
            symbol = c2.text_input("티커/종목코드", key=f"buy_symbol_{row_id}", placeholder="예: VT, 005930").strip().upper()
            matched = holdings_lookup.get(symbol)
            default_asset, default_market, default_currency, default_name, lookup_status = buy_defaults_from_symbol(symbol, matched)
            default_avg = matched.get("평균단가", "") if matched is not None else ""
            st.text(f"종목명: {default_name or '-'}")
            st.text(f"자산군/시장/통화: {default_asset} / {default_market} / {default_currency}")
            if matched is None and lookup_status is not None:
                if lookup_status.success:
                    st.caption(f"신규 티커 조회 성공: {lookup_status.source}")
                else:
                    st.warning(f"신규 티커 조회 실패: 데이터소스={lookup_status.source}, 원인={lookup_status.reason or 'not_found'}")
            if matched is not None:
                st.text(
                    "현재 수량: "
                    f"새빛 {format_quantity_for_display(matched.get('새빛_보유수량'), default_asset, default_market, symbol)} / "
                    f"희주 {format_quantity_for_display(matched.get('희주_보유수량'), default_asset, default_market, symbol)} / "
                    f"합산 {format_quantity_for_display(matched.get('합산_보유수량'), default_asset, default_market, symbol)}"
                )
                st.text(f"현재 평균단가: {format_number_for_display(default_avg, 2)}")
            q_col, p_col = st.columns(2)
            quantity_text = q_col.text_input(
                "추가매수수량",
                key=f"buy_quantity_{row_id}",
                placeholder="예: 1,000 또는 0.12345678",
            )
            price_text = p_col.text_input(
                "추가매수단가",
                key=f"buy_price_{row_id}",
                placeholder="예: 123.45 또는 78.9012",
            )
            rows.append(
                {
                    "매수계좌": account,
                    "티커 또는 종목코드": symbol,
                    "종목명": default_name or symbol,
                    "자산군": default_asset,
                    "시장": default_market,
                    "통화": default_currency,
                    "매수수량": parse_number_from_display(quantity_text) or 0,
                    "매수단가": parse_number_from_display(price_text) or 0,
                    "메모": "",
                }
            )
    add_col, reset_col = st.columns(2)
    if add_col.button("매수 종목 추가", key="desktop_add_buy_row_button", use_container_width=True):
        st.session_state["buy_row_ids"].append(f"buy-{datetime.now():%H%M%S%f}")
        st.rerun()
    if reset_col.button("입력 초기화", key="desktop_reset_buy_rows_button", use_container_width=True):
        for row_id in st.session_state["buy_row_ids"]:
            for field in ["account", "symbol", "quantity", "price", "memo"]:
                st.session_state.pop(f"buy_{field}_{row_id}", None)
        st.session_state["buy_row_ids"] = [f"buy-{datetime.now():%H%M%S%f}"]
        st.rerun()
    buys = pd.DataFrame(rows)
    if st.button("추가매수 DB 반영", type="primary", use_container_width=True):
        result = apply_buys(buys)
        sync_after_holdings_mutation("transactions", "buy_transactions")
        st.success(f"{result}건의 추가매수를 반영했습니다.")
    render_buy_transaction_revert_section(context="desktop")


def show_capital_flows() -> None:
    st.subheader("투자원금")
    flows = normalize_capital_flows(load_table_cached("capital_flows"))
    st.metric("현재 투자원금", f"{current_invested_principal(flows):,.0f}원")
    capital_flow_message = st.session_state.pop("capital_flow_message", None)
    if capital_flow_message:
        st.success(capital_flow_message)
    if st.session_state.pop("clear_capital_flow_inputs", False):
        st.session_state["capital_flow_amount_input"] = ""
        st.session_state["capital_flow_memo_input"] = ""
    flow_type = st.selectbox("유형", CAPITAL_FLOW_TYPES, index=1)
    amount_text = st.text_input(
        "금액",
        placeholder="예: 3,000,000",
        key="capital_flow_amount_input",
        on_change=on_capital_amount_change,
    )
    amount = parse_integer_amount(amount_text)
    if amount_text.strip() and amount is None:
        st.warning("금액은 숫자 또는 콤마가 포함된 숫자로 입력해주세요.")
    memo = st.text_input("메모", key="capital_flow_memo_input")
    submitted = st.button("투자원금 기록 저장", type="primary", use_container_width=True)
    if submitted:
        if amount is None:
            st.error("저장할 금액을 입력해주세요.")
            st.stop()
        updated = append_capital_flow(flows, flow_type, amount, memo=memo)
        db.backup_database("before_capital_flow_save")
        db.write_table("capital_flows", updated)
        st.session_state["clear_capital_flow_inputs"] = True
        clear_cached_tables("capital_flows")
        st.session_state["capital_flow_message"] = "투자원금 기록을 DB에 저장했습니다."
        st.rerun()
    display_flows = format_capital_flows_for_display(flows)
    st.dataframe(display_flows, use_container_width=True, hide_index=True)
    render_capital_flow_delete_controls(flows)


def parse_integer_amount(value):
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    text = text.replace(",", "").replace("원", "").strip()
    try:
        return int(float(text))
    except ValueError:
        return None


def format_amount_input_text(value) -> str:
    text = str(value or "").strip()
    if text == "":
        return ""
    text = text.replace(",", "").replace("원", "").strip()
    if not text:
        return ""
    try:
        return f"{int(float(text)):,}"
    except ValueError:
        return str(value)


def on_capital_amount_change() -> None:
    st.session_state["capital_flow_amount_input"] = format_amount_input_text(
        st.session_state.get("capital_flow_amount_input", "")
    )


def format_integer_amount(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{int(float(str(value).replace(',', ''))):,}"
    except Exception:
        return str(value)


def format_capital_flows_for_display(flows: pd.DataFrame) -> pd.DataFrame:
    output = normalize_capital_flows(flows).copy()
    if output.empty:
        return output
    for column in ["금액", "반영 후 투자원금"]:
        if column in output.columns:
            output[column] = output[column].map(format_integer_amount)
    return output


def render_capital_flow_delete_controls(flows: pd.DataFrame) -> None:
    st.divider()
    st.subheader("투자원금 기록 삭제")
    normalized = normalize_capital_flows(flows)
    if normalized.empty:
        st.info("삭제할 투자원금 기록이 없습니다.")
        return

    recent = normalized.tail(5)
    st.caption("삭제 목록에는 최근 5개 기록만 표시합니다.")
    label_to_index = capital_flow_selector_map(recent)
    selected_label = st.selectbox("삭제할 투자원금 기록 선택", [""] + list(label_to_index.keys()), key="delete_capital_flow_label")
    if st.button("선택 기록 삭제", use_container_width=True, disabled=not selected_label):
        st.session_state["pending_delete_capital_flow_label"] = selected_label
        st.session_state["pending_delete_capital_flow_index"] = label_to_index.get(selected_label)

    pending_index = st.session_state.get("pending_delete_capital_flow_index")
    if pending_index is not None:
        st.warning("선택한 투자원금 기록을 삭제하시겠습니까?\n\n삭제 후 투자원금 계산에서 제외됩니다.")
        st.caption(st.session_state.get("pending_delete_capital_flow_label", ""))
        c1, c2 = st.columns(2)
        if c1.button("삭제 확정", type="primary", use_container_width=True):
            updated = delete_capital_flow_by_index(normalized, int(pending_index))
            db.backup_database("before_capital_flow_delete")
            db.write_table("capital_flows", updated)
            st.session_state.pop("pending_delete_capital_flow_label", None)
            st.session_state.pop("pending_delete_capital_flow_index", None)
            clear_cached_tables("capital_flows")
            st.session_state["capital_flow_message"] = "선택한 투자원금 기록을 삭제했습니다."
            st.rerun()
        if c2.button("삭제 취소", use_container_width=True):
            st.session_state.pop("pending_delete_capital_flow_label", None)
            st.session_state.pop("pending_delete_capital_flow_index", None)
            st.rerun()


def capital_flow_selector_map(flows: pd.DataFrame) -> dict[str, int]:
    labels: dict[str, int] = {}
    seen: dict[str, int] = {}
    for idx, row in flows.iterrows():
        base = (
            f"{row.get('일시', '')} | {row.get('유형', '')} | "
            f"{format_integer_amount(row.get('금액'))} | {row.get('메모', '')}"
        )
        seen[base] = seen.get(base, 0) + 1
        label = base if seen[base] == 1 else f"{base} ({seen[base]})"
        labels[label] = int(idx)
    return labels


def delete_capital_flow_by_index(flows: pd.DataFrame, delete_index: int) -> pd.DataFrame:
    remaining = normalize_capital_flows(flows).drop(index=delete_index, errors="ignore").reset_index(drop=True)
    rebuilt = pd.DataFrame()
    for _, row in remaining.iterrows():
        rebuilt = append_capital_flow(
            rebuilt,
            str(row.get("유형", "")),
            parse_number(row.get("금액", 0)),
            memo=str(row.get("메모", "") or ""),
            timestamp=str(row.get("일시", "") or "") or None,
        )
    return normalize_capital_flows(rebuilt)


def show_price_update() -> None:
    st.subheader("시세 업데이트")
    holdings = load_table_cached("holdings")
    if st.button("현재 보유자산 시세 조회 후 DB 저장", type="primary", use_container_width=True):
        with st.spinner("시세를 조회하는 중입니다."):
            update_targets = holdings.drop_duplicates(subset=[column for column in ["시장", "티커 또는 종목코드"] if column in holdings.columns])
            prices, errors = fetch_all_prices(update_targets)
            previous_prices = load_table_cached("prices")
            prices = preserve_previous_prices_on_failure(prices, previous_prices)
            errors = suppress_errors_for_preserved_prices(errors, prices)
        db.backup_database("before_price_update")
        db.write_table("prices", prices)
        clear_cached_tables("prices")
        st.success("시세를 DB에 저장했습니다.")
        for error in errors[:10]:
            st.warning(error)
    st.dataframe(load_table_cached("prices"), use_container_width=True, hide_index=True, column_config=number_column_config())


def preserve_previous_prices_on_failure(latest: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    if latest is None or latest.empty or previous is None or previous.empty:
        return latest
    output = latest.copy()
    previous_by_symbol = previous.drop_duplicates("티커 또는 종목코드", keep="last").set_index("티커 또는 종목코드")
    for index, row in output.iterrows():
        if pd.notna(row.get("현재가")) and parse_number(row.get("현재가")) > 0:
            continue
        symbol = str(row.get("티커 또는 종목코드", "") or "")
        if symbol not in previous_by_symbol.index:
            continue
        old = previous_by_symbol.loc[symbol]
        old_price = parse_number(old.get("현재가", 0))
        if old_price <= 0:
            continue
        output.at[index, "현재가"] = old_price
        output.at[index, "USD/KRW"] = parse_number(old.get("USD/KRW", row.get("USD/KRW", 0)))
        output.at[index, "상태"] = "기존 저장가격 유지"
    return output


def suppress_errors_for_preserved_prices(errors: list[str], prices: pd.DataFrame) -> list[str]:
    if not errors or prices is None or prices.empty:
        return errors
    preserved = set(
        prices.loc[prices["상태"].astype(str) == "기존 저장가격 유지", "티커 또는 종목코드"]
        .fillna("")
        .astype(str)
    )
    if not preserved:
        return errors
    return [error for error in errors if not any(error.startswith(f"{symbol} ") for symbol in preserved)]


def show_disclosures() -> None:
    st.subheader("주요 공시")
    st.info("1차 모바일 DB 버전에서는 저장된 공시 조회와 관심 종목 관리부터 제공합니다. API 새로고침은 다음 단계에서 DB 저장 방식으로 이전하세요.")
    disclosures = load_table_cached("disclosures")
    watchlist = load_table_cached("disclosure_watchlist")
    st.dataframe(disclosures, use_container_width=True, hide_index=True)
    with st.expander("관심/제외 종목 목록"):
        edited = st.data_editor(watchlist, use_container_width=True, hide_index=True, num_rows="dynamic")
        if st.button("관심 종목 DB 저장", use_container_width=True):
            db.backup_database("before_watchlist_save")
            db.write_table("disclosure_watchlist", edited)
            clear_cached_tables("disclosure_watchlist")
            st.success("관심 종목 목록을 저장했습니다.")


def show_settings() -> None:
    st.subheader("설정")
    st.write("DB 연결")
    st.text(f"DATABASE_BACKEND: {os.getenv('DATABASE_BACKEND', 'sqlite')}")
    st.text(f"SQLITE_DB_PATH: {os.getenv('SQLITE_DB_PATH', 'data/portfolio.db')}")
    diagnostics = db.supabase_connection_diagnostics()
    st.text(f"사용 중인 연결 종류: {diagnostics['connection_type']}")
    st.text(f"사용 중인 host: {diagnostics['host']}")
    st.text(f"사용 중인 port: {diagnostics['port']}")
    st.text(f"DNS 해석: {'성공' if diagnostics['dns_ok'] else '실패'}")
    st.text(f"SUPABASE_POOLER_DATABASE_URL: {db.mask_database_url(os.getenv('SUPABASE_POOLER_DATABASE_URL', ''))}")
    st.text(f"DATABASE_URL: {db.mask_database_url(os.getenv('DATABASE_URL', ''))}")
    st.caption("설정 우선순위는 Streamlit secrets, OS 환경변수, 로컬 .env 순서입니다. 값을 바꾼 뒤에는 앱을 재시작하세요.")

    c1, c2, c3 = st.columns(3)
    if c1.button("Supabase 연결 테스트", use_container_width=True):
        ok, message = db.test_supabase_connection()
        if ok:
            st.success(message)
        else:
            st.error(message)

    if c2.button("Supabase 테이블 생성/점검", use_container_width=True):
        ok, message = db.run_supabase_schema()
        if ok:
            st.success(message)
        else:
            st.error(message)

    if c3.button("Direct 연결 테스트", use_container_width=True):
        ok, message = db.test_supabase_direct_connection()
        if ok:
            st.success(message)
        else:
            st.error(message)

    upload_mode_label = st.radio(
        "SQLite 데이터를 Supabase로 업로드 방식",
        ["기존 Supabase 데이터 유지 후 추가", "기존 Supabase 데이터 삭제 후 새로 업로드"],
        horizontal=False,
    )
    confirm_upload = st.checkbox("Supabase 업로드를 실행하기 전에 내용을 확인했습니다.")
    if st.button("SQLite 데이터를 Supabase로 업로드", use_container_width=True, disabled=not confirm_upload):
        mode = "replace" if upload_mode_label.startswith("기존 Supabase 데이터 삭제") else "append"
        try:
            with st.spinner("SQLite 데이터를 Supabase로 업로드하는 중입니다."):
                result = db.upload_sqlite_to_supabase(mode=mode)
            st.success(f"Supabase 업로드 완료: {result}")
        except Exception as exc:
            st.error(f"Supabase 업로드 실패: {exc}")

    st.divider()
    st.subheader("기존 PC 앱 데이터 가져오기")
    st.caption("기존 PC용 `portfolio.xlsx`는 읽기만 하며 수정하지 않습니다.")
    if st.button("기존 portfolio.xlsx 찾기", use_container_width=True):
        found = db.find_pc_portfolio_excels()
        st.session_state["pc_excel_candidates"] = [str(path) for path in found]
        if found:
            st.success(f"{len(found)}개 파일을 찾았습니다.")
        else:
            st.warning("자동으로 찾은 portfolio.xlsx가 없습니다. 아래 경로 입력 또는 파일 업로드를 사용하세요.")

    candidates = st.session_state.get("pc_excel_candidates") or [str(DEFAULT_EXCEL_PATH)]
    selected_excel = st.selectbox("가져올 Excel 경로", candidates)
    manual_excel_path = st.text_input("직접 경로 입력", value=selected_excel)
    uploaded_excel = st.file_uploader("또는 기존 portfolio.xlsx 업로드", type=["xlsx"], key="pc_excel_upload")

    excel_path = Path(manual_excel_path)
    if uploaded_excel is not None:
        excel_path = db.DATA_DIR / "_uploaded_pc_portfolio.xlsx"
        excel_path.write_bytes(uploaded_excel.getbuffer())

    if st.button("기존 portfolio.xlsx에서 미리보기", use_container_width=True):
        try:
            preview = db.preview_excel(excel_path)
            st.session_state["pc_excel_preview"] = preview
            st.dataframe(pd.DataFrame.from_dict(preview, orient="index"), use_container_width=True)
        except Exception as exc:
            st.error(f"미리보기에 실패했습니다: {exc}")

    if "pc_excel_preview" in st.session_state:
        st.dataframe(pd.DataFrame.from_dict(st.session_state["pc_excel_preview"], orient="index"), use_container_width=True)

    confirm_replace = st.checkbox(
        "현재 Supabase DB의 holdings, transactions, capital_flows, prices, settings, disclosures 데이터가 기존 PC 앱 데이터로 교체됩니다. 계속하시겠습니까?"
    )
    if st.button("Supabase 초기화 후 기존 PC 앱 데이터로 교체", type="primary", use_container_width=True, disabled=not confirm_replace):
        try:
            with st.spinner("기존 PC 앱 데이터를 Supabase로 가져오는 중입니다."):
                report = db.import_excel_to_current_backend(excel_path, mode="replace")
            st.success("기존 PC 앱 데이터 가져오기 완료")
            st.dataframe(import_report_frame(report), use_container_width=True, hide_index=True)
            st.cache_data.clear()
            st.rerun()
        except Exception as exc:
            st.error(f"기존 PC 앱 데이터 가져오기에 실패했습니다: {exc}")

    confirm_append = st.checkbox("기존 Supabase 데이터를 유지하고 중복을 정리하며 추가로 가져옵니다.", key="confirm_pc_append")
    if st.button("기존 데이터 추가로 가져오기", use_container_width=True, disabled=not confirm_append):
        try:
            with st.spinner("기존 PC 앱 데이터를 추가로 가져오는 중입니다."):
                report = db.import_excel_to_current_backend(excel_path, mode="append")
            st.success("기존 PC 앱 데이터 추가 가져오기 완료")
            st.dataframe(import_report_frame(report), use_container_width=True, hide_index=True)
            st.cache_data.clear()
            st.rerun()
        except Exception as exc:
            st.error(f"기존 PC 앱 데이터 추가 가져오기에 실패했습니다: {exc}")

    st.divider()
    try:
        settings = load_table_cached("settings")
    except Exception as exc:
        st.warning(f"settings 테이블을 읽지 못했습니다. DB 연결 설정을 먼저 확인하세요. ({exc})")
        settings = pd.DataFrame({"설정": [], "값": []})
    env_keys = [
        "DATABASE_BACKEND",
        "SQLITE_DB_PATH",
        "DATABASE_URL",
        "SUPABASE_POOLER_DATABASE_URL",
        "SUPABASE_DIRECT_DATABASE_URL",
        "SUPABASE_PROJECT_URL",
        "APP_PASSWORD",
        "OPENAI_API_KEY",
        "OPENDART_API_KEY",
        "SEC_USER_AGENT",
    ]
    st.write("환경 변수 상태")
    for key in env_keys:
        value = os.getenv(key, "")
        st.text(f"{key}: {mask_secret(value)}")
    edited = st.data_editor(settings, use_container_width=True, hide_index=True, num_rows="dynamic")
    if st.button("설정 DB 저장", type="primary", use_container_width=True):
        db.backup_database("before_settings_save")
        db.write_table("settings", edited)
        clear_cached_tables("settings")
        st.success("설정을 DB에 저장했습니다.")


def show_excel_tools() -> None:
    st.subheader("Excel 가져오기/내보내기")
    st.warning("가져오기는 기존 Excel을 읽기만 하며 수정하지 않습니다. 가져오기 전 현재 DB를 자동 백업합니다.")
    excel_path_text = st.text_input("기존 Excel 경로", value=str(DEFAULT_EXCEL_PATH))
    uploaded = st.file_uploader("또는 Excel 파일 업로드", type=["xlsx"])
    if st.button("기존 Excel 데이터 가져오기", type="primary", use_container_width=True):
        if uploaded is not None:
            temp_path = db.DATA_DIR / "_uploaded_import.xlsx"
            temp_path.write_bytes(uploaded.getbuffer())
            path = temp_path
        else:
            path = Path(excel_path_text)
        imported = db.import_excel(path)
        clear_app_cache()
        st.success(f"Excel 데이터를 DB로 가져왔습니다: {imported}")

    if st.button("Excel로 내보내기", use_container_width=True):
        export_path = db.export_excel()
        st.success(f"Excel 파일을 생성했습니다: {export_path}")
        st.download_button(
            "생성된 Excel 다운로드",
            data=export_path.read_bytes(),
            file_name=export_path.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    backup = st.button("현재 DB 백업 생성", use_container_width=True)
    if backup:
        backup_path = db.backup_database("manual")
        st.success(f"백업 생성 완료: {backup_path}" if backup_path else "백업할 DB가 아직 없습니다.")


def prepare_holdings(df: pd.DataFrame) -> pd.DataFrame:
    normalized = normalize_holdings(df)
    normalized["세부자산군"] = normalized["자산군"].map(normalize_sub_asset_class)
    normalized["자산군"] = normalized["세부자산군"]
    normalized["상위자산군"] = normalized["세부자산군"].map(infer_major_asset_class)
    normalized["시장"] = normalized.apply(lambda row: infer_market(row["세부자산군"], row["시장"]), axis=1)
    normalized["새빛_보유수량"] = normalized["새빛_보유수량"].map(parse_number)
    normalized["희주_보유수량"] = normalized["희주_보유수량"].map(parse_number)
    normalized["합산_보유수량"] = normalized["새빛_보유수량"] + normalized["희주_보유수량"]
    normalized["보유수량"] = normalized["합산_보유수량"]
    return normalize_holdings(normalized)


def apply_buys(buys: pd.DataFrame) -> int:
    holdings = normalize_holdings(db.read_table("holdings"))
    transaction_rows = []
    buy_transaction_rows = []
    batch_id = str(uuid4())
    created_at = datetime.now().isoformat(timespec="seconds")
    applied = 0
    for _, row in buys.iterrows():
        quantity = parse_number(row.get("매수수량"))
        unit_price = parse_number(row.get("매수단가"))
        symbol = str(row.get("티커 또는 종목코드", "") or "").strip().upper()
        if not symbol or quantity <= 0 or unit_price < 0:
            continue
        account = str(row.get("매수계좌", "새빛") or "새빛")
        asset_class = normalize_sub_asset_class(row.get("자산군", "ETF"))
        market = infer_market(asset_class, row.get("시장", "US"))
        currency = str(row.get("통화", "USD") or "USD").upper()
        name = str(row.get("종목명", "") or symbol)
        target_col = "새빛_보유수량" if account == "새빛" else "희주_보유수량"
        matches = holdings["티커 또는 종목코드"].astype(str).str.upper() == symbol
        if matches.any():
            trade_type = "추가매수"
            idx = holdings[matches].index[0]
            asset_class = str(holdings.at[idx, "자산군"] or asset_class)
            market = str(holdings.at[idx, "시장"] or market)
            currency = str(holdings.at[idx, "통화"] or currency).upper()
            name = str(holdings.at[idx, "종목명"] or name)
            old_qty = parse_number(holdings.at[idx, target_col])
            old_total_qty = parse_number(holdings.at[idx, "합산_보유수량"])
            old_avg = parse_number(holdings.at[idx, "평균단가"])
            holdings.at[idx, target_col] = old_qty + quantity
            new_total_qty = old_total_qty + quantity
            holdings.at[idx, "평균단가"] = ((old_total_qty * old_avg) + (quantity * unit_price)) / new_total_qty if new_total_qty else unit_price
        else:
            trade_type = "신규매수"
            next_order = int(holdings["표시순서"].map(parse_number).max() or 0) + 1
            new_row = {
                "표시순서": next_order,
                "sort_order": next_order,
                "row_id": f"mobile-{datetime.now():%Y%m%d%H%M%S%f}",
                "상위자산군": infer_major_asset_class(asset_class),
                "세부자산군": asset_class,
                "자산군": asset_class,
                "시장": market,
                "티커 또는 종목코드": symbol,
                "종목명": name,
                "새빛_보유수량": quantity if account == "새빛" else 0,
                "희주_보유수량": quantity if account == "희주" else 0,
                "합산_보유수량": quantity,
                "보유수량": quantity,
                "평균단가": unit_price,
                "통화": currency,
                "메모": str(row.get("메모", "") or ""),
            }
            holdings = pd.concat([holdings, pd.DataFrame([new_row])], ignore_index=True)
        holdings = prepare_holdings(holdings)
        transaction_rows.append(make_transaction(row, account, asset_class, market, symbol, name, quantity, unit_price, currency, holdings, trade_type))
        latest = holdings[holdings["티커 또는 종목코드"].astype(str).str.upper() == symbol].iloc[0]
        buy_transaction_rows.append(
            record_buy_transaction(
                batch_id,
                str(latest.get("row_id", "") or ""),
                {
                    "티커": symbol,
                    "종목명": name,
                    "계좌": account,
                    "수량": quantity,
                    "단가": unit_price,
                    "금액": quantity * unit_price,
                    "통화": currency,
                    "메모": str(row.get("메모", "") or ""),
                    "생성일시": created_at,
                },
            )
        )
        applied += 1
    if applied:
        db.backup_database("before_bulk_buy")
        db.write_table("holdings", holdings)
        db.append_rows("transactions", pd.DataFrame(transaction_rows, columns=TRANSACTION_COLUMNS))
        db.append_rows("buy_transactions", pd.DataFrame(buy_transaction_rows, columns=BUY_TRANSACTION_COLUMNS))
    return applied


def record_buy_transaction(batch_id: str, asset_id: str, row: dict | pd.Series) -> dict:
    quantity = parse_number(row.get("수량", row.get("매수수량", 0)))
    unit_price = parse_number(row.get("단가", row.get("매수단가", 0)))
    return {
        "거래ID": str(uuid4()),
        "일괄반영ID": batch_id,
        "자산ID": str(asset_id or ""),
        "티커": str(row.get("티커", row.get("티커 또는 종목코드", "")) or "").strip().upper(),
        "종목명": str(row.get("종목명", "") or ""),
        "계좌": str(row.get("계좌", row.get("매수계좌", "새빛")) or "새빛"),
        "수량": quantity,
        "단가": unit_price,
        "금액": parse_number(row.get("금액")) or quantity * unit_price,
        "통화": str(row.get("통화", "USD") or "USD").upper(),
        "메모": str(row.get("메모", "") or ""),
        "생성일시": str(row.get("생성일시", "") or datetime.now().isoformat(timespec="seconds")),
        "되돌림여부": False,
        "되돌림일시": "",
        "되돌림사유": "",
    }


def render_buy_transaction_revert_section(context: str) -> None:
    st.divider()
    st.subheader("최근 추가매수 반영 내역 되돌리기")
    recent_tx = load_recent_buy_transactions(limit=5)
    if not recent_tx:
        st.info("되돌릴 수 있는 최근 추가매수 내역이 없습니다.")
        return

    apply_buy_transaction_card_style()
    tx_by_id = {str(tx.get("거래ID", "")): tx for tx in recent_tx}
    selected_tx_id = st.radio(
        "되돌릴 추가매수 내역을 1개만 선택하세요.",
        list(tx_by_id.keys()),
        format_func=lambda tx_id: format_buy_transaction_label(tx_by_id.get(str(tx_id), {})),
        key=f"{context}_revert_buy_transaction_radio",
    )
    selected_tx = tx_by_id.get(str(selected_tx_id), {})
    st.warning(
        "선택한 추가매수 1건을 되돌립니다:\n\n"
        f"{format_buy_transaction_confirmation(selected_tx)}\n\n"
        "여러 건 일괄 삭제는 지원하지 않습니다."
    )
    confirm = st.checkbox(
        "선택한 추가매수 반영 내역을 되돌리는 것을 확인합니다.",
        key=f"{context}_confirm_revert_buy_transaction",
    )
    if st.button(
        "선택한 추가매수 1건 되돌리기",
        key=f"{context}_revert_one_buy_transaction_button",
        disabled=not confirm,
        use_container_width=True,
    ):
        try:
            revert_buy_transaction(selected_tx_id)
        except ValueError as exc:
            st.error(str(exc))
            return
        clear_buy_transaction_cache()
        st.success("선택한 추가매수 1건을 되돌렸습니다.")
        st.rerun()


def load_recent_buy_transactions(limit: int = 5) -> list[dict]:
    transactions = normalize_buy_transactions(db.read_table("buy_transactions"))
    if transactions.empty:
        return []
    active = transactions[~transactions["되돌림여부"].map(is_truthy)].copy()
    if active.empty:
        return []
    active["_created_sort"] = pd.to_datetime(active["생성일시"], errors="coerce")
    active = active.sort_values(["_created_sort", "생성일시"], ascending=[False, False], kind="stable")
    recent = active.drop(columns=["_created_sort"], errors="ignore").head(limit)
    holdings = normalize_holdings(db.read_table("holdings"))
    return enrich_buy_transactions_with_holdings(recent, holdings).to_dict("records")


def enrich_buy_transactions_with_holdings(transactions: pd.DataFrame, holdings: pd.DataFrame) -> pd.DataFrame:
    output = normalize_buy_transactions(transactions)
    if output.empty:
        return output
    holdings = normalize_holdings(holdings)

    row_id_lookup = {}
    symbol_lookup = {}
    for _, holding in holdings.iterrows():
        row_id = str(holding.get("row_id", "") or "").strip()
        ticker = str(holding.get("티커 또는 종목코드", "") or "").strip().upper()
        if row_id:
            row_id_lookup[row_id] = holding
        if ticker and ticker not in symbol_lookup:
            symbol_lookup[ticker] = holding

    display_tickers = []
    display_names = []
    display_sources = []
    for _, tx in output.iterrows():
        raw_ticker = str(tx.get("티커", "") or "").strip().upper()
        raw_name = str(tx.get("종목명", "") or "").strip()
        batch_id = str(tx.get("일괄반영ID", "") or "").strip()
        asset_id = str(tx.get("자산ID", "") or "").strip()
        holding = None
        if asset_id:
            holding = row_id_lookup.get(asset_id)
        if holding is None and raw_ticker and not is_internal_batch_symbol(raw_ticker, batch_id):
            holding = symbol_lookup.get(raw_ticker)

        holding_ticker = str(holding.get("티커 또는 종목코드", "") or "").strip().upper() if holding is not None else ""
        holding_name = str(holding.get("종목명", "") or "").strip() if holding is not None else ""
        ticker = "" if is_internal_batch_symbol(raw_ticker, batch_id) else raw_ticker
        name = "" if is_internal_batch_symbol(raw_name, batch_id) else raw_name

        display_tickers.append(ticker or holding_ticker)
        display_names.append(name or holding_name)
        display_sources.append("holding" if (not ticker or not name) and holding is not None else "transaction")

    output["_display_ticker"] = display_tickers
    output["_display_asset_name"] = display_names
    output["_display_source"] = display_sources
    return output


def normalize_buy_transactions(df: pd.DataFrame | None) -> pd.DataFrame:
    output = df.copy() if df is not None else pd.DataFrame()
    for column in BUY_TRANSACTION_COLUMNS:
        if column not in output.columns:
            output[column] = False if column == "되돌림여부" else ""
    output = output[BUY_TRANSACTION_COLUMNS].copy()
    for column in ["수량", "단가", "금액"]:
        output[column] = output[column].map(parse_number)
    output["되돌림여부"] = output["되돌림여부"].map(is_truthy)
    return output


def is_truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "t", "yes", "y", "on", "되돌림", "완료"}


def format_buy_transaction_label(tx: dict) -> str:
    title, detail, created_at, internal_note = buy_transaction_display_parts(tx)
    lines = [title, detail, created_at]
    if internal_note:
        lines.append(internal_note)
    return "\n".join(line for line in lines if line)


def format_buy_transaction_confirmation(tx: dict) -> str:
    title, detail, _, internal_note = buy_transaction_display_parts(tx)
    lines = [title, detail]
    if internal_note:
        lines.append(internal_note)
    return "\n".join(line for line in lines if line)


def buy_transaction_display_parts(tx: dict) -> tuple[str, str, str, str]:
    ticker = str(tx.get("_display_ticker", "") or "").strip().upper()
    asset_name = str(tx.get("_display_asset_name", "") or "").strip()
    raw_ticker = str(tx.get("티커", "") or "").strip().upper()
    raw_name = str(tx.get("종목명", "") or "").strip()
    batch_id = str(tx.get("일괄반영ID", "") or "").strip()
    asset_id = str(tx.get("자산ID", "") or "").strip()
    if not ticker and not is_internal_batch_symbol(raw_ticker, batch_id):
        ticker = raw_ticker
    if not asset_name and not is_internal_batch_symbol(raw_name, batch_id):
        asset_name = raw_name

    if ticker and asset_name and ticker != asset_name:
        title = f"{ticker} · {asset_name}"
    elif ticker:
        title = ticker
    elif asset_name:
        title = asset_name
    else:
        title = f"종목 정보 없음 · 자산 ID {asset_id or '-'}"

    account = format_account_label(tx.get("계좌"))
    quantity = format_quantity_compact(tx.get("수량"))
    currency = str(tx.get("통화", "") or "").upper()
    unit_price = format_unit_price_for_revert(tx.get("단가"), currency)
    amount_value = parse_number(tx.get("금액")) or parse_number(tx.get("수량")) * parse_number(tx.get("단가"))
    amount = format_money_for_revert(amount_value, currency)
    created_at = format_datetime_for_display(tx.get("생성일시"))
    detail = f"{account} | {quantity}주 × {unit_price} = {amount}"
    internal_note = f"내부 batch: {batch_id}" if batch_id and (not ticker and not asset_name) else ""
    return title, detail, created_at, internal_note


def is_internal_batch_symbol(value: object, batch_id: str = "") -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if batch_id and text == str(batch_id).strip():
        return True
    return bool(re.fullmatch(r"BATCH[\w-]*", text, flags=re.IGNORECASE))


def format_account_label(value: object) -> str:
    account = str(value or "").strip()
    if not account:
        return "계좌 미지정"
    return account if account.endswith("계좌") else f"{account} 계좌"


def format_quantity_compact(value: object) -> str:
    quantity = parse_number(value)
    return f"{quantity:.8f}".rstrip("0").rstrip(".") or "0"


def format_money_for_revert(value: object, currency: str) -> str:
    amount = parse_number(value)
    if str(currency or "").upper() == "KRW":
        return f"{amount:,.0f} KRW"
    return f"{amount:,.2f} {str(currency or '').upper()}".strip()


def format_unit_price_for_revert(value: object, currency: str) -> str:
    unit_price = parse_number(value)
    if str(currency or "").upper() == "KRW":
        return f"{unit_price:,.0f} KRW"
    return f"{unit_price:,.4f} {str(currency or '').upper()}".strip()


def format_datetime_for_display(value: object) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value or "")
    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert(APP_TIMEZONE)
    return parsed.strftime("%Y-%m-%d %H:%M")


def apply_buy_transaction_card_style() -> None:
    st.markdown(
        """
        <style>
        div[role="radiogroup"] > label {
            border: 1px solid #d7dde5;
            border-radius: 8px;
            padding: 10px 12px;
            margin-bottom: 8px;
            background: #ffffff;
            white-space: pre-line;
        }
        div[role="radiogroup"] > label:has(input:checked) {
            border-color: #1a73e8;
            background: #eef5ff;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def revert_buy_transaction(transaction_id: str) -> None:
    transaction_id = str(transaction_id or "").strip()
    if not transaction_id:
        raise ValueError("되돌릴 거래 ID가 없습니다.")

    transactions = normalize_buy_transactions(db.read_table("buy_transactions"))
    matches = transactions["거래ID"].astype(str) == transaction_id
    if not matches.any():
        raise ValueError("선택한 추가매수 이력을 찾을 수 없습니다.")
    tx_idx = transactions[matches].index[0]
    tx = transactions.loc[tx_idx]
    if is_truthy(tx.get("되돌림여부")):
        raise ValueError("이미 되돌린 추가매수 이력입니다.")

    quantity = parse_number(tx.get("수량"))
    unit_price = parse_number(tx.get("단가"))
    if quantity <= 0:
        raise ValueError("되돌릴 수량이 0 이하입니다.")

    holdings = normalize_holdings(db.read_table("holdings"))
    asset_id = str(tx.get("자산ID", "") or "").strip()
    symbol = str(tx.get("티커", "") or "").strip().upper()
    if asset_id:
        holding_matches = holdings["row_id"].fillna("").astype(str) == asset_id
    else:
        holding_matches = holdings["티커 또는 종목코드"].fillna("").astype(str).str.upper() == symbol
    if not holding_matches.any() and symbol:
        holding_matches = holdings["티커 또는 종목코드"].fillna("").astype(str).str.upper() == symbol
    if not holding_matches.any():
        raise ValueError("되돌릴 자산을 찾을 수 없습니다.")

    holding_idx = holdings[holding_matches].index[0]
    account = str(tx.get("계좌", "새빛") or "새빛")
    target_col = "새빛_보유수량" if account == "새빛" else "희주_보유수량"
    account_quantity = parse_number(holdings.at[holding_idx, target_col])
    old_total_quantity = parse_number(holdings.at[holding_idx, "합산_보유수량"])
    old_avg_price = parse_number(holdings.at[holding_idx, "평균단가"])
    if account_quantity + 1e-12 < quantity or old_total_quantity + 1e-12 < quantity:
        raise ValueError("되돌리면 자산 수량이 음수가 되어 취소할 수 없습니다.")

    old_total_cost = old_total_quantity * old_avg_price
    new_account_quantity = max(0.0, account_quantity - quantity)
    new_total_quantity = max(0.0, old_total_quantity - quantity)
    new_total_cost = max(0.0, old_total_cost - (quantity * unit_price))
    new_avg_price = new_total_cost / new_total_quantity if new_total_quantity > 0 else 0.0

    updated_holdings = holdings.copy()
    updated_holdings.at[holding_idx, target_col] = new_account_quantity
    updated_holdings.at[holding_idx, "합산_보유수량"] = new_total_quantity
    updated_holdings.at[holding_idx, "보유수량"] = new_total_quantity
    updated_holdings.at[holding_idx, "평균단가"] = new_avg_price
    updated_holdings = prepare_holdings(updated_holdings)

    updated_transactions = transactions.copy()
    updated_transactions.at[tx_idx, "되돌림여부"] = True
    updated_transactions.at[tx_idx, "되돌림일시"] = datetime.now().isoformat(timespec="seconds")
    updated_transactions.at[tx_idx, "되돌림사유"] = "사용자 요청"

    db.backup_database("before_revert_buy_transaction")
    db.write_table("holdings", updated_holdings)
    db.write_table("buy_transactions", updated_transactions)


def clear_buy_transaction_cache() -> None:
    for key in ["buy_transactions", "revert_buy_transaction_radio", "confirm_revert_buy_transaction"]:
        st.session_state.pop(key, None)
    sync_after_holdings_mutation("transactions", "buy_transactions")


def buy_defaults_from_symbol(symbol: str, matched: pd.Series | None) -> tuple[str, str, str, str, SecurityLookupResult | None]:
    if matched is not None:
        asset_class = str(matched.get("자산군", "ETF") or "ETF")
        market = str(matched.get("시장", "US") or "US")
        currency = str(matched.get("통화", "USD") or "USD")
        name = str(matched.get("종목명", "") or "")
        return asset_class, market, currency, name, None

    normalized_symbol = normalize_symbol("US", symbol)
    asset_class = "ETF"
    market = "US"
    currency = infer_currency(market, asset_class, normalized_symbol)
    if not normalized_symbol:
        return asset_class, market, currency, "", None

    lookup_status = lookup_security_remote(market, normalized_symbol, asset_class)
    name = lookup_status.name if lookup_status.success else normalized_symbol
    return asset_class, market, currency, name, lookup_status


def make_transaction(row, account, asset_class, market, symbol, name, quantity, unit_price, currency, holdings, trade_type: str) -> dict:
    latest = holdings[holdings["티커 또는 종목코드"].astype(str).str.upper() == symbol].iloc[0]
    return {
        "거래일시": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "거래유형": trade_type,
        "계좌": account,
        "상위자산군": infer_major_asset_class(asset_class),
        "세부자산군": asset_class,
        "자산군": asset_class,
        "시장": market,
        "티커 또는 종목코드": symbol,
        "종목명": name,
        "매수수량": quantity,
        "매수단가": unit_price,
        "매수금액": quantity * unit_price,
        "통화": currency,
        "메모": str(row.get("메모", "") or ""),
        "반영 후 새빛_보유수량": latest["새빛_보유수량"],
        "반영 후 희주_보유수량": latest["희주_보유수량"],
        "반영 후 합산_보유수량": latest["합산_보유수량"],
        "반영 후 보유수량": latest["보유수량"],
        "반영 후 평균단가": latest["평균단가"],
    }


def raw_quantity_column(column: str) -> str:
    return f"{QUANTITY_RAW_PREFIX}{column}"


def prepare_holdings_editor_df(holdings: pd.DataFrame) -> pd.DataFrame:
    output = normalize_holdings(holdings).copy()
    for column in QUANTITY_COLUMNS:
        if column not in output.columns:
            continue
        raw_column = raw_quantity_column(column)
        output[raw_column] = output[column]
        output[column] = output.apply(
            lambda row, source_column=column: format_quantity_for_display(
                row.get(raw_quantity_column(source_column)),
                row.get("세부자산군", row.get("자산군", "")),
                row.get("시장", ""),
                row.get("티커 또는 종목코드", ""),
            ),
            axis=1,
        )
    return output


def materialize_holdings_editor_df(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    if output.empty:
        return output
    for idx, row in output.iterrows():
        for column in QUANTITY_COLUMNS:
            if column not in output.columns:
                continue
            raw_column = raw_quantity_column(column)
            raw_value = row.get(raw_column, row.get(column, 0))
            formatted_raw = format_quantity_for_display(
                raw_value,
                row.get("세부자산군", row.get("자산군", "")),
                row.get("시장", ""),
                row.get("티커 또는 종목코드", ""),
            )
            display_value = str(row.get(column, "") or "").strip()
            if display_value == formatted_raw and raw_column in output.columns:
                output.at[idx, column] = raw_value
            else:
                output.at[idx, column] = parse_number_from_display(display_value) or 0
    return output.drop(columns=[raw_quantity_column(column) for column in QUANTITY_COLUMNS], errors="ignore")


def autocomplete_holdings(df: pd.DataFrame, source_holdings: pd.DataFrame) -> pd.DataFrame:
    output = df.copy() if df is not None else pd.DataFrame()
    if output.empty:
        return output

    source = normalize_holdings(source_holdings)
    name_lookup = {
        normalize_symbol(row.get("시장", ""), row.get("티커 또는 종목코드", "")): str(row.get("종목명", "") or "")
        for _, row in source.iterrows()
        if str(row.get("티커 또는 종목코드", "") or "").strip()
    }

    for idx, row in output.iterrows():
        sub_asset_class = normalize_sub_asset_class(row.get("세부자산군", row.get("자산군", "")))
        market = infer_market(sub_asset_class, row.get("시장", ""))
        symbol = normalize_symbol(market, row.get("티커 또는 종목코드", ""))
        output.at[idx, "세부자산군"] = sub_asset_class
        output.at[idx, "자산군"] = sub_asset_class
        output.at[idx, "상위자산군"] = infer_major_asset_class(sub_asset_class)
        output.at[idx, "시장"] = market
        output.at[idx, "티커 또는 종목코드"] = symbol
        output.at[idx, "통화"] = infer_currency(market, sub_asset_class, symbol)
        current_name = str(row.get("종목명", "") or "").strip()
        if not current_name:
            output.at[idx, "종목명"] = resolve_security_name_fast(market, symbol, sub_asset_class, name_lookup)
        for column in ["새빛_보유수량", "희주_보유수량"]:
            raw_column = raw_quantity_column(column)
            raw_value = row.get(raw_column, row.get(column, 0))
            formatted_raw = format_quantity_for_display(raw_value, sub_asset_class, market, symbol)
            display_value = str(row.get(column, "") or "").strip()
            if display_value != formatted_raw:
                raw_value = parse_number_from_display(display_value) or 0
            output.at[idx, raw_column] = raw_value
            output.at[idx, column] = format_quantity_for_display(raw_value, sub_asset_class, market, symbol)
        saebit_quantity = parse_number(output.at[idx, raw_quantity_column("새빛_보유수량")])
        heeju_quantity = parse_number(output.at[idx, raw_quantity_column("희주_보유수량")])
        total_quantity = saebit_quantity + heeju_quantity
        output.at[idx, raw_quantity_column("합산_보유수량")] = total_quantity
        output.at[idx, raw_quantity_column("보유수량")] = total_quantity
        output.at[idx, "합산_보유수량"] = format_quantity_for_display(total_quantity, sub_asset_class, market, symbol)
        if "보유수량" in output.columns:
            output.at[idx, "보유수량"] = format_quantity_for_display(total_quantity, sub_asset_class, market, symbol)
    return output


def resolve_security_name_fast(market: str, symbol: str, sub_asset_class: str, name_lookup: dict[str, str] | None = None) -> str:
    normalized_market = str(market or "").strip().upper()
    normalized_symbol = normalize_symbol(normalized_market, symbol)
    if name_lookup and name_lookup.get(normalized_symbol):
        return name_lookup[normalized_symbol]
    cache_key = f"{normalized_market}:{normalized_symbol}"
    if cache_key in SYMBOL_NAME_CACHE:
        return SYMBOL_NAME_CACHE[cache_key]
    if str(sub_asset_class or "").strip() == "암호화폐" or normalized_market == "CRYPTO":
        return SYMBOL_NAME_CACHE.get(f"CRYPTO:{normalized_symbol}", normalized_symbol)
    return ""


def lookup_security_remote(market: str, symbol: str, sub_asset_class: str) -> SecurityLookupResult:
    result = lookup_security_remote_cached(market, symbol, sub_asset_class)
    return SecurityLookupResult(*result)


@st.cache_data(ttl=86400, show_spinner=False)
def lookup_security_remote_cached(market: str, symbol: str, sub_asset_class: str) -> tuple[str, str, str, bool, str, str]:
    normalized_market = str(market or "").strip().upper()
    normalized_symbol = normalize_symbol(normalized_market, symbol)
    if not normalized_symbol:
        return normalized_market, "", "", False, "input", "empty_symbol"
    fast = resolve_security_name_fast(normalized_market, normalized_symbol, sub_asset_class)
    if fast:
        return normalized_market, normalized_symbol, fast, True, "local_cache", ""
    try:
        result = lookup_security(normalized_market, normalized_symbol, sub_asset_class, sub_asset_class)
        return result.market, result.symbol, result.name, result.success, result.source, result.reason
    except Exception as exc:
        return normalized_market, normalized_symbol, "", False, "lookup_security", type(exc).__name__


@st.cache_data(ttl=86400, show_spinner=False)
def resolve_security_name_remote(market: str, symbol: str, sub_asset_class: str) -> str:
    result = lookup_security_remote(market, symbol, sub_asset_class)
    return result.name if result.name else result.symbol


def dataframes_equal(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    try:
        return left.reset_index(drop=True).fillna("").astype(str).equals(right.reset_index(drop=True).fillna("").astype(str))
    except Exception:
        return False


def build_dashboard_holdings_table(calculated: pd.DataFrame) -> pd.DataFrame:
    output = calculated.copy()
    if output.empty:
        return output

    output = apply_display_columns(output)
    value_column = "원화 환산 평가금액"
    output["평가금액_numeric"] = output[value_column].map(parse_number) if value_column in output.columns else 0.0
    output["평가손익_numeric"] = output["평가손익"].map(parse_number) if "평가손익" in output.columns else 0.0
    output["수익률_numeric"] = output.apply(calculate_display_return_rate, axis=1)
    total_value = float(output["평가금액_numeric"].sum()) if "평가금액_numeric" in output.columns else 0.0
    if total_value > 0:
        weight_numeric = output["평가금액_numeric"] / total_value * 100
    else:
        weight_numeric = pd.Series(0.0, index=output.index)
    output["전체_포트폴리오_내_비중_numeric"] = weight_numeric
    output["평가금액"] = output["평가금액_numeric"].map(lambda value: f"{value:,.0f}")
    output["평가손익"] = output["평가손익_numeric"].map(format_signed_integer)
    output["수익률"] = output["수익률_numeric"].map(format_return_pct)
    output["전체 포트폴리오 내 비중"] = weight_numeric.map(lambda value: f"{value:.2f}%")
    return output


def calculate_display_return_rate(row) -> float | None:
    if is_cash_asset(row):
        return None
    avg_price = parse_number(row.get("평균단가"))
    current_price = parse_number(row.get("현재가"))
    if avg_price <= 0 or current_price <= 0:
        return None
    return ((current_price - avg_price) / avg_price) * 100


def format_return_pct(value) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except Exception:
        return "-"
    if pd.isna(number):
        return "-"
    if number > 0:
        return f"+{number:.2f}%"
    return f"{number:.2f}%"


def format_signed_integer(value) -> str:
    number = parse_number(value)
    if number > 0:
        return f"+{number:,.0f}"
    if number < 0:
        return f"{number:,.0f}"
    return "0"


def render_colored_holdings_table(df: pd.DataFrame) -> None:
    columns = ["자산군", "시장", "티커 또는 종목코드", "종목명", "평가금액", "전체 포트폴리오 내 비중", "평가손익", "수익률"]
    visible_columns = [column for column in columns if column in df.columns]
    if df.empty or not visible_columns:
        st.info("표시할 보유 종목 데이터가 없습니다.")
        return

    header_cells = "".join(f"<th>{html.escape(column)}</th>" for column in visible_columns)
    body_rows = []
    for _, row in df.iterrows():
        asset_class = str(row.get("자산군", row.get("세부자산군", "")) or "")
        bg = ASSET_CLASS_TABLE_BG_COLORS.get(asset_class, "rgba(255, 255, 255, 1)")
        cells = []
        for column in visible_columns:
            value = "" if row.get(column) is None else str(row.get(column))
            style = ""
            if column == "평가손익":
                style = signed_value_style(row.get("평가손익_numeric"))
            elif column == "수익률":
                style = signed_value_style(row.get("수익률_numeric"))
            align = "right" if column in {"평가금액", "전체 포트폴리오 내 비중", "평가손익", "수익률"} else "left"
            cells.append(f"<td style='text-align:{align}; {style}'>{html.escape(value)}</td>")
        body_rows.append(f"<tr style='background:{bg};'>{''.join(cells)}</tr>")

    table_html = f"""
    <div class="mobile-holdings-table-wrap">
      <table class="mobile-holdings-table">
        <thead><tr>{header_cells}</tr></thead>
        <tbody>{''.join(body_rows)}</tbody>
      </table>
    </div>
    <style>
      .mobile-holdings-table-wrap {{
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        margin-top: 0.5rem;
      }}
      .mobile-holdings-table {{
        border-collapse: collapse;
        min-width: 760px;
        width: 100%;
        font-size: 13px;
      }}
      .mobile-holdings-table th {{
        background: #f4f6f8;
        color: #1f2937;
        font-weight: 700;
        border: 1px solid #d7dde5;
        padding: 8px 10px;
        white-space: nowrap;
      }}
      .mobile-holdings-table td {{
        border: 1px solid #d7dde5;
        padding: 7px 10px;
        color: #222;
        white-space: nowrap;
      }}
    </style>
    """
    st.markdown(table_html, unsafe_allow_html=True)


def signed_value_style(value) -> str:
    if value is None:
        return f"color:{NEUTRAL_COLOR};"
    number = parse_number(value)
    if number > 0:
        return f"color:{PROFIT_COLOR}; font-weight:700;"
    if number < 0:
        return f"color:{LOSS_COLOR}; font-weight:700;"
    return f"color:{NEUTRAL_COLOR};"


def apply_display_columns(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    if output.empty:
        return output
    for column in ["새빛_보유수량", "희주_보유수량", "합산_보유수량", "보유수량"]:
        if column in output.columns:
            output[f"{column}_표시"] = output.apply(
                lambda row, source_column=column: format_quantity_for_display(
                    row.get(source_column),
                    row.get("세부자산군", row.get("자산군", "")),
                    row.get("시장", ""),
                    row.get("티커 또는 종목코드", ""),
                ),
                axis=1,
            )
    if "평균단가" in output.columns:
        output["평균단가_표시"] = output.apply(
            lambda row: "" if is_cash_asset(row) else format_number_for_display(row.get("평균단가"), 2),
            axis=1,
        )
    return output


def is_cash_asset(row) -> bool:
    asset = str(row.get("세부자산군", row.get("자산군", "")) or "")
    market = str(row.get("시장", "") or "").upper()
    symbol = str(row.get("티커 또는 종목코드", "") or "").upper()
    return asset == "달러" or market == "FX" or symbol in {"USD", "USDKRW"}


def current_usdkrw(prices: pd.DataFrame) -> float:
    if prices.empty or "USD/KRW" not in prices.columns:
        return 1350.0
    value = pd.to_numeric(prices["USD/KRW"], errors="coerce").dropna()
    return float(value.iloc[-1]) if not value.empty else 1350.0


def format_number_for_display(value, decimals: int = 2, blank_if_none: bool = True) -> str:
    if value is None or value == "":
        return "" if blank_if_none else f"{0:,.{decimals}f}"
    try:
        number = float(str(value).replace(",", ""))
        return f"{number:,.{decimals}f}"
    except Exception:
        return str(value)


def parse_number_from_display(value):
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    text = text.replace(",", "").replace("원", "").replace("$", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def number_column_config() -> dict:
    return {
        "평가금액": st.column_config.NumberColumn("평가금액", format="%,.0f"),
        "원화 환산 평가금액": st.column_config.NumberColumn("원화 환산 평가금액", format="%,.0f"),
        "원화 환산 매입금액": st.column_config.NumberColumn("원화 환산 매입금액", format="%,.0f"),
        "평가손익": st.column_config.NumberColumn("평가손익", format="%,.0f"),
        "투자원금": st.column_config.NumberColumn("투자원금", format="%,.0f"),
        "현재가": st.column_config.NumberColumn("현재가", format="%,.2f"),
        "평균단가": st.column_config.NumberColumn("평균단가", format="%,.2f"),
        "매수단가": st.column_config.NumberColumn("매수단가", format="%,.2f"),
        "매수금액": st.column_config.NumberColumn("매수금액", format="%,.2f"),
        "보유수량": st.column_config.NumberColumn("보유수량", format="%,.8f"),
        "새빛_보유수량": st.column_config.NumberColumn("새빛_보유수량", format="%,.8f"),
        "희주_보유수량": st.column_config.NumberColumn("희주_보유수량", format="%,.8f"),
        "합산_보유수량": st.column_config.NumberColumn("합산_보유수량", format="%,.8f"),
        "매수수량": st.column_config.NumberColumn("매수수량", format="%,.8f"),
        "수익률": st.column_config.NumberColumn("수익률", format="%.2%"),
        "전체 포트폴리오 내 비중": st.column_config.NumberColumn("전체 포트폴리오 내 비중", format="%.2%"),
    }


def dashboard_holdings_column_config() -> dict:
    return {
        "평가금액": st.column_config.NumberColumn("평가금액", format="%,.0f"),
        "평가손익": st.column_config.NumberColumn("평가손익", format="%,.0f"),
        "수익률": st.column_config.NumberColumn("수익률", format="%.2%"),
        "전체 포트폴리오 내 비중": st.column_config.TextColumn("전체 포트폴리오 내 비중"),
    }


def render_performance_debug(settings_values: dict[str, str], perf: list[tuple[str, float]]) -> None:
    enabled = str(settings_values.get("성능 디버그 표시", "") or "").strip().lower() in {"1", "true", "yes", "y", "on", "표시", "켜기"}
    if not enabled:
        return
    with st.expander("성능 디버그"):
        for label, elapsed in perf:
            st.text(f"{label}: {elapsed:.2f}초")


def format_krw(value) -> str:
    return f"{parse_number(value):,.0f}원"


def calculate_this_year_return(snapshots: pd.DataFrame, current_value: float, cumulative_return: float = 0.0) -> float:
    current_year = datetime.now().year
    if current_year <= 2026:
        return cumulative_return
    if snapshots is None or snapshots.empty:
        return 0.0
    data = snapshots.copy()
    if "연도" not in data.columns or "총평가금액" not in data.columns:
        return 0.0
    data["연도"] = data["연도"].map(parse_number).astype(int)
    year_rows = data[data["연도"] == current_year].copy()
    if year_rows.empty:
        return 0.0
    if "날짜시간" in year_rows.columns:
        year_rows = year_rows.sort_values("날짜시간")
    start_value = parse_number(year_rows.iloc[0].get("총평가금액", 0))
    if start_value <= 0:
        return 0.0
    return (current_value - start_value) / start_value


def render_return_history_section(
    snapshots: pd.DataFrame,
    current_value: float,
    cumulative_return: float,
    settings_values: dict[str, str],
) -> None:
    if st.button("누적수익률 상세 보기", use_container_width=True):
        st.session_state["show_return_history"] = not st.session_state.get("show_return_history", False)
    if not st.session_state.get("show_return_history", False):
        return
    with st.spinner("연도별 수익률을 계산하는 중입니다."):
        history = build_return_history_table(snapshots, current_value, cumulative_return, settings_values)
    st.caption("※ 벤치마크 수익률은 배당금 15.4% 세금 차감 후 재투자하고 USD/KRW 환율을 반영한 원화 기준 Total Return입니다.")
    st.dataframe(history, use_container_width=True, hide_index=True)


def build_return_history_table(
    snapshots: pd.DataFrame,
    current_value: float,
    cumulative_return: float,
    settings_values: dict[str, str],
) -> pd.DataFrame:
    current_year = datetime.now().year
    years = list(range(2026, current_year + 1))
    portfolio_returns = annual_portfolio_returns(snapshots, current_value, cumulative_return, years)
    benchmark_returns = annual_benchmark_returns_cached(
        tuple(years),
        settings_values.get("주식 벤치마크 티커", "VT") or "VT",
        settings_values.get("채권 벤치마크 티커", "BND") or "BND",
        settings_values.get("금 벤치마크 티커", "GLD") or "GLD",
        parse_number(settings_values.get("주식 비중", "60")) / 100,
        parse_number(settings_values.get("채권 비중", "30")) / 100,
        parse_number(settings_values.get("금 비중", "10")) / 100,
        BENCHMARK_RETURN_METHOD,
        DIVIDEND_TAX_RATE,
    )
    rows = []
    cumulative_benchmark = 1.0
    has_benchmark = False
    for year in years:
        benchmark = benchmark_returns.get(year)
        if benchmark is not None:
            cumulative_benchmark *= 1 + benchmark
            has_benchmark = True
        rows.append(
            {
                "구분": str(year),
                "포트폴리오 수익률": format_percent(portfolio_returns.get(year)),
                "벤치마크 수익률": format_percent(benchmark) if benchmark is not None else "미조회",
            }
        )
    rows.append(
        {
            "구분": "누적",
            "포트폴리오 수익률": format_percent(cumulative_return),
            "벤치마크 수익률": format_percent(cumulative_benchmark - 1) if has_benchmark else "미조회",
        }
    )
    return pd.DataFrame(rows)


def annual_portfolio_returns(
    snapshots: pd.DataFrame,
    current_value: float,
    cumulative_return: float,
    years: list[int],
) -> dict[int, float]:
    returns: dict[int, float] = {}
    for year in years:
        if year <= 2026:
            returns[year] = cumulative_return
            continue
        returns[year] = calculate_year_return_from_snapshots(snapshots, year, current_value)
    return returns


def calculate_year_return_from_snapshots(snapshots: pd.DataFrame, year: int, current_value: float) -> float:
    if snapshots is None or snapshots.empty:
        return 0.0
    if "연도" not in snapshots.columns or "총평가금액" not in snapshots.columns:
        return 0.0
    data = snapshots.copy()
    data["연도"] = data["연도"].map(parse_number).astype(int)
    year_rows = data[data["연도"] == year].copy()
    if year_rows.empty:
        return 0.0
    if "날짜시간" in year_rows.columns:
        year_rows = year_rows.sort_values("날짜시간")
    start_value = parse_number(year_rows.iloc[0].get("총평가금액", 0))
    if start_value <= 0:
        return 0.0
    if year == datetime.now().year:
        end_value = current_value
    else:
        end_value = parse_number(year_rows.iloc[-1].get("총평가금액", 0))
    return (end_value - start_value) / start_value if end_value > 0 else 0.0


@st.cache_data(ttl=86400, show_spinner=False)
def annual_benchmark_returns_cached(
    years: tuple[int, ...],
    stock_symbol: str,
    bond_symbol: str,
    gold_symbol: str,
    stock_weight: float,
    bond_weight: float,
    gold_weight: float,
    return_method: str = BENCHMARK_RETURN_METHOD,
    dividend_tax_rate: float = DIVIDEND_TAX_RATE,
) -> dict[int, float | None]:
    returns: dict[int, float | None] = {}
    for year in years:
        value, _ = fetch_benchmark_after_tax_total_return(
            stock_symbol,
            bond_symbol,
            gold_symbol,
            stock_weight,
            bond_weight,
            gold_weight,
            year=year,
        )
        returns[year] = value
    return returns


def build_dashboard_benchmark_contributions(capital_flows: pd.DataFrame) -> list[tuple[pd.Timestamp, float]]:
    flows = normalize_capital_flows(capital_flows).copy()
    flows["_date"] = pd.to_datetime(flows["일시"], errors="coerce").dt.normalize()
    cutoff_flows = flows[flows["_date"] <= BENCHMARK_SYNTHETIC_CUTOFF].copy()
    cutoff_principal = current_invested_principal(cutoff_flows)
    synthetic_total = BENCHMARK_SYNTHETIC_MONTHLY_AMOUNT * 7
    initial_principal = cutoff_principal - synthetic_total
    if initial_principal < 0:
        raise ValueError("2026년 7월 10일 기준 원금이 가정 추가입금 합계보다 작습니다.")

    contributions: list[tuple[pd.Timestamp, float]] = [(pd.Timestamp("2025-12-31"), initial_principal)]
    contributions.extend(
        (pd.Timestamp(year=2026, month=month, day=1), BENCHMARK_SYNTHETIC_MONTHLY_AMOUNT)
        for month in range(1, 8)
    )
    actual_later = flows[
        (flows["_date"] > BENCHMARK_SYNTHETIC_CUTOFF)
        & flows["유형"].isin({"추가입금", "추가매수연동"})
    ]
    contributions.extend(
        (row["_date"], parse_number(row["금액"]))
        for _, row in actual_later.iterrows()
        if parse_number(row["금액"]) > 0
    )
    return contributions


def fetch_dashboard_benchmark(
    settings_values: dict[str, str], capital_flows: pd.DataFrame
) -> tuple[float | None, str | None]:
    try:
        stock_symbol = settings_values.get("주식 벤치마크 티커", "VT") or "VT"
        bond_symbol = settings_values.get("채권 벤치마크 티커", "BND") or "BND"
        gold_symbol = settings_values.get("금 벤치마크 티커", "GLD") or "GLD"
        stock_weight = parse_number(settings_values.get("주식 비중", "60")) / 100
        bond_weight = parse_number(settings_values.get("채권 비중", "30")) / 100
        gold_weight = parse_number(settings_values.get("금 비중", "10")) / 100
        contributions = build_dashboard_benchmark_contributions(capital_flows)
        return fetch_benchmark_after_tax_total_return(
            stock_symbol,
            bond_symbol,
            gold_symbol,
            stock_weight,
            bond_weight,
            gold_weight,
            capital_contributions=contributions,
        )
    except Exception as exc:
        return None, f"벤치마크 조회 실패: {exc}"


def benchmark_label(settings_values: dict[str, str]) -> str:
    stock_symbol = settings_values.get("주식 벤치마크 티커", "VT") or "VT"
    bond_symbol = settings_values.get("채권 벤치마크 티커", "BND") or "BND"
    gold_symbol = settings_values.get("금 벤치마크 티커", "GLD") or "GLD"
    stock_weight = parse_number(settings_values.get("주식 비중", "60"))
    bond_weight = parse_number(settings_values.get("채권 비중", "30"))
    gold_weight = parse_number(settings_values.get("금 비중", "10"))
    return f"{stock_symbol} {stock_weight:.0f}% / {bond_symbol} {bond_weight:.0f}% / {gold_symbol} {gold_weight:.0f}%"


def import_report_frame(report: dict[str, dict[str, object]]) -> pd.DataFrame:
    rows = []
    for table_name, values in report.items():
        rows.append(
            {
                "테이블": table_name,
                "가져온 건수": values.get("imported", 0),
                "상태": values.get("status", ""),
            }
        )
    return pd.DataFrame(rows)


def mask_secret(value: str) -> str:
    if not value:
        return "미설정"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def apply_mobile_style() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 0.5rem; padding-bottom: 5rem; max-width: 980px; }
        h1 a, h2 a, h3 a, h4 a, h5 a, h6 a,
        a.anchor-link {
            display: none !important;
            visibility: hidden !important;
        }
        div[data-testid="stMetric"] {
            border: 1px solid #d7dde5;
            border-radius: 8px;
            padding: 14px 16px;
            background: #ffffff;
        }
        div.stButton > button, div.stDownloadButton > button {
            min-height: 46px;
            font-weight: 700;
        }
        div[data-baseweb="select"] { min-height: 44px; }
        .app-card {
            border: 1px solid #d7dde5;
            border-radius: 8px;
            background: #ffffff;
            padding: 10px 12px;
            margin: 6px 0;
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
        }
        .principal-value {
            font-size: 1.45rem;
            line-height: 1.2;
            color: #111827;
            font-weight: 850;
        }
        div[role="radiogroup"] {
            gap: 4px;
        }
        div[role="radiogroup"] label {
            min-height: 42px;
            border: 1px solid #d7dde5;
            border-radius: 8px;
            padding: 7px 9px;
            background: #fff;
            justify-content: center;
        }
        .mobile-holdings-table-wrap {
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
            margin-top: 0.5rem;
        }
        .mobile-holdings-table {
            border-collapse: collapse;
            width: 100%;
            min-width: 560px;
            font-size: 12px;
        }
        .mobile-holdings-table th {
            background: #f4f6f8;
            color: #1f2937;
            font-weight: 700;
            border: 1px solid #d7dde5;
            padding: 7px 8px;
            white-space: nowrap;
        }
        .mobile-holdings-table td {
            border: 1px solid #d7dde5;
            padding: 7px 8px;
            color: #222;
            white-space: nowrap;
        }
        .mobile-bottom-spacer { height: 2px; }
        @media (max-width: 700px) {
            .block-container { padding-left: 0.75rem; padding-right: 0.75rem; }
            h1 { font-size: 1.35rem; margin-bottom: 0.25rem; }
            h2, h3 { font-size: 1.05rem; }
            div[data-testid="stDataFrame"] { font-size: 0.82rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        st.error("앱 실행 중 오류가 발생했습니다.")
        st.info("아래 진단 내용을 확인해 원인을 수정할 수 있습니다.")
        st.code(traceback.format_exc(), language="python")
