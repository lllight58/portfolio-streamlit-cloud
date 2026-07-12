from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

from src.formatters import infer_currency
from src.symbol_resolver import crypto_yfinance_symbol, is_crypto_route, normalize_symbol

APP_TIMEZONE = ZoneInfo("Asia/Seoul")
DIVIDEND_TAX_RATE = 0.154
BENCHMARK_RETURN_METHOD = "after_tax_total_return_krw_v2"


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


def fetch_benchmark_after_tax_total_return(
    stock_symbol: str = "VT",
    bond_symbol: str = "BND",
    gold_symbol: str = "GLD",
    stock_weight: float = 0.6,
    bond_weight: float = 0.3,
    gold_weight: float = 0.1,
    year: int | None = None,
) -> tuple[float | None, str | None]:
    """
    벤치마크 수익률을 배당금 15.4% 세금 차감 후 재투자하고 USD/KRW 환율을
    반영한 원화 기준 Total Return으로 계산한다.

    Yahoo Finance의 Adj Close는 세전 배당 재투자 효과가 섞여 있으므로 사용하지 않는다.
    history(auto_adjust=False, actions=True)의 Close와 Dividends를 이용해 각 구성 ETF의
    일별 세후 total return을 먼저 만든 뒤 일별 수익률을 가중합한다.
    """
    try:
        symbols = {
            normalize_symbol("US", stock_symbol): float(stock_weight or 0),
            normalize_symbol("US", bond_symbol): float(bond_weight or 0),
            normalize_symbol("US", gold_symbol): float(gold_weight or 0),
        }
        symbols = {symbol: weight for symbol, weight in symbols.items() if symbol and weight > 0}
        if not symbols:
            return None, "벤치마크 비중 또는 티커가 비어 있습니다."

        target_year = year or datetime.now(APP_TIMEZONE).year
        start, end = benchmark_history_window(target_year, year is None)
        daily_returns_by_ticker: dict[str, pd.Series] = {}
        missing: list[str] = []

        for symbol in symbols:
            history = fetch_benchmark_price_history(symbol, start, end)
            if history.empty:
                missing.append(symbol)
                continue
            tr_df = build_after_tax_total_return_index(history)
            returns = tr_df["after_tax_total_return"].dropna()
            if returns.empty:
                missing.append(symbol)
                continue
            daily_returns_by_ticker[symbol] = returns

        if not daily_returns_by_ticker:
            return None, f"{', '.join(symbols.keys())} 가격/배당 데이터를 가져오지 못했습니다."

        benchmark = build_weighted_benchmark_after_tax_tr(daily_returns_by_ticker, symbols)
        fx_history = fetch_usdkrw_history(start, end)
        benchmark = build_krw_adjusted_benchmark_tr(
            benchmark["benchmark_after_tax_tr_index"],
            fx_history,
        )
        if benchmark.empty:
            return None, f"{target_year}년 USD/KRW 환율 데이터를 가져오지 못했습니다."
        value = calculate_calendar_year_return_from_index(
            benchmark["benchmark_after_tax_tr_krw_index"],
            target_year,
        )
        if value is None:
            return None, f"{target_year}년 벤치마크 원화 기준 세후 Total Return 데이터를 계산할 수 없습니다."
        if missing:
            return value, f"일부 벤치마크 데이터 누락: {', '.join(missing)}"
        return value, None
    except Exception as exc:
        return None, f"벤치마크 원화 기준 세후 Total Return 조회 실패: {exc}"


def benchmark_history_window(target_year: int, is_ytd: bool) -> tuple[datetime, datetime]:
    start = datetime(target_year - 1, 12, 15)
    if is_ytd:
        end = datetime.now(APP_TIMEZONE).replace(tzinfo=None) + timedelta(days=1)
    else:
        end = datetime(target_year + 1, 1, 10)
    return start, end


def fetch_benchmark_price_history(symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    ticker = yf.Ticker(normalize_symbol("US", symbol))
    history = ticker.history(
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval="1d",
        auto_adjust=False,
        actions=True,
    )
    return history if history is not None else pd.DataFrame()


def fetch_usdkrw_history(start: datetime, end: datetime) -> pd.Series:
    history = yf.Ticker("KRW=X").history(
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval="1d",
        auto_adjust=False,
    )
    if history is None or history.empty or "Close" not in history.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(history["Close"], errors="coerce").dropna()


def build_after_tax_total_return_index(
    price_df: pd.DataFrame,
    dividend_col: str = "Dividends",
    dividend_tax_rate: float = DIVIDEND_TAX_RATE,
) -> pd.DataFrame:
    """Close와 Dividends로 일별 세후 total return index를 만든다."""
    if price_df is None or price_df.empty:
        return pd.DataFrame(columns=["after_tax_total_return", "after_tax_tr_index"])

    df = price_df.copy().sort_index()
    if "Close" not in df.columns:
        raise ValueError("Close column is required")
    if dividend_col not in df.columns:
        df[dividend_col] = 0.0

    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    df[dividend_col] = pd.to_numeric(df[dividend_col], errors="coerce").fillna(0.0)
    df = df.dropna(subset=["Close"])
    df = df[df["Close"] > 0].copy()
    if df.empty:
        return pd.DataFrame(columns=["after_tax_total_return", "after_tax_tr_index"])

    df["prev_close"] = df["Close"].shift(1)
    df["after_tax_dividend"] = df[dividend_col] * (1 - dividend_tax_rate)
    df["after_tax_total_return"] = (df["Close"] + df["after_tax_dividend"]) / df["prev_close"] - 1
    df.loc[df["prev_close"].isna() | (df["prev_close"] <= 0), "after_tax_total_return"] = 0.0
    df["after_tax_total_return"] = df["after_tax_total_return"].replace([float("inf"), float("-inf")], 0.0).fillna(0.0)
    df["after_tax_tr_index"] = (1 + df["after_tax_total_return"]).cumprod()
    return df


def build_weighted_benchmark_after_tax_tr(
    daily_returns_by_ticker: dict[str, pd.Series],
    weights: dict[str, float],
) -> pd.DataFrame:
    returns_df = pd.DataFrame(daily_returns_by_ticker).sort_index()
    if returns_df.empty:
        return pd.DataFrame(columns=["benchmark_after_tax_daily_return", "benchmark_after_tax_tr_index"])
    returns_df = returns_df.fillna(0.0)

    usable_weights = {ticker: float(weights.get(ticker, 0)) for ticker in returns_df.columns}
    weight_sum = sum(weight for weight in usable_weights.values() if weight > 0)
    if weight_sum <= 0:
        raise ValueError("벤치마크 비중 합계가 0입니다.")

    benchmark_daily_return = pd.Series(0.0, index=returns_df.index)
    for ticker, weight in usable_weights.items():
        if weight > 0:
            benchmark_daily_return += returns_df[ticker] * (weight / weight_sum)

    return pd.DataFrame(
        {
            "benchmark_after_tax_daily_return": benchmark_daily_return,
            "benchmark_after_tax_tr_index": (1 + benchmark_daily_return).cumprod(),
        }
    )


def build_krw_adjusted_benchmark_tr(benchmark_tr_index: pd.Series, usdkrw: pd.Series) -> pd.DataFrame:
    benchmark_tr_index = normalize_tr_index(benchmark_tr_index)
    usdkrw = normalize_tr_index(usdkrw)
    if benchmark_tr_index.empty or usdkrw.empty:
        return pd.DataFrame(
            columns=[
                "benchmark_after_tax_tr_index",
                "usdkrw",
                "benchmark_after_tax_tr_krw_index",
            ]
        )

    df = pd.concat(
        [
            benchmark_tr_index.rename("benchmark_after_tax_tr_index"),
            usdkrw.rename("usdkrw"),
        ],
        axis=1,
    ).sort_index()
    df[["benchmark_after_tax_tr_index", "usdkrw"]] = df[["benchmark_after_tax_tr_index", "usdkrw"]].ffill()
    df = df.dropna(subset=["benchmark_after_tax_tr_index", "usdkrw"])
    df = df[df["usdkrw"] > 0].copy()
    if df.empty:
        return pd.DataFrame(
            columns=[
                "benchmark_after_tax_tr_index",
                "usdkrw",
                "benchmark_after_tax_tr_krw_index",
            ]
        )
    df["benchmark_after_tax_tr_krw_index"] = df["benchmark_after_tax_tr_index"] * df["usdkrw"]
    return df


def calculate_ytd_return(tr_index: pd.Series) -> float | None:
    current_year = datetime.now(APP_TIMEZONE).year
    return calculate_calendar_year_return_from_index(tr_index, current_year)


def calculate_calendar_year_returns(tr_index: pd.Series) -> dict[int, float]:
    tr_index = normalize_tr_index(tr_index)
    if tr_index.empty:
        return {}

    years = sorted({int(value) for value in tr_index.index.year})
    result: dict[int, float] = {}
    for year in years:
        value = calculate_calendar_year_return_from_index(tr_index, year)
        if value is not None:
            result[year] = value
    return result


def calculate_calendar_year_return_from_index(tr_index: pd.Series, year: int) -> float | None:
    tr_index = normalize_tr_index(tr_index)
    if tr_index.empty:
        return None

    end_candidates = tr_index[tr_index.index.year == int(year)]
    if end_candidates.empty:
        return None

    prior_candidates = tr_index[tr_index.index < pd.Timestamp(year=int(year), month=1, day=1, tz=tr_index.index.tz)]
    if prior_candidates.empty:
        start_value = float(end_candidates.iloc[0])
    else:
        start_value = float(prior_candidates.iloc[-1])
    end_value = float(end_candidates.iloc[-1])
    if start_value <= 0:
        return None
    return end_value / start_value - 1


def normalize_tr_index(tr_index: pd.Series) -> pd.Series:
    if tr_index is None or tr_index.empty:
        return pd.Series(dtype=float)
    series = pd.to_numeric(tr_index.copy(), errors="coerce").dropna().sort_index()
    if not isinstance(series.index, pd.DatetimeIndex):
        series.index = pd.to_datetime(series.index, errors="coerce")
        series = series[~series.index.isna()]
    if isinstance(series.index, pd.DatetimeIndex) and series.index.tz is not None:
        series.index = series.index.tz_convert(None)
    return series


def fetch_benchmark_return(
    stock_symbol: str = "VT",
    bond_symbol: str = "BND",
    gold_symbol: str = "GLD",
    stock_weight: float = 0.6,
    bond_weight: float = 0.3,
    gold_weight: float = 0.1,
    year: int | None = None,
) -> tuple[float | None, str | None]:
    """호환용 wrapper. 실제 계산 기준은 원화 기준 세후 배당 재투자 Total Return이다."""
    return fetch_benchmark_after_tax_total_return(
        stock_symbol,
        bond_symbol,
        gold_symbol,
        stock_weight,
        bond_weight,
        gold_weight,
        year=year,
    )


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
