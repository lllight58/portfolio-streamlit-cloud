from __future__ import annotations

import re

import pandas as pd


def parse_number(value) -> float:
    """
    콤마, 원, $, 공백 등이 포함된 값을 계산 가능한 숫자로 변환한다.
    """
    if value is None:
        return 0.0
    try:
        if pd.isna(value):
            return 0.0
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return 0.0
    cleaned = re.sub(r"[,\s$원%]", "", text)
    cleaned = cleaned.replace("KRW", "").replace("USD", "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def infer_currency(market: str, asset_class: str = "", symbol: str = "") -> str:
    """
    시장, 자산군, 티커/종목코드를 기준으로 통화를 자동 추론한다.
    """
    normalized_market = str(market or "").strip().upper()
    if normalized_market == "US":
        return "USD"
    if normalized_market == "KR":
        return "KRW"
    if normalized_market == "CRYPTO":
        return "USD"
    if normalized_market == "FX":
        return "USD"
    return "KRW"


def format_quantity(value) -> str:
    text = f"{parse_number(value):,.8f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _strip_trailing_zeros(text: str) -> str:
    if "." not in text:
        return text
    return text.rstrip("0").rstrip(".")


def format_quantity_for_display(value, sub_asset_class=None, market=None, symbol=None) -> str:
    """
    보유수량 화면 표시 전용 함수. DB 저장 원본값은 변경하지 않는다.
    """
    if value is None or value == "":
        return ""
    try:
        number = float(str(value).replace(",", ""))
    except Exception:
        return str(value)

    symbol_text = str(symbol or "").strip().upper()
    sub = str(sub_asset_class or "").strip()
    market_text = str(market or "").strip().upper()
    is_crypto = sub == "암호화폐" or market_text == "CRYPTO" or symbol_text in {"BTC", "ETH", "BTC-USD", "ETH-USD"}

    if is_crypto:
        text = _strip_trailing_zeros(f"{number:,.8f}")
        return text if text else "0"
    if float(number).is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}"


def format_quantity_display(value) -> str:
    """
    표 표시용 보유수량. 기본적으로 소수점 둘째 자리까지 표시한다.
    """
    return format_quantity_for_display(value)


def format_quantity_detail(value) -> str:
    """
    상세 수정/정밀 확인용 보유수량. 최대 소수점 여덟째 자리까지 표시한다.
    """
    return format_quantity(value)


def format_price(value, currency: str) -> str:
    normalized_currency = str(currency or "").upper()
    if normalized_currency == "KRW":
        return f"{parse_number(value):,.0f}원"
    return f"${parse_number(value):,.2f}"


def format_money(value, currency: str) -> str:
    return format_price(value, currency)


def format_percent(value) -> str:
    number = parse_number(value)
    if abs(number) > 1:
        number = number / 100
    return f"{number:+.2%}"


def format_weight(value) -> str:
    number = parse_number(value)
    if abs(number) > 1:
        number = number / 100
    return f"{number:.2%}"
