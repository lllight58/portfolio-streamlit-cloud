import unittest
import os
from pathlib import Path
from uuid import uuid4

import pandas as pd

import app
from src import db
from src.portfolio_calculator import HOLDINGS_COLUMNS, sample_holdings
from src.repositories.holdings_repository import upsert_holding_row
from src.symbol_resolver import lookup_security


class TickerLookupTests(unittest.TestCase):
    def test_us_short_and_common_tickers_resolve(self):
        for symbol in ["BR", "AAPL", "MSFT"]:
            with self.subTest(symbol=symbol):
                result = lookup_security("US", symbol)
                self.assertTrue(result.success, result)
                self.assertEqual(result.symbol, symbol)
                self.assertTrue(result.name)

    def test_kr_yfinance_symbol_resolves_when_supported(self):
        result = lookup_security("KR", "005930.KS")
        self.assertTrue(result.success, result)
        self.assertEqual(result.symbol, "005930.KS")
        self.assertTrue(result.name)

    def test_missing_ticker_returns_clear_failure(self):
        result = lookup_security("US", "ZZZZZ")
        self.assertFalse(result.success, result)
        self.assertEqual(result.symbol, "ZZZZZ")
        self.assertTrue(result.source)
        self.assertTrue(result.reason)


class HoldingUpsertTests(unittest.TestCase):
    def test_add_then_edit_updates_same_row_id(self):
        holdings = sample_holdings().iloc[:1].copy()
        updated, row_id = upsert_holding_row(
            holdings,
            "",
            {
                "세부자산군": "개별주",
                "시장": "US",
                "티커 또는 종목코드": "BR",
                "종목명": "Broadridge Financial Solutions, Inc.",
                "새빛_보유수량": 1,
                "희주_보유수량": 0,
                "평균단가": 100,
                "통화": "USD",
                "메모": "first",
            },
        )

        edited, edited_row_id = upsert_holding_row(
            updated,
            row_id,
            {
                "세부자산군": "개별주",
                "시장": "US",
                "티커 또는 종목코드": "BR",
                "종목명": "Broadridge Financial Solutions, Inc.",
                "새빛_보유수량": 2,
                "희주_보유수량": 3,
                "평균단가": 123.45,
                "통화": "USD",
                "메모": "edited",
            },
        )

        self.assertEqual(row_id, edited_row_id)
        self.assertEqual(len(updated), len(edited))
        row = edited.loc[edited["row_id"] == row_id].iloc[0]
        self.assertEqual(row["티커 또는 종목코드"], "BR")
        self.assertEqual(row["새빛_보유수량"], 2)
        self.assertEqual(row["희주_보유수량"], 3)
        self.assertEqual(row["합산_보유수량"], 5)
        self.assertEqual(row["메모"], "edited")

    def test_repository_output_keeps_holdings_schema(self):
        updated, _ = upsert_holding_row(
            pd.DataFrame([sample_holdings().iloc[0].to_dict()]),
            "",
            {
                "세부자산군": "ETF",
                "시장": "US",
                "티커 또는 종목코드": "AAPL",
                "종목명": "Apple Inc.",
                "새빛_보유수량": 1,
                "희주_보유수량": 1,
                "평균단가": 200,
                "통화": "USD",
                "메모": "",
            },
        )
        self.assertEqual(list(updated.columns), HOLDINGS_COLUMNS)

    def test_apply_buys_preserves_decimal_quantity_and_price(self):
        old_backend = os.environ.get("DATABASE_BACKEND")
        old_sqlite_path = os.environ.get("SQLITE_DB_PATH")
        tmp_db = Path("data") / f"test_decimal_buys_{uuid4().hex}.db"
        try:
            os.environ["DATABASE_BACKEND"] = "sqlite"
            os.environ["SQLITE_DB_PATH"] = str(tmp_db)
            db.initialize_database()
            app.clear_cached_tables("holdings", "transactions")

            applied = app.apply_buys(
                pd.DataFrame(
                    [
                        {
                            "매수계좌": "새빛",
                            "티커 또는 종목코드": "DECIMALTEST",
                            "종목명": "Decimal Test",
                            "자산군": "ETF",
                            "시장": "US",
                            "통화": "USD",
                            "매수수량": 0.12345678,
                            "매수단가": 78.9012,
                            "메모": "",
                        }
                    ]
                )
            )

            holdings = app.normalize_holdings(db.read_table("holdings"))
            transactions = db.read_table("transactions")
            row = holdings[holdings["티커 또는 종목코드"] == "DECIMALTEST"].iloc[0]
            tx = transactions[transactions["티커 또는 종목코드"] == "DECIMALTEST"].iloc[0]

            self.assertEqual(applied, 1)
            self.assertAlmostEqual(float(row["새빛_보유수량"]), 0.12345678)
            self.assertAlmostEqual(float(row["평균단가"]), 78.9012)
            self.assertAlmostEqual(float(tx["매수수량"]), 0.12345678)
            self.assertAlmostEqual(float(tx["매수단가"]), 78.9012)
            self.assertAlmostEqual(float(tx["매수금액"]), 0.12345678 * 78.9012)
        finally:
            app.clear_cached_tables("holdings", "transactions")
            if tmp_db.exists():
                try:
                    tmp_db.unlink()
                except PermissionError:
                    pass
            if old_backend is None:
                os.environ.pop("DATABASE_BACKEND", None)
            else:
                os.environ["DATABASE_BACKEND"] = old_backend
            if old_sqlite_path is None:
                os.environ.pop("SQLITE_DB_PATH", None)
            else:
                os.environ["SQLITE_DB_PATH"] = old_sqlite_path


class AssetOrderTests(unittest.TestCase):
    def test_build_asset_order_items_includes_all_holdings(self):
        holdings = sample_holdings()
        items = app.build_asset_order_items(holdings)
        self.assertEqual(len(items), len(holdings))
        self.assertTrue(all(item["id"] for item in items))
        self.assertTrue(all(item["label"] for item in items))

    def test_build_asset_order_items_handles_missing_order_values(self):
        holdings = sample_holdings()
        holdings["sort_order"] = None
        holdings["표시순서"] = None
        items = app.build_asset_order_items(holdings)
        self.assertEqual(len(items), len(holdings))

    def test_build_asset_order_df_includes_debug_ui_rows(self):
        holdings = sample_holdings()
        order_df = app.build_asset_order_df(holdings)
        self.assertEqual(list(order_df.columns), ["id", "label", "display_order"])
        self.assertEqual(len(order_df), len(holdings))
        self.assertEqual(order_df["display_order"].tolist(), list(range(len(order_df))))

    def test_zero_based_sort_order_is_preserved(self):
        holdings = sample_holdings().iloc[:3].copy()
        holdings["sort_order"] = [2, 1, 0]
        normalized = app.normalize_holdings(holdings)
        self.assertEqual(list(normalized["sort_order"]), [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
