from __future__ import annotations

from datetime import datetime

import pandas as pd
from dateutil.relativedelta import relativedelta

import json

from src.disclosure_fetcher import fetch_dart_filings, fetch_sec_filings
from src.disclosure_summarizer import classify_disclosure_importance, summarize_disclosure
from src.excel_manager import (
    DISCLOSURE_COLUMNS,
    DISCLOSURE_LOG_COLUMNS,
    DISCLOSURE_WATCHLIST_COLUMNS,
    normalize_disclosure_logs,
    normalize_disclosure_watchlist,
    normalize_disclosures,
    normalize_settings,
    settings_to_dict,
)
from src.portfolio_calculator import normalize_holdings


def normalize_market(value: str) -> str:
    text = str(value or "").strip().upper()
    if text in {"US", "미국"}:
        return "US"
    if text in {"KR", "한국", "KOREA"}:
        return "KR"
    return text


def normalize_tracking_symbol(market: str, symbol: str) -> str:
    clean = str(symbol or "").strip()
    if normalize_market(market) == "US":
        return clean.upper()
    return clean.upper()


def individual_stock_holdings(holdings: pd.DataFrame) -> pd.DataFrame:
    normalized = normalize_holdings(holdings)
    quantity = normalized["합산_보유수량"] if "합산_보유수량" in normalized.columns else normalized["보유수량"]
    mask = ((normalized["세부자산군"] == "개별주") | (normalized["자산군"] == "개별주")) & (pd.to_numeric(quantity, errors="coerce").fillna(0) > 0)
    result = normalized.loc[mask].copy().reset_index(drop=True)
    result["시장"] = result["시장"].map(normalize_market)
    result["티커 또는 종목코드"] = result.apply(lambda row: normalize_tracking_symbol(row["시장"], row["티커 또는 종목코드"]), axis=1)
    return result


def first_refresh_required(settings: pd.DataFrame, disclosures: pd.DataFrame, force_first: bool = False) -> bool:
    if force_first:
        return True
    existing = normalize_disclosures(disclosures)
    values = settings_to_dict(settings)
    completed = str(values.get("disclosure_first_refresh_completed", "")).strip().lower() == "true"
    last_refresh = str(values.get("last_disclosure_refresh_datetime", "") or "").strip()
    parsed = pd.to_datetime(last_refresh, errors="coerce") if last_refresh else pd.NaT
    return existing.empty or not completed or not last_refresh or pd.isna(parsed)


def disclosure_since_date(settings: pd.DataFrame, disclosures: pd.DataFrame | None = None, mode: str = "auto") -> tuple[str, bool, str]:
    settings = normalize_settings(settings)
    disclosures = normalize_disclosures(disclosures)
    if mode in {"force_3m", "force_first"}:
        return (datetime.now() - relativedelta(months=3)).strftime("%Y-%m-%d"), True, "최근3개월강제조회" if mode == "force_3m" else "최초조회"
    if first_refresh_required(settings, disclosures):
        return (datetime.now() - relativedelta(months=3)).strftime("%Y-%m-%d"), True, "최초조회"
    values = settings_to_dict(settings)
    last_refresh = pd.to_datetime(values.get("last_disclosure_refresh_datetime", ""), errors="coerce")
    return last_refresh.strftime("%Y-%m-%d"), False, "증분조회"


def disclosure_key(market: str, symbol: str) -> str:
    return f"{normalize_market(market)}|{normalize_tracking_symbol(market, symbol)}"


def build_disclosure_universe(holdings: pd.DataFrame, watchlist: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    normalized_holdings = normalize_holdings(holdings)
    watchlist = normalize_disclosure_watchlist(watchlist)
    status_map = {
        disclosure_key(row["시장"], row["티커_또는_종목코드"]): str(row.get("추적상태", "추적중"))
        for _, row in watchlist.iterrows()
    }

    targets: list[dict] = []
    excluded: list[dict] = []
    for _, row in normalized_holdings.iterrows():
        market = normalize_market(row.get("시장", ""))
        symbol = normalize_tracking_symbol(market, row.get("티커 또는 종목코드", ""))
        key = disclosure_key(market, symbol)
        quantity = float(row.get("합산_보유수량", row.get("보유수량", 0)) or 0)
        is_stock = row.get("세부자산군") == "개별주" or row.get("자산군") == "개별주"
        base = {
            "시장": market,
            "티커_또는_종목코드": symbol,
            "종목명": str(row.get("종목명", "") or symbol),
        }
        if status_map.get(key) == "제외":
            excluded.append({**base, "사유": "관심 제외 종목"})
        elif not is_stock:
            excluded.append({**base, "사유": f"{row.get('세부자산군', row.get('자산군', ''))}라서 제외"})
        elif quantity <= 0:
            excluded.append({**base, "사유": "보유수량 0"})
        else:
            targets.append({**base, "포함이유": "보유 중인 개별주"})

    holding_keys = {disclosure_key(row["시장"], row["티커_또는_종목코드"]) for row in targets + excluded}
    for _, row in watchlist.iterrows():
        market = normalize_market(row.get("시장", ""))
        symbol = normalize_tracking_symbol(market, row.get("티커_또는_종목코드", ""))
        key = disclosure_key(market, symbol)
        base = {"시장": market, "티커_또는_종목코드": symbol, "종목명": str(row.get("종목명", "") or symbol)}
        if str(row.get("추적상태", "")) == "제외":
            if key not in holding_keys:
                excluded.append({**base, "사유": "관심 제외 종목"})
            continue
        if key not in {disclosure_key(item["시장"], item["티커_또는_종목코드"]) for item in targets}:
            targets.append({**base, "포함이유": "관심 종목으로 추가됨"})

    return pd.DataFrame(targets), pd.DataFrame(excluded)


def refresh_disclosures(
    holdings: pd.DataFrame,
    existing_disclosures: pd.DataFrame,
    settings: pd.DataFrame,
    watchlist: pd.DataFrame | None = None,
    existing_logs: pd.DataFrame | None = None,
    mode: str = "auto",
    market_scope: str = "ALL",
    selected_keys: list[str] | None = None,
    progress_callback=None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict, list[str], int]:
    settings = normalize_settings(settings)
    existing = normalize_disclosures(existing_disclosures)
    watchlist = normalize_disclosure_watchlist(watchlist)
    logs = normalize_disclosure_logs(existing_logs)
    values = settings_to_dict(settings)
    since_date, is_first_refresh, mode_label = disclosure_since_date(settings, existing, mode)
    today = datetime.now().strftime("%Y-%m-%d")
    dart_api_key = values.get("dart_api_key", "")
    sec_user_agent = values.get("sec_user_agent", "")
    summary_model = values.get("summary_model", "gpt-4o-mini")
    max_count = int(float(values.get("종목당 최대 공시 조회 건수", "30") or 30))
    targets, excluded = build_disclosure_universe(holdings, watchlist)
    if market_scope == "KR":
        targets = targets[targets["시장"] == "KR"].reset_index(drop=True)
        mode_label = f"{mode_label}-한국종목"
    elif market_scope == "US":
        targets = targets[targets["시장"] == "US"].reset_index(drop=True)
        mode_label = f"{mode_label}-미국종목"
    elif market_scope == "SELECTED" and selected_keys:
        selected_set = set(selected_keys)
        targets = targets[targets.apply(lambda row: disclosure_key(row["시장"], row["티커_또는_종목코드"]) in selected_set, axis=1)].reset_index(drop=True)
        mode_label = f"{mode_label}-선택종목"

    messages: list[str] = []
    new_rows: list[dict] = []
    per_symbol: list[dict] = []
    success_count = 0
    failure_count = 0
    fetched_count = 0
    detail_logs: list[dict] = []
    if targets.empty:
        messages.append("공시 조회 대상 종목이 없습니다. 보유자산 중 자산군이 '개별주'인 종목이 없거나, 모든 개별주가 관심 제외 상태입니다.")

    for pos, (_, target) in enumerate(targets.iterrows(), start=1):
        market = normalize_market(target["시장"])
        symbol = normalize_tracking_symbol(market, target["티커_또는_종목코드"])
        name = str(target.get("종목명", "") or symbol)
        error = ""
        filings: list[dict] = []
        if progress_callback:
            progress_callback(pos, len(targets), name)
        try:
            if market == "US":
                filings = fetch_sec_filings(symbol, since_date, sec_user_agent)
            elif market == "KR":
                if not dart_api_key:
                    raise ValueError("DART API Key가 없어 한국 개별주 공시 조회를 건너뛰었습니다.")
                filings = fetch_dart_filings(symbol, since_date, dart_api_key, max_count=max_count)
            else:
                raise ValueError(f"지원하지 않는 시장: {market}")
            success_count += 1
        except Exception as exc:
            failure_count += 1
            error = str(exc)
            messages.append(f"{symbol}: {error}")

        fetched_count += len(filings)
        per_symbol.append({"시장": market, "티커_또는_종목코드": symbol, "종목명": name, "조회결과건수": len(filings), "오류": error})
        detail_logs.append({"symbol": symbol, "name": name, "market": market, "status": "failed" if error else "success", "fetched": len(filings), "error": error})
        for filing in filings:
            form_type = str(filing.get("공시유형", ""))
            title = str(filing.get("공시제목", ""))
            filing_date = str(filing.get("공시일", ""))
            url = str(filing.get("공시원문URL", ""))
            new_rows.append(
                {
                    "저장일시": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "시장": market,
                    "티커_또는_종목코드": symbol,
                    "종목명": name,
                    "공시일": filing_date,
                    "공시유형": form_type,
                    "공시제목": title,
                    "공시원문URL": url,
                    "공시ID": str(filing.get("공시ID", "")),
                    "요약": summarize_disclosure(market, form_type, title, filing_date, url, "", summary_model),
                    "중요도": classify_disclosure_importance(market, form_type, title),
                    "처리상태": "신규",
                }
            )

    refreshed = existing if not new_rows else pd.concat([existing, pd.DataFrame(new_rows)], ignore_index=True)
    refreshed = deduplicate_disclosures(refreshed)
    new_count = max(len(refreshed) - len(existing), 0)
    duplicate_count = max(len(new_rows) - new_count, 0)
    completed_query = not targets.empty and success_count > 0
    if completed_query:
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        settings.loc[settings["설정"] == "last_disclosure_refresh_datetime", "값"] = now_text
        settings.loc[settings["설정"] == "disclosure_first_refresh_completed", "값"] = "True"
    if new_count == 0 and completed_query:
        messages.append(f"신규 공시가 없습니다. 조회 대상 {len(targets)}개 종목을 확인했고, 조회 기간 내 신규 공시가 없습니다.")

    diagnostic = {
        "조회대상종목수": len(targets),
        "조회대상": targets,
        "제외종목": excluded,
        "조회시작일": since_date,
        "조회종료일": today,
        "최초새로고침여부": is_first_refresh,
        "조회모드": mode_label,
        "마지막새로고침시각": values.get("last_disclosure_refresh_datetime", ""),
        "종목별결과": pd.DataFrame(per_symbol),
    }
    log_row = pd.DataFrame(
        [
            [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                mode_label,
                since_date,
                today,
                len(targets),
                ", ".join([f"{row['시장']}:{row['티커_또는_종목코드']}" for _, row in targets.iterrows()]),
                success_count,
                failure_count,
                fetched_count,
                new_count,
                duplicate_count,
                len(refreshed),
                "\n".join(messages),
                json.dumps(detail_logs, ensure_ascii=False),
            ]
        ],
        columns=DISCLOSURE_LOG_COLUMNS,
    )
    logs = pd.concat([logs, log_row], ignore_index=True)
    return refreshed[DISCLOSURE_COLUMNS], settings, logs, diagnostic, messages, new_count


def deduplicate_disclosures(disclosures: pd.DataFrame) -> pd.DataFrame:
    normalized = normalize_disclosures(disclosures)
    normalized["_dedupe_key"] = normalized.apply(_dedupe_key, axis=1)
    return normalized.drop_duplicates("_dedupe_key", keep="first").drop(columns=["_dedupe_key"]).reset_index(drop=True)


def _dedupe_key(row: pd.Series) -> str:
    disclosure_id = str(row.get("공시ID", "") or "").strip()
    if disclosure_id:
        return "|".join([str(row.get("시장", "")), str(row.get("티커_또는_종목코드", "")), disclosure_id])
    return "|".join(
        [
            str(row.get("시장", "")),
            str(row.get("티커_또는_종목코드", "")),
            str(row.get("공시일", "")),
            str(row.get("공시유형", "")),
            str(row.get("공시제목", "")),
        ]
    )
