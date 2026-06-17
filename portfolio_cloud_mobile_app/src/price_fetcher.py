from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

from src.formatters import infer_currency
from src.symbol_resolver import crypto_yfinance_symbol, is_crypto_route, normalize_symbol

APP_TIMEZONE = ZoneInfo("Asia/Seoul")


def now_text() -> str:
    return datetime.now(APP_TIMEZONE).isoformat(timespec="seconds")


def fetch_all_prices(holdings: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """보유자산 목록을 기준으로 가격과 USD/KRW 환율을 조회합니다."""
    errors: list[str] = []
    updated_at = now_text()
    usdkrw, fx_error = fetch_usdkrw()
    if fx_error:
        errors.append(fx_error)
        usdkrw = 1350.0

    rows = []
    for _, holding in holdings.iterrows():
        market = str(holding.get("시장", "")).upper()
        symbol = normalize_symbol(market, holding.get("티커 또는 종목코드", ""))
        asset_class = str(holding.get("자산군", ""))
        sub_asset_class = str(holding.get("세부자산군", asset_class))
        currency = infer_currency(market, asset_class, symbol)

        price = None
        status = "정상"

        if not symbol:
            errors.append("티커 또는 종목코드가 비어 있는 행이 있습니다.")
            status = "필수 입력값 누락"
        else:
            try:
                if asset_class == "달러" or market == "FX":
                    price = usdkrw
                    currency = "USD"
                elif is_crypto_route(market, asset_class, sub_asset_class):
                    price = fetch_crypto_price(symbol)
                    currency = "USD"
                elif market == "US":
                    price = fetch_us_price(symbol)
                elif market == "KR":
                    price = fetch_kr_price(symbol)
                else:
                    status = "지원하지 않는 시장"
                    errors.append(f"{symbol} 가격 조회에 실패했습니다. 시장 값을 확인해주세요.")
            except Exception as exc:
                status = "조회 실패"
                errors.append(_friendly_error(symbol, market, exc))

        if price is None:
            status = "가격 데이터 없음" if status == "정상" else status
            if market == "KR":
                errors.append(f"{symbol} 종목은 가격 조회에 실패했지만 포트폴리오에는 저장되었습니다.")
            else:
                errors.append(f"{symbol} 가격 데이터가 없습니다. 티커 또는 종목코드를 확인해주세요.")

        rows.append(
            {
                "티커 또는 종목코드": symbol,
                "현재가": price,
                "통화": currency,
                "USD/KRW": usdkrw,
                "마지막 가격 업데이트 시각": updated_at,
                "상태": status,
            }
        )

    return pd.DataFrame(rows), errors


def fetch_us_price(symbol: str) -> float:
    symbol = normalize_symbol("US", symbol)
    ticker = yf.Ticker(symbol)
    fast_info = getattr(ticker, "fast_info", {}) or {}
    price = fast_info.get("last_price") or fast_info.get("regular_market_price")
    if price:
        return float(price)

    history = ticker.history(period="5d", interval="1d")
    if history.empty:
        raise ValueError("가격 데이터 없음")
    return float(history["Close"].dropna().iloc[-1])


def fetch_us_ytd_return(symbol: str, year: int | None = None) -> float:
    symbol = normalize_symbol("US", symbol)
    target_year = year or datetime.now().year
    start = datetime(target_year, 1, 1)
    end = datetime.now() + timedelta(days=1) if target_year == datetime.now().year else datetime(target_year + 1, 1, 1)
    history = yf.Ticker(symbol).history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"), interval="1d")
    closes = history["Close"].dropna() if not history.empty and "Close" in history.columns else pd.Series(dtype=float)
    if closes.empty:
        raise ValueError(f"{symbol} 가격 데이터 없음")
    start_price = float(closes.iloc[0])
    end_price = float(closes.iloc[-1])
    if start_price <= 0:
        raise ValueError(f"{symbol} 연초 기준가 오류")
    return (end_price - start_price) / start_price


def fetch_benchmark_return(
    stock_symbol: str = "VT",
    bond_symbol: str = "BND",
    gold_symbol: str = "GLD",
    stock_weight: float = 0.6,
    bond_weight: float = 0.3,
    gold_weight: float = 0.1,
    year: int | None = None,
) -> tuple[float | None, str | None]:
    try:
        stock_return = fetch_us_ytd_return(stock_symbol, year)
        bond_return = fetch_us_ytd_return(bond_symbol, year)
        gold_return = fetch_us_ytd_return(gold_symbol, year)
        return stock_return * stock_weight + bond_return * bond_weight + gold_return * gold_weight, None
    except Exception:
        return None, f"{stock_symbol}, {bond_symbol}, {gold_symbol} 가격 데이터를 가져오지 못했습니다."


def fetch_kr_price(code: str) -> float:
    clean_code = normalize_symbol("KR", code)
    if not clean_code:
        raise ValueError("국내 종목코드가 비어 있습니다.")

    try:
        import FinanceDataReader as fdr

        history = fdr.DataReader(clean_code)
        if not history.empty:
            return float(history["Close"].dropna().iloc[-1])
    except Exception:
        pass

    try:
        from pykrx import stock

        end = datetime.now().strftime("%Y%m%d")
        history = stock.get_market_ohlcv_by_date("20200101", end, clean_code)
        if not history.empty:
            return float(history["종가"].dropna().iloc[-1])
    except Exception:
        pass

    try:
        price = fetch_kr_price_from_naver(clean_code)
        if price:
            return float(price)
    except Exception:
        pass

    raise ValueError("국내 가격 데이터 없음")


def fetch_kr_price_from_naver(code: str) -> float:
    response = requests.get(
        "https://polling.finance.naver.com/api/realtime/domestic/stock",
        params={"queryCodes": f"ITEM{code}"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    areas = data.get("result", {}).get("areas", [])
    for area in areas:
        for item in area.get("datas", []):
            if str(item.get("cd", "")).upper() == code:
                price = item.get("nv") or item.get("closePrice")
                if price is not None:
                    return float(str(price).replace(",", ""))
    raise ValueError("네이버금융 가격 데이터 없음")


def fetch_crypto_price(symbol: str) -> float:
    normalized = normalize_symbol("CRYPTO", symbol)
    lookup_symbol = crypto_yfinance_symbol(normalized)

    try:
        return fetch_us_price(lookup_symbol)
    except Exception:
        coin_ids = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
            "XRP": "ripple",
            "ADA": "cardano",
            "DOGE": "dogecoin",
        }
        coin_id = coin_ids.get(normalized, normalized.lower())
        response = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin_id, "vs_currencies": "usd"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        return float(data[coin_id]["usd"])


def fetch_usdkrw() -> tuple[float | None, str | None]:
    try:
        price = fetch_us_price("KRW=X")
        if price > 0:
            return float(price), None
    except Exception:
        pass

    try:
        response = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10)
        response.raise_for_status()
        data = response.json()
        rate = float(data["rates"]["KRW"])
        return rate, None
    except Exception:
        return None, "USD/KRW 환율 조회에 실패했습니다. 인터넷 연결을 확인해주세요."


def _friendly_error(symbol: str, market: str, exc: Exception) -> str:
    message = str(exc)
    if market == "KR":
        return f"{symbol} 가격 조회에 실패했습니다. 국내 알파뉴메릭 ETF 코드 지원 여부를 확인해주세요. ({message})"
    if market == "US":
        return f"{symbol} 가격 조회에 실패했습니다. 티커가 올바른지 확인해주세요. ({message})"
    if market == "CRYPTO":
        return f"{symbol} 가격 조회에 실패했습니다. 암호화폐 심볼이 올바른지 확인해주세요. ({message})"
    return f"{symbol} 가격 조회에 실패했습니다. 입력값을 확인해주세요. ({message})"
