from __future__ import annotations

import re

import pandas as pd
import requests
import yfinance as yf


KR_NAME_OVERRIDES = {
    "0060H0": "TIGER 토탈월드스탁액티브",
    "329200": "TIGER 리츠부동산인프라",
}

CRYPTO_NAME_MAP = {
    "BTC": "Bitcoin",
    "BITCOIN": "Bitcoin",
    "ETH": "Ethereum",
    "ETHEREUM": "Ethereum",
    "SOL": "Solana",
    "XRP": "XRP",
    "ADA": "Cardano",
    "DOGE": "Dogecoin",
}

CRYPTO_COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
}

FX_NAMES = {
    "USD": "미국 달러 현금",
    "USDKRW": "미국 달러 현금",
    "KRW=X": "미국 달러 현금",
    "EUR": "유로 현금",
    "EURKRW": "유로 현금",
    "JPY": "일본 엔 현금",
    "JPYKRW": "일본 엔 현금",
}


def normalize_symbol(market: str, symbol: str) -> str:
    clean = re.sub(r"\s+", "", str(symbol or "")).upper()
    if str(market or "").upper() == "CRYPTO":
        return normalize_crypto_symbol(clean)
    if str(market or "").upper() == "FX":
        if clean == "USD":
            return "USDKRW"
    return clean


def normalize_crypto_symbol(symbol: str) -> str:
    """
    암호화폐 심볼을 표준 저장/조회 기준 심볼로 정규화한다.
    """
    clean = re.sub(r"\s+", "", str(symbol or "")).upper()
    if clean.endswith("-USD"):
        clean = clean[:-4]
    aliases = {
        "BITCOIN": "BTC",
        "ETHEREUM": "ETH",
    }
    return aliases.get(clean, clean)


def crypto_yfinance_symbol(symbol: str) -> str:
    normalized = normalize_crypto_symbol(symbol)
    return f"{normalized}-USD" if normalized else ""


def is_crypto_route(market: str, asset_class: str | None = None, sub_asset_class: str | None = None) -> bool:
    return (
        str(sub_asset_class or "").strip() == "암호화폐"
        or str(asset_class or "").strip() == "암호화폐"
        or str(market or "").upper() == "CRYPTO"
    )


def get_security_name(market: str, symbol: str, asset_class: str | None = None, sub_asset_class: str | None = None) -> str:
    if is_crypto_route(market, asset_class, sub_asset_class):
        normalized = normalize_crypto_symbol(symbol)
        return get_crypto_security_name(normalized) if normalized else ""
    normalized = normalize_symbol(market, symbol)
    market = str(market or "").upper()
    if not normalized:
        return ""
    if market == "US":
        return get_us_security_name(normalized)
    if market == "KR":
        return get_kr_security_name(normalized)
    if market == "CRYPTO":
        return get_crypto_security_name(normalized)
    if market == "FX":
        return get_fx_security_name(normalized)
    return normalized


def get_us_security_name(symbol: str) -> str:
    normalized = normalize_symbol("US", symbol)
    try:
        ticker = yf.Ticker(normalized)
        info = ticker.get_info() or {}
        for key in ("longName", "shortName"):
            value = info.get(key)
            if value:
                return str(value)
        quote_type = info.get("quoteType")
        if quote_type:
            return f"{normalized} {quote_type}"
    except Exception:
        pass
    return normalized


def get_kr_security_name(symbol: str) -> str:
    normalized = normalize_symbol("KR", symbol)
    if normalized in KR_NAME_OVERRIDES:
        return KR_NAME_OVERRIDES[normalized]

    name = _get_kr_name_from_naver(normalized)
    if name:
        return name

    return normalized


def get_crypto_security_name(symbol: str) -> str:
    normalized = normalize_crypto_symbol(symbol)
    if normalized in CRYPTO_NAME_MAP:
        return CRYPTO_NAME_MAP[normalized]

    coin_id = CRYPTO_COINGECKO_IDS.get(normalized)
    if not coin_id:
        coin_id = normalized.lower()
    try:
        response = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "ids": coin_id},
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
        if data and data[0].get("name"):
            return str(data[0]["name"])
    except Exception:
        pass
    return normalized


def get_fx_security_name(symbol: str) -> str:
    normalized = normalize_symbol("FX", symbol)
    return FX_NAMES.get(normalized, normalized)


def _get_kr_name_from_fdr(symbol: str) -> str:
    try:
        import FinanceDataReader as fdr

        markets = ["KRX", "KOSPI", "KOSDAQ", "ETF"]
        frames = []
        for market in markets:
            try:
                frames.append(fdr.StockListing(market))
            except Exception:
                continue
        if not frames:
            return ""
        listings = pd.concat(frames, ignore_index=True)
        code_column = _first_existing_column(listings, ["Code", "Symbol", "종목코드"])
        name_column = _first_existing_column(listings, ["Name", "종목명", "NameEng"])
        if not code_column or not name_column:
            return ""
        codes = listings[code_column].fillna("").astype(str).str.strip().str.upper()
        matches = listings.loc[codes == symbol]
        if not matches.empty:
            return str(matches.iloc[0][name_column]).strip()
    except Exception:
        pass
    return ""


def _get_kr_name_from_pykrx(symbol: str) -> str:
    try:
        from pykrx import stock

        for market in ["KOSPI", "KOSDAQ", "KONEX", "ALL"]:
            try:
                tickers = stock.get_market_ticker_list(market=market)
                if symbol in {str(ticker).upper() for ticker in tickers}:
                    name = stock.get_market_ticker_name(symbol)
                    if name:
                        return str(name)
            except Exception:
                continue
    except Exception:
        pass
    return ""


def _get_kr_name_from_naver(symbol: str) -> str:
    try:
        response = requests.get(
            "https://finance.naver.com/item/main.naver",
            params={"code": symbol},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        response.raise_for_status()
        match = re.search(r"<title>\s*([^<:]+)\s*:", response.text)
        if match:
            return match.group(1).strip()
    except Exception:
        pass

    try:
        response = requests.get(
            "https://m.stock.naver.com/api/stock/search",
            params={"keyword": symbol},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
        items = data.get("result", {}).get("d", []) if isinstance(data, dict) else []
        for item in items:
            item_code = str(item.get("cd") or item.get("symbolCode") or "").upper()
            if item_code == symbol:
                name = item.get("nm") or item.get("stockName")
                if name:
                    return str(name)
    except Exception:
        pass
    return ""


def _first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    return ""
