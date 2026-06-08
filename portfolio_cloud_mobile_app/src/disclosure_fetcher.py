from __future__ import annotations

import io
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests


SEC_DEFAULT_USER_AGENT = "Personal Portfolio Disclosure Tracker contact@example.com"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache"
DART_CORP_CODE_CACHE = CACHE_DIR / "dart_corp_codes.csv"
SEC_TICKER_CACHE = CACHE_DIR / "sec_company_tickers.csv"


def sec_headers(user_agent: str = "") -> dict[str, str]:
    return {"User-Agent": user_agent or SEC_DEFAULT_USER_AGENT, "Accept-Encoding": "gzip, deflate"}


def fetch_sec_ticker_cik_map(user_agent: str = "") -> dict[str, str]:
    if SEC_TICKER_CACHE.exists():
        cached = pd.read_csv(SEC_TICKER_CACHE, dtype=str).fillna("")
        return dict(zip(cached["ticker"].str.upper(), cached["cik"].str.zfill(10)))
    response = requests.get(SEC_TICKERS_URL, headers=sec_headers(user_agent), timeout=15)
    response.raise_for_status()
    data = response.json()
    mapping: dict[str, str] = {}
    rows = []
    for item in data.values():
        ticker = str(item.get("ticker", "")).upper()
        cik = str(item.get("cik_str", "")).zfill(10)
        if ticker and cik:
            mapping[ticker] = cik
            rows.append({"ticker": ticker, "cik": cik})
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(SEC_TICKER_CACHE, index=False, encoding="utf-8-sig")
    return mapping


def test_sec_connection(user_agent: str = "") -> tuple[bool, str]:
    if "@" not in str(user_agent or ""):
        return False, "SEC User-Agent에 이메일이 포함되어 있지 않습니다."
    try:
        mapping = fetch_sec_ticker_cik_map(user_agent)
        cik = mapping.get("AAPL")
        if not cik:
            return False, "SEC ticker-CIK 매핑에서 AAPL을 찾지 못했습니다."
        response = requests.get(SEC_SUBMISSIONS_URL.format(cik=cik), headers=sec_headers(user_agent), timeout=15)
        response.raise_for_status()
        return True, f"성공. User-Agent: {user_agent}"
    except Exception as exc:
        return False, f"SEC 요청에 실패했습니다. User-Agent 또는 네트워크 상태를 확인해주세요. ({exc})"


def ticker_to_cik(ticker: str, user_agent: str = "") -> str:
    mapping = fetch_sec_ticker_cik_map(user_agent)
    return mapping.get(str(ticker or "").upper(), "")


def fetch_sec_filings(ticker: str, since_date: str, user_agent: str = "") -> list[dict]:
    normalized_ticker = str(ticker or "").upper().strip()
    cik = ticker_to_cik(normalized_ticker, user_agent)
    if not cik:
        raise ValueError(f"{normalized_ticker} CIK를 찾지 못했습니다.")

    response = requests.get(SEC_SUBMISSIONS_URL.format(cik=cik), headers=sec_headers(user_agent), timeout=20)
    response.raise_for_status()
    recent = response.json().get("filings", {}).get("recent", {})
    since = pd.to_datetime(since_date).date()
    rows: list[dict] = []
    forms = recent.get("form", [])
    accession_numbers = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    primary_docs = recent.get("primaryDocument", [])
    descriptions = recent.get("primaryDocDescription", [])
    for form, accession, filing_date, primary_doc, description in zip(forms, accession_numbers, filing_dates, primary_docs, descriptions):
        if pd.to_datetime(filing_date).date() < since:
            continue
        accession_clean = str(accession).replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_clean}/{primary_doc}" if primary_doc else ""
        title = str(description or form or "").strip() or f"{normalized_ticker} {form}"
        rows.append(
            {
                "시장": "US",
                "티커_또는_종목코드": normalized_ticker,
                "공시일": filing_date,
                "공시유형": str(form),
                "공시제목": title,
                "공시원문URL": url,
                "공시ID": str(accession),
            }
        )
    return rows


def normalize_kr_stock_code(stock_code: str) -> str:
    clean = str(stock_code or "").strip().upper()
    return clean.zfill(6) if clean.isdigit() else clean


def load_dart_corp_code_map(api_key: str, force_refresh: bool = False) -> pd.DataFrame:
    if not force_refresh and DART_CORP_CODE_CACHE.exists():
        return pd.read_csv(DART_CORP_CODE_CACHE, dtype=str).fillna("")
    response = requests.get(DART_CORP_CODE_URL, params={"crtfc_key": api_key}, timeout=30)
    response.raise_for_status()
    if response.headers.get("content-type", "").lower().startswith("application/json"):
        data = response.json()
        raise ValueError(f"{data.get('status')} {data.get('message')}")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        xml_bytes = archive.read("CORPCODE.xml")
    frame = pd.read_xml(io.BytesIO(xml_bytes), xpath=".//list")
    if frame.empty:
        return pd.DataFrame(columns=["corp_code", "corp_name", "stock_code", "modify_date"])
    for column in ["corp_code", "corp_name", "stock_code", "modify_date"]:
        if column not in frame.columns:
            frame[column] = ""
    frame["stock_code"] = frame["stock_code"].fillna("").astype(str).str.strip().str.upper().map(normalize_kr_stock_code)
    frame["corp_code"] = frame["corp_code"].fillna("").astype(str).str.strip().str.replace(r"\.0$", "", regex=True).str.zfill(8)
    frame["corp_name"] = frame["corp_name"].fillna("").astype(str).str.strip()
    frame = frame[["corp_code", "corp_name", "stock_code", "modify_date"]]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(DART_CORP_CODE_CACHE, index=False, encoding="utf-8-sig")
    return frame


def fetch_dart_corp_code_map(api_key: str) -> dict[str, str]:
    frame = load_dart_corp_code_map(api_key)
    listed = frame[frame["stock_code"].astype(str).str.strip() != ""]
    return dict(zip(listed["stock_code"], listed["corp_code"]))


def get_dart_corp_code_by_stock_code(stock_code: str, corp_map: pd.DataFrame) -> str:
    normalized = normalize_kr_stock_code(stock_code)
    matches = corp_map[corp_map["stock_code"].astype(str).str.upper() == normalized]
    return str(matches.iloc[0]["corp_code"]).zfill(8) if not matches.empty else ""


def search_dart_companies(query: str, api_key: str, limit: int = 20) -> pd.DataFrame:
    corp_map = load_dart_corp_code_map(api_key)
    text = str(query or "").strip().upper()
    if not text:
        return corp_map.head(0)
    if text.isdigit() or any(ch.isdigit() for ch in text):
        normalized = normalize_kr_stock_code(text)
        matches = corp_map[corp_map["stock_code"].astype(str).str.upper() == normalized]
    else:
        matches = corp_map[corp_map["corp_name"].astype(str).str.contains(str(query).strip(), case=False, na=False)]
    return matches.head(limit).reset_index(drop=True)


def test_dart_api_key(api_key: str) -> tuple[bool, str]:
    if not str(api_key or "").strip():
        return False, "키가 입력되지 않았습니다."
    try:
        mapping = load_dart_corp_code_map(api_key, force_refresh=True)
        listed_count = int((mapping["stock_code"].astype(str).str.strip() != "").sum()) if not mapping.empty else 0
        if listed_count:
            return True, f"성공. corp_code 매핑 {len(mapping):,}건 로드 완료, 상장 stock_code {listed_count:,}건"
        return False, "corp_code 매핑을 내려받았지만 상장 종목코드가 없습니다."
    except Exception as exc:
        return False, f"OpenDART API Key가 유효하지 않거나 요청이 실패했습니다. ({exc})"


def stock_code_to_corp_code(stock_code: str, api_key: str) -> str:
    corp_map = load_dart_corp_code_map(api_key)
    return get_dart_corp_code_by_stock_code(stock_code, corp_map)


def fetch_dart_filings(stock_code: str, since_date: str, api_key: str, max_count: int = 30) -> list[dict]:
    normalized_code = normalize_kr_stock_code(stock_code)
    corp_map = load_dart_corp_code_map(api_key)
    corp_code = get_dart_corp_code_by_stock_code(normalized_code, corp_map)
    if not corp_code:
        raise ValueError(f"{normalized_code} DART corp_code를 찾지 못했습니다.")
    corp_name = ""
    matches = corp_map[corp_map["corp_code"].astype(str) == corp_code]
    if not matches.empty:
        corp_name = str(matches.iloc[0].get("corp_name", ""))
    since = pd.to_datetime(since_date).strftime("%Y%m%d")
    today = datetime.now().strftime("%Y%m%d")
    response = requests.get(
        DART_LIST_URL,
        params={"crtfc_key": api_key, "corp_code": corp_code, "bgn_de": since, "end_de": today, "page_count": 100, "sort": "date", "sort_mth": "desc"},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("status") not in {"000", "013"}:
        raise ValueError(data.get("message", "DART 조회 실패"))
    rows: list[dict] = []
    for item in (data.get("list", []) or [])[:max_count]:
        rcept_no = str(item.get("rcept_no", ""))
        report_nm = str(item.get("report_nm", ""))
        rows.append(
            {
                "시장": "KR",
                "티커_또는_종목코드": normalized_code,
                "공시일": str(item.get("rcept_dt", "")),
                "공시유형": infer_dart_form_type(report_nm),
                "공시제목": report_nm,
                "공시원문URL": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
                "공시ID": rcept_no,
                "corp_code": corp_code,
                "corp_name": corp_name,
            }
        )
    return rows


def dart_filings_test(stock_code_or_name: str, api_key: str, since_date: str) -> tuple[bool, str, pd.DataFrame]:
    try:
        candidates = search_dart_companies(stock_code_or_name, api_key, limit=5)
        if candidates.empty:
            return False, f"{stock_code_or_name}에 해당하는 DART 회사를 찾지 못했습니다.", pd.DataFrame()
        row = candidates.iloc[0]
        stock_code = str(row.get("stock_code", ""))
        corp_code = str(row.get("corp_code", ""))
        corp_name = str(row.get("corp_name", ""))
        filings = fetch_dart_filings(stock_code, since_date, api_key, max_count=30)
        frame = pd.DataFrame(filings)
        return True, f"corp_code: {corp_code}, stock_code: {stock_code}, corp_name: {corp_name}, 최근 3개월 공시: {len(frame)}건", frame
    except Exception as exc:
        return False, str(exc), pd.DataFrame()


def infer_dart_form_type(title: str) -> str:
    for keyword in ["사업보고서", "반기보고서", "분기보고서", "주요사항보고서"]:
        if keyword in str(title):
            return keyword
    return "기타"
