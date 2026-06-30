import unittest

import pandas as pd

import app
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

    def test_zero_based_sort_order_is_preserved(self):
        holdings = sample_holdings().iloc[:3].copy()
        holdings["sort_order"] = [2, 1, 0]
        normalized = app.normalize_holdings(holdings)
        self.assertEqual(list(normalized["sort_order"]), [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
