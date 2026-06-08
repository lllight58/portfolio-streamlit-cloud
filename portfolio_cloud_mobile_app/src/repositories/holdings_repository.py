from __future__ import annotations

from uuid import uuid4

import pandas as pd

from src import db
from src.formatters import parse_number
from src.portfolio_calculator import normalize_holdings

from .base_repository import DataFrameRepository

holdings_repository = DataFrameRepository("holdings")


def ensure_row_ids() -> int:
    """Persist row_id and sort_order values for holdings rows that need them."""
    holdings = normalize_holdings(db.read_table("holdings"))
    if holdings.empty:
        return 0

    changed = False
    if "row_id" not in holdings.columns:
        holdings["row_id"] = ""
        changed = True

    missing_row_ids = holdings["row_id"].fillna("").astype(str).str.strip() == ""
    if missing_row_ids.any():
        holdings.loc[missing_row_ids, "row_id"] = [str(uuid4()) for _ in range(int(missing_row_ids.sum()))]
        changed = True

    if "sort_order" not in holdings.columns:
        holdings["sort_order"] = range(1, len(holdings) + 1)
        changed = True

    sort_values = holdings["sort_order"].map(parse_number)
    missing_sort = sort_values <= 0
    if missing_sort.any():
        holdings.loc[missing_sort, "sort_order"] = [idx + 1 for idx in range(int(missing_sort.sum()))]
        changed = True

    if "표시순서" not in holdings.columns or not holdings["표시순서"].equals(holdings["sort_order"]):
        holdings["표시순서"] = holdings["sort_order"]
        changed = True

    if changed:
        db.write_table("holdings", normalize_holdings(holdings))
    return int(changed)


def delete_holdings_by_row_ids(row_ids: list[str]) -> int:
    """Delete holdings rows by row_id only. Other tables are intentionally preserved."""
    target_ids = {str(row_id).strip() for row_id in row_ids if str(row_id).strip()}
    if not target_ids:
        return 0

    holdings = normalize_holdings(db.read_table("holdings"))
    before_count = len(holdings)
    remaining = holdings[~holdings["row_id"].fillna("").astype(str).isin(target_ids)].copy()
    deleted_count = before_count - len(remaining)
    if deleted_count <= 0:
        return 0

    remaining = _renumber_sort_order(remaining)
    db.write_table("holdings", remaining)
    return int(deleted_count)


def delete_holdings_by_selectors(selectors: list[dict]) -> int:
    """Delete holdings by row_id, falling back to market + symbol when row_id is unavailable."""
    if not selectors:
        return 0

    row_ids = {str(item.get("row_id", "")).strip() for item in selectors if str(item.get("row_id", "")).strip()}
    market_symbols = {
        (str(item.get("market", "")).strip().upper(), str(item.get("symbol", "")).strip().upper())
        for item in selectors
        if str(item.get("market", "")).strip() and str(item.get("symbol", "")).strip()
    }
    if not row_ids and not market_symbols:
        return 0

    holdings = normalize_holdings(db.read_table("holdings"))
    before_count = len(holdings)
    delete_mask = holdings["row_id"].fillna("").astype(str).isin(row_ids)
    fallback_mask = holdings.apply(
        lambda row: (
            str(row.get("market", row.get("시장", "")) or "").strip().upper(),
            str(row.get("symbol", row.get("티커 또는 종목코드", "")) or "").strip().upper(),
        )
        in market_symbols,
        axis=1,
    )
    remaining = holdings[~(delete_mask | fallback_mask)].copy()
    deleted_count = before_count - len(remaining)
    if deleted_count <= 0:
        return 0

    remaining = _renumber_sort_order(remaining)
    db.write_table("holdings", remaining)
    return int(deleted_count)


def update_holdings_sort_order(order_items: list[dict]) -> int:
    """Update sort_order using row_id as the stable key."""
    if not order_items:
        return 0

    order_map = {
        str(item.get("row_id", "")).strip(): int(parse_number(item.get("sort_order")))
        for item in order_items
        if str(item.get("row_id", "")).strip()
    }
    if not order_map:
        return 0

    holdings = normalize_holdings(db.read_table("holdings"))
    updated = 0
    for idx, row in holdings.iterrows():
        row_id = str(row.get("row_id", "")).strip()
        if row_id in order_map:
            holdings.at[idx, "sort_order"] = order_map[row_id]
            holdings.at[idx, "표시순서"] = order_map[row_id]
            updated += 1

    if updated:
        holdings = normalize_holdings(holdings)
        db.write_table("holdings", holdings)
    return int(updated)


def _renumber_sort_order(holdings: pd.DataFrame) -> pd.DataFrame:
    if holdings.empty:
        return holdings
    output = normalize_holdings(holdings).copy()
    output["sort_order"] = range(1, len(output) + 1)
    output["표시순서"] = output["sort_order"]
    return normalize_holdings(output)
