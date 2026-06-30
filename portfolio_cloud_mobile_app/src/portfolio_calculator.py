from __future__ import annotations

import numpy as np
import pandas as pd
from uuid import uuid4

from src.formatters import infer_currency, parse_number
from src.symbol_resolver import get_crypto_security_name, is_crypto_route, normalize_symbol


MAJOR_ASSET_CLASSES = ["주식", "채권", "대체자산", "현금"]
ASSET_CLASSES = ["ETF", "개별주", "미국채권", "국내채권", "한국리츠", "암호화폐", "달러"]
SUB_ASSET_CLASSES = ASSET_CLASSES
SUB_TO_MAJOR_ASSET_CLASS = {
    "ETF": "주식",
    "개별주": "주식",
    "주식": "주식",
    "미국채권": "채권",
    "국내채권": "채권",
    "한국리츠": "대체자산",
    "암호화폐": "대체자산",
    "달러": "현금",
}
MARKETS = ["US", "KR", "CRYPTO", "FX"]
CURRENCIES = ["KRW", "USD"]

HOLDINGS_COLUMNS = [
    "표시순서",
    "sort_order",
    "row_id",
    "상위자산군",
    "세부자산군",
    "자산군",
    "시장",
    "티커 또는 종목코드",
    "종목명",
    "새빛_보유수량",
    "희주_보유수량",
    "합산_보유수량",
    "보유수량",
    "평균단가",
    "통화",
    "메모",
]

PRICE_COLUMNS = [
    "티커 또는 종목코드",
    "현재가",
    "통화",
    "USD/KRW",
    "마지막 가격 업데이트 시각",
    "상태",
]

CAPITAL_FLOW_COLUMNS = ["일시", "유형", "금액", "통화", "메모", "반영 후 투자원금"]
CAPITAL_FLOW_TYPES = ["초기원금", "추가입금", "원금출금", "원금수정", "추가매수연동"]
SNAPSHOT_COLUMNS = ["날짜시간", "연도", "스냅샷유형", "총평가금액", "투자원금", "평가손익", "누적수익률", "메모"]


def sample_holdings() -> pd.DataFrame:
    return pd.DataFrame(
        [
            [1, 1, _new_row_id(), "주식", "ETF", "ETF", "US", "VT", "Vanguard Total World Stock ETF", 10, 0, 10, 10, 100, "USD", ""],
            [2, 2, _new_row_id(), "채권", "미국채권", "미국채권", "US", "BND", "Vanguard Total Bond Market ETF", 5, 0, 5, 5, 72, "USD", ""],
            [3, 3, _new_row_id(), "대체자산", "한국리츠", "한국리츠", "KR", "329200", "TIGER 리츠부동산인프라", 100, 0, 100, 100, 4500, "KRW", ""],
            [4, 4, _new_row_id(), "대체자산", "암호화폐", "암호화폐", "CRYPTO", "BTC", "Bitcoin", 0.01, 0, 0.01, 0.01, 50000, "USD", ""],
            [5, 5, _new_row_id(), "현금", "달러", "달러", "FX", "USDKRW", "미국 달러 현금", 1000, 0, 1000, 1000, 1, "USD", ""],
        ],
        columns=HOLDINGS_COLUMNS,
    )


def empty_prices() -> pd.DataFrame:
    return pd.DataFrame(columns=PRICE_COLUMNS)


def empty_transactions() -> pd.DataFrame:
    return pd.DataFrame(columns=TRANSACTION_COLUMNS)


def empty_capital_flows() -> pd.DataFrame:
    return pd.DataFrame(columns=CAPITAL_FLOW_COLUMNS)


def empty_snapshots() -> pd.DataFrame:
    return pd.DataFrame(columns=SNAPSHOT_COLUMNS)


TRANSACTION_COLUMNS = [
    "거래일시",
    "거래유형",
    "계좌",
    "상위자산군",
    "세부자산군",
    "자산군",
    "시장",
    "티커 또는 종목코드",
    "종목명",
    "매수수량",
    "매수단가",
    "매수금액",
    "통화",
    "메모",
    "반영 후 새빛_보유수량",
    "반영 후 희주_보유수량",
    "반영 후 합산_보유수량",
    "반영 후 보유수량",
    "반영 후 평균단가",
]


def infer_major_asset_class(sub_asset_class: str) -> str:
    return SUB_TO_MAJOR_ASSET_CLASS.get(str(sub_asset_class or "").strip(), "")


def _new_row_id() -> str:
    return str(uuid4())


def normalize_sub_asset_class(asset_class: str) -> str:
    asset_class = str(asset_class or "").strip()
    if asset_class == "주식":
        return "ETF"
    if asset_class == "비트코인":
        return "암호화폐"
    return asset_class


def infer_market(asset_class: str, market: str = "") -> str:
    asset_class = normalize_sub_asset_class(asset_class)
    normalized_market = str(market or "").strip().upper()
    if asset_class == "암호화폐":
        return "CRYPTO"
    if asset_class == "달러":
        return "FX"
    if asset_class == "미국채권":
        return "US"
    if asset_class in {"국내채권", "한국리츠"}:
        return "KR"
    return normalized_market or "US"


def normalize_holdings(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return sample_holdings()

    normalized = df.copy()
    if "sort_order" not in normalized.columns and "표시순서" in normalized.columns:
        normalized["sort_order"] = normalized["표시순서"]
    if "표시순서" not in normalized.columns and "sort_order" in normalized.columns:
        normalized["표시순서"] = normalized["sort_order"]
    if "새빛_보유수량" not in normalized.columns:
        normalized["새빛_보유수량"] = normalized["보유수량"] if "보유수량" in normalized.columns else 0
    if "희주_보유수량" not in normalized.columns:
        normalized["희주_보유수량"] = 0
    if "자산군" in normalized.columns:
        asset_values = normalized["자산군"].fillna("").astype(str).str.strip()
        valid_asset_values = asset_values.map(normalize_sub_asset_class).isin(ASSET_CLASSES + ["주식"])
    else:
        asset_values = pd.Series("", index=normalized.index)
        valid_asset_values = pd.Series(False, index=normalized.index)
    if "세부자산군" not in normalized.columns:
        normalized["세부자산군"] = asset_values
    else:
        normalized["세부자산군"] = normalized["세부자산군"].where(~valid_asset_values, asset_values)
    normalized["세부자산군"] = normalized["세부자산군"].map(normalize_sub_asset_class)
    normalized["자산군"] = normalized["세부자산군"]
    normalized["상위자산군"] = normalized["세부자산군"].map(infer_major_asset_class)
    for column in HOLDINGS_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = ""
    if "row_id" not in normalized.columns:
        normalized["row_id"] = ""
    if "표시순서" not in normalized.columns:
        normalized["표시순서"] = range(1, len(normalized) + 1)
    if "sort_order" not in normalized.columns:
        normalized["sort_order"] = normalized["표시순서"]

    normalized = normalized[HOLDINGS_COLUMNS]
    if "sort_order" not in normalized.columns:
        normalized.insert(1, "sort_order", normalized["표시순서"] if "표시순서" in normalized.columns else range(1, len(normalized) + 1))
    normalized["sort_order"] = normalized["sort_order"].map(parse_number)
    normalized["표시순서"] = normalized["표시순서"].map(parse_number)
    normalized["sort_order"] = normalized["sort_order"].where(normalized["sort_order"] >= 0, normalized["표시순서"])
    missing_order = normalized["sort_order"] < 0
    normalized.loc[missing_order, "sort_order"] = range(int(missing_order.sum()))
    normalized = normalized.sort_values("sort_order", kind="stable").reset_index(drop=True)
    normalized["sort_order"] = range(len(normalized))
    normalized["표시순서"] = normalized["sort_order"]
    normalized["세부자산군"] = normalized["세부자산군"].fillna("").astype(str).map(normalize_sub_asset_class)
    normalized["자산군"] = normalized["세부자산군"]
    normalized["상위자산군"] = normalized["세부자산군"].map(infer_major_asset_class)
    normalized["row_id"] = normalized["row_id"].fillna("").astype(str).str.strip()
    missing_row_ids = normalized["row_id"] == ""
    normalized.loc[missing_row_ids, "row_id"] = [_new_row_id() for _ in range(int(missing_row_ids.sum()))]
    normalized["시장"] = normalized.apply(lambda row: infer_market(row.get("세부자산군", ""), row.get("시장", "")), axis=1)
    normalized["티커 또는 종목코드"] = normalized.apply(
        lambda row: normalize_symbol(row["시장"], row["티커 또는 종목코드"]),
        axis=1,
    )
    normalized["종목명"] = normalized["종목명"].fillna("").astype(str)
    crypto_rows = normalized.apply(
        lambda row: is_crypto_route(row.get("시장", ""), row.get("자산군", ""), row.get("세부자산군", "")),
        axis=1,
    )
    normalized.loc[crypto_rows, "종목명"] = normalized.loc[crypto_rows, "티커 또는 종목코드"].map(get_crypto_security_name)
    normalized["통화"] = normalized.apply(
        lambda row: infer_currency(row.get("시장", ""), row.get("자산군", ""), row.get("티커 또는 종목코드", "")),
        axis=1,
    )
    normalized["메모"] = normalized["메모"].fillna("").astype(str)
    normalized["새빛_보유수량"] = normalized["새빛_보유수량"].map(parse_number)
    normalized["희주_보유수량"] = normalized["희주_보유수량"].map(parse_number)
    normalized["합산_보유수량"] = normalized["새빛_보유수량"] + normalized["희주_보유수량"]
    normalized["보유수량"] = normalized["합산_보유수량"]
    normalized["평균단가"] = normalized["평균단가"].map(parse_number)
    return normalized.reset_index(drop=True)


def validate_holdings(df: pd.DataFrame) -> list[str]:
    errors: list[str] = []
    required = ["상위자산군", "세부자산군", "자산군", "시장", "티커 또는 종목코드", "종목명", "새빛_보유수량", "희주_보유수량", "평균단가", "통화"]
    for idx, row in df.iterrows():
        label = f"{idx + 1}행"
        for column in required:
            value = row.get(column, "")
            if pd.isna(value) or str(value).strip() == "":
                errors.append(f"{label}: '{column}' 값이 비어 있습니다.")
        if row.get("자산군") not in ASSET_CLASSES:
            errors.append(f"{label}: 자산군은 목록에서 선택해주세요.")
        if row.get("세부자산군") not in ASSET_CLASSES:
            errors.append(f"{label}: 세부자산군은 목록에서 선택해주세요.")
        if row.get("상위자산군") != infer_major_asset_class(row.get("세부자산군", "")):
            errors.append(f"{label}: 상위자산군 자동 분류가 올바르지 않습니다.")
        if row.get("시장") not in MARKETS:
            errors.append(f"{label}: 시장은 목록에서 선택해주세요.")
        if row.get("통화") not in CURRENCIES:
            errors.append(f"{label}: 통화는 목록에서 선택해주세요.")
        if float(row.get("새빛_보유수량", 0) or 0) < 0:
            errors.append(f"{label}: 새빛_보유수량은 0 이상이어야 합니다.")
        if float(row.get("희주_보유수량", 0) or 0) < 0:
            errors.append(f"{label}: 희주_보유수량은 0 이상이어야 합니다.")
        if float(row.get("평균단가", 0) or 0) < 0:
            errors.append(f"{label}: 평균단가는 0 이상이어야 합니다.")
    return errors


def normalize_capital_flows(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return empty_capital_flows()
    normalized = df.copy()
    for column in CAPITAL_FLOW_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = ""
    normalized = normalized[CAPITAL_FLOW_COLUMNS]
    normalized["일시"] = normalized["일시"].fillna("").astype(str)
    normalized["유형"] = normalized["유형"].fillna("").astype(str)
    normalized["금액"] = normalized["금액"].map(parse_number)
    normalized["통화"] = normalized["통화"].fillna("KRW").astype(str).str.upper()
    normalized["메모"] = normalized["메모"].fillna("").astype(str)
    normalized["반영 후 투자원금"] = normalized["반영 후 투자원금"].map(parse_number)
    return normalized


def current_invested_principal(capital_flows: pd.DataFrame | None) -> float:
    flows = normalize_capital_flows(capital_flows)
    if flows.empty:
        return 0.0
    last_balance = parse_number(flows.iloc[-1].get("반영 후 투자원금", 0))
    if last_balance:
        return last_balance
    total = 0.0
    for _, row in flows.iterrows():
        amount = parse_number(row.get("금액", 0))
        flow_type = str(row.get("유형", ""))
        if flow_type in {"초기원금", "추가입금", "추가매수연동"}:
            total += amount
        elif flow_type == "원금출금":
            total -= amount
        elif flow_type == "원금수정":
            total = amount
    return total


def append_capital_flow(
    capital_flows: pd.DataFrame | None,
    flow_type: str,
    amount: float,
    memo: str = "",
    timestamp: str | None = None,
) -> pd.DataFrame:
    flows = normalize_capital_flows(capital_flows)
    current = current_invested_principal(flows)
    amount = parse_number(amount)
    if flow_type in {"초기원금", "원금수정"}:
        next_principal = amount
    elif flow_type in {"추가입금", "추가매수연동"}:
        next_principal = current + amount
    elif flow_type == "원금출금":
        next_principal = current - amount
    else:
        next_principal = current
    row = pd.DataFrame(
        [[timestamp or pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), flow_type, amount, "KRW", memo, next_principal]],
        columns=CAPITAL_FLOW_COLUMNS,
    )
    if flows.empty:
        return row
    return pd.concat([flows, row], ignore_index=True)


def calculate_simple_return(current_value: float, invested_principal: float) -> float:
    if invested_principal == 0:
        return 0.0
    return (current_value - invested_principal) / invested_principal


def calculate_xirr_return(cash_flows) -> float | None:
    """
    입금/출금 시점을 반영한 현금흐름 수익률. 현재는 추후 확장을 위해 None을 반환한다.
    """
    return None


def normalize_snapshots(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return empty_snapshots()
    normalized = df.copy()
    if "날짜시간" not in normalized.columns and "날짜" in normalized.columns:
        normalized["날짜시간"] = normalized["날짜"]
    if "스냅샷유형" not in normalized.columns:
        if "메모" in normalized.columns:
            normalized["스냅샷유형"] = normalized["메모"].map(lambda value: "현재값" if str(value) == "현재값" else "수동저장")
        else:
            normalized["스냅샷유형"] = "수동저장"
    for column in SNAPSHOT_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = ""
    normalized = normalized[SNAPSHOT_COLUMNS]
    normalized["날짜시간"] = normalized["날짜시간"].fillna("").astype(str)
    normalized["연도"] = normalized["연도"].map(parse_number).astype(int)
    normalized["스냅샷유형"] = normalized["스냅샷유형"].fillna("수동저장").astype(str)
    for column in ["총평가금액", "투자원금", "평가손익", "누적수익률"]:
        normalized[column] = normalized[column].map(parse_number)
    normalized["메모"] = normalized["메모"].fillna("").astype(str)
    return normalized


def calculate_portfolio(holdings: pd.DataFrame, prices: pd.DataFrame, usdkrw: float | None = None) -> pd.DataFrame:
    holdings = normalize_holdings(holdings)
    prices = prices.copy() if prices is not None else empty_prices()
    if prices.empty:
        prices = empty_prices()

    price_map = {}
    for _, row in prices.iterrows():
        price_symbol = str(row.get("티커 또는 종목코드", "")).strip().upper()
        if not price_symbol:
            continue
        price_map[price_symbol] = row
        if price_symbol.endswith("-USD"):
            price_map[price_symbol[:-4]] = row

    rows = []
    fallback_usdkrw = float(usdkrw or _extract_usdkrw(prices) or 1350.0)

    for _, row in holdings.iterrows():
        symbol = normalize_symbol(row["시장"], row["티커 또는 종목코드"])
        key = symbol.upper()
        price_row = price_map.get(key, {})

        current_price = _to_float(price_row.get("현재가"), np.nan)
        if np.isnan(current_price):
            current_price = _default_price(row)
        price_basis_current = current_price

        fx_rate = _to_float(price_row.get("USD/KRW"), fallback_usdkrw)
        currency = str(row["통화"]).upper()
        saebit_quantity = float(row.get("새빛_보유수량", 0) or 0)
        heeju_quantity = float(row.get("희주_보유수량", 0) or 0)
        quantity = saebit_quantity + heeju_quantity
        avg_price = float(row["평균단가"] or 0)

        purchase_amount = quantity * avg_price
        value = quantity * current_price
        saebit_value = saebit_quantity * current_price
        heeju_value = heeju_quantity * current_price

        if row["세부자산군"] == "달러":
            value_krw = quantity * fx_rate
            purchase_krw = quantity * avg_price * fx_rate
            saebit_value_krw = saebit_quantity * fx_rate
            heeju_value_krw = heeju_quantity * fx_rate
            current_price = fx_rate
        elif currency == "USD":
            value_krw = value * fx_rate
            purchase_krw = purchase_amount * fx_rate
            saebit_value_krw = saebit_value * fx_rate
            heeju_value_krw = heeju_value * fx_rate
        else:
            value_krw = value
            purchase_krw = purchase_amount
            saebit_value_krw = saebit_value
            heeju_value_krw = heeju_value

        profit_loss = value_krw - purchase_krw
        return_rate, return_status = calculate_position_return(
            {
                **row.to_dict(),
                "현재가": price_basis_current,
                "합산_보유수량": quantity,
                "매입금액": purchase_amount,
                "평가금액": value,
                "평가손익": profit_loss,
            }
        )

        rows.append(
            {
                **row.to_dict(),
                "보유수량": quantity,
                "합산_보유수량": quantity,
                "현재가": current_price,
                "USD/KRW": fx_rate,
                "매입금액": purchase_amount,
                "평가금액": value,
                "원화 환산 평가금액": value_krw,
                "원화 환산 매입금액": purchase_krw,
                "평가손익": profit_loss,
                "수익률": return_rate,
                "수익률 계산상태": return_status,
                "새빛_평가금액": saebit_value_krw,
                "희주_평가금액": heeju_value_krw,
                "합산_평가금액": value_krw,
                "합산_평가손익": profit_loss,
                "합산_수익률": return_rate,
                "마지막 가격 업데이트 시각": price_row.get("마지막 가격 업데이트 시각", ""),
                "가격 상태": price_row.get("상태", "가격 미조회"),
            }
        )

    calculated = pd.DataFrame(rows)
    total_value = calculated["원화 환산 평가금액"].sum() if not calculated.empty else 0.0
    calculated["전체 포트폴리오 내 비중"] = np.where(total_value > 0, calculated["원화 환산 평가금액"] / total_value, 0.0)
    calculated["전체_비중"] = calculated["전체 포트폴리오 내 비중"]
    calculated["자산군 내 비중"] = calculated.groupby("자산군")["원화 환산 평가금액"].transform(
        lambda s: s / s.sum() if s.sum() else 0.0
    )
    calculated["세부자산군 내 비중"] = calculated["자산군 내 비중"]
    calculated["상위자산군 내 비중"] = calculated.groupby("상위자산군")["원화 환산 평가금액"].transform(
        lambda s: s / s.sum() if s.sum() else 0.0
    )
    return calculated


def is_cash_asset(row: pd.Series | dict) -> bool:
    sub_asset_class = str(row.get("세부자산군", row.get("자산군", "")) or "").strip()
    asset_class = str(row.get("자산군", "") or "").strip()
    market = str(row.get("시장", "") or "").strip().upper()
    currency = str(row.get("통화", "") or "").strip().upper()
    symbol = normalize_symbol(market, row.get("티커 또는 종목코드", ""))
    return (
        sub_asset_class == "달러"
        or asset_class == "달러"
        or market == "FX"
        or (currency == "USD" and symbol in {"USD", "USDKRW", "KRW=X"})
    )


def calculate_position_return(row: pd.Series | dict) -> tuple[float | None, str]:
    """
    종목별 수익률을 같은 통화의 현재가와 평균단가 기준으로 계산한다.
    US/CRYPTO는 USD 가격끼리, KR은 KRW 가격끼리 비교한다.
    """
    if is_cash_asset(row):
        return None, "현금성 자산 제외"

    quantity = parse_number(row.get("합산_보유수량", row.get("보유수량", 0)))
    if quantity <= 0:
        return None, "수량 0"

    avg_price = parse_number(row.get("평균단가"))
    if avg_price <= 0:
        return None, "평균단가 없음"

    current_price = parse_number(row.get("현재가"))
    if current_price <= 0:
        return None, "현재가 없음"

    market = str(row.get("시장", "") or "").strip().upper()
    currency = str(row.get("통화", "") or "").strip().upper()
    if market == "US" and currency != "USD":
        return None, "통화 확인 필요"
    if market == "KR" and currency != "KRW":
        return None, "통화 확인 필요"
    if market == "CRYPTO" and currency != "USD":
        return None, "통화 확인 필요"

    return (current_price - avg_price) / avg_price, "정상"


def build_position_return_audit(calculated: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "티커_또는_종목코드",
        "종목명",
        "시장",
        "통화",
        "세부자산군",
        "합산_보유수량",
        "평균단가",
        "현재가",
        "매입금액",
        "평가금액",
        "평가손익",
        "계산된 수익률",
        "계산상태",
    ]
    if calculated is None or calculated.empty:
        return pd.DataFrame(columns=columns)

    rows = []
    for _, row in calculated.iterrows():
        return_rate, status = calculate_position_return(row)
        rows.append(
            {
                "티커_또는_종목코드": row.get("티커 또는 종목코드", ""),
                "종목명": row.get("종목명", ""),
                "시장": row.get("시장", ""),
                "통화": row.get("통화", ""),
                "세부자산군": row.get("세부자산군", row.get("자산군", "")),
                "합산_보유수량": row.get("합산_보유수량", row.get("보유수량", 0)),
                "평균단가": row.get("평균단가", 0),
                "현재가": row.get("현재가", 0),
                "매입금액": row.get("매입금액", 0),
                "평가금액": row.get("평가금액", 0),
                "평가손익": row.get("평가손익", 0),
                "계산된 수익률": return_rate,
                "계산상태": status,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def summarize_portfolio(calculated: pd.DataFrame) -> dict[str, float]:
    if calculated.empty:
        return {"총 평가금액": 0.0, "총 매입금액": 0.0, "총 평가손익": 0.0, "총 수익률": 0.0}

    total_value = float(calculated["원화 환산 평가금액"].sum())
    total_purchase = float(calculated["원화 환산 매입금액"].sum())
    profit_loss = total_value - total_purchase
    return_rate = profit_loss / total_purchase if total_purchase else 0.0
    return {
        "총 평가금액": total_value,
        "총 매입금액": total_purchase,
        "총 평가손익": profit_loss,
        "총 수익률": return_rate,
    }


def calculate_allocation_by_sub_asset_class(calculated: pd.DataFrame) -> pd.DataFrame:
    if calculated.empty:
        return pd.DataFrame(columns=["자산군", "원화 환산 평가금액", "비중"])
    group_column = "세부자산군" if "세부자산군" in calculated.columns else "자산군"
    grouped = calculated.groupby(group_column, as_index=False)["원화 환산 평가금액"].sum()
    grouped = grouped.rename(columns={group_column: "자산군"})
    total = grouped["원화 환산 평가금액"].sum()
    grouped["비중"] = grouped["원화 환산 평가금액"] / total if total else 0.0
    grouped["자산군"] = pd.Categorical(grouped["자산군"], categories=ASSET_CLASSES, ordered=True)
    return grouped.sort_values("자산군").reset_index(drop=True)


def calculate_allocation_by_major_asset_class(calculated: pd.DataFrame) -> pd.DataFrame:
    if calculated.empty:
        return pd.DataFrame(columns=["상위자산군", "원화 환산 평가금액", "비중"])
    data = calculated.copy()
    if "상위자산군" not in data.columns:
        group_column = "세부자산군" if "세부자산군" in data.columns else "자산군"
        data["상위자산군"] = data[group_column].map(infer_major_asset_class)
    grouped = data.groupby("상위자산군", as_index=False)["원화 환산 평가금액"].sum()
    total = grouped["원화 환산 평가금액"].sum()
    grouped["비중"] = grouped["원화 환산 평가금액"] / total if total else 0.0
    grouped["상위자산군"] = pd.Categorical(grouped["상위자산군"], categories=MAJOR_ASSET_CLASSES, ordered=True)
    return grouped.sort_values("상위자산군").reset_index(drop=True)


def asset_class_summary(calculated: pd.DataFrame) -> pd.DataFrame:
    return calculate_allocation_by_sub_asset_class(calculated)


def account_value_summary(calculated: pd.DataFrame) -> pd.DataFrame:
    if calculated.empty:
        return pd.DataFrame({"계좌": ["새빛 계좌", "희주 계좌"], "평가금액": [0.0, 0.0]})
    return pd.DataFrame(
        {
            "계좌": ["새빛 계좌", "희주 계좌"],
            "평가금액": [
                float(calculated.get("새빛_평가금액", pd.Series(dtype=float)).sum()),
                float(calculated.get("희주_평가금액", pd.Series(dtype=float)).sum()),
            ],
        }
    )


def account_asset_class_summary(calculated: pd.DataFrame, account: str) -> pd.DataFrame:
    value_column = f"{account}_평가금액"
    if calculated.empty or value_column not in calculated.columns:
        return pd.DataFrame(columns=["자산군", "평가금액", "비중"])
    group_column = "세부자산군" if "세부자산군" in calculated.columns else "자산군"
    grouped = calculated.groupby(group_column, as_index=False)[value_column].sum().rename(columns={group_column: "자산군", value_column: "평가금액"})
    total = grouped["평가금액"].sum()
    grouped["비중"] = grouped["평가금액"] / total if total else 0.0
    grouped["자산군"] = pd.Categorical(grouped["자산군"], categories=ASSET_CLASSES, ordered=True)
    return grouped.sort_values("자산군").reset_index(drop=True)


def account_major_asset_class_summary(calculated: pd.DataFrame, account: str) -> pd.DataFrame:
    value_column = f"{account}_평가금액"
    if calculated.empty or value_column not in calculated.columns:
        return pd.DataFrame(columns=["상위자산군", "평가금액", "비중"])
    data = calculated.copy()
    if "상위자산군" not in data.columns:
        group_column = "세부자산군" if "세부자산군" in data.columns else "자산군"
        data["상위자산군"] = data[group_column].map(infer_major_asset_class)
    grouped = data.groupby("상위자산군", as_index=False)[value_column].sum().rename(columns={value_column: "평가금액"})
    total = grouped["평가금액"].sum()
    grouped["비중"] = grouped["평가금액"] / total if total else 0.0
    grouped["상위자산군"] = pd.Categorical(grouped["상위자산군"], categories=MAJOR_ASSET_CLASSES, ordered=True)
    return grouped.sort_values("상위자산군").reset_index(drop=True)


def _extract_usdkrw(prices: pd.DataFrame) -> float | None:
    if prices is None or prices.empty or "USD/KRW" not in prices.columns:
        return None
    values = pd.to_numeric(prices["USD/KRW"], errors="coerce").dropna()
    return float(values.iloc[-1]) if not values.empty else None


def _default_price(row: pd.Series) -> float:
    if row.get("세부자산군", row.get("자산군")) == "달러":
        return 1.0
    return float(row.get("평균단가", 0) or 0)


def _to_float(value, default: float) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
