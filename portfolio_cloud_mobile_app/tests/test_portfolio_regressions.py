import unittest
import os
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import pandas as pd

import app
from src import db
from src.portfolio_calculator import HOLDINGS_COLUMNS, sample_holdings
from src.price_fetcher import (
    DIVIDEND_TAX_RATE,
    build_after_tax_total_return_index,
    build_krw_adjusted_benchmark_tr,
    build_weighted_benchmark_after_tax_tr,
    calculate_cash_flow_adjusted_return_from_index,
    calculate_calendar_year_return_from_index,
    fetch_kr_price_from_naver_chart,
    fetch_kr_price_from_naver_mobile,
)
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
            buy_transactions = db.read_table("buy_transactions")
            buy_tx = buy_transactions[buy_transactions["티커"] == "DECIMALTEST"].iloc[0]

            self.assertEqual(applied, 1)
            self.assertAlmostEqual(float(row["새빛_보유수량"]), 0.12345678)
            self.assertAlmostEqual(float(row["평균단가"]), 78.9012)
            self.assertAlmostEqual(float(tx["매수수량"]), 0.12345678)
            self.assertAlmostEqual(float(tx["매수단가"]), 78.9012)
            self.assertAlmostEqual(float(tx["매수금액"]), 0.12345678 * 78.9012)
            self.assertAlmostEqual(float(buy_tx["수량"]), 0.12345678)
            self.assertAlmostEqual(float(buy_tx["단가"]), 78.9012)
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

    def test_revert_buy_transaction_recalculates_average_price(self):
        old_backend = os.environ.get("DATABASE_BACKEND")
        old_sqlite_path = os.environ.get("SQLITE_DB_PATH")
        tmp_db = Path("data") / f"test_revert_buy_{uuid4().hex}.db"
        try:
            os.environ["DATABASE_BACKEND"] = "sqlite"
            os.environ["SQLITE_DB_PATH"] = str(tmp_db)
            db.initialize_database()
            app.clear_cached_tables("holdings", "transactions", "buy_transactions")

            buys = pd.DataFrame(
                [
                    {
                        "매수계좌": "새빛",
                        "티커 또는 종목코드": "VT",
                        "종목명": "Vanguard Total World Stock ETF",
                        "자산군": "ETF",
                        "시장": "US",
                        "통화": "USD",
                        "매수수량": 0.5,
                        "매수단가": 123.45,
                        "메모": "",
                    }
                ]
            )
            before = app.normalize_holdings(db.read_table("holdings"))
            before_vt = before[before["티커 또는 종목코드"] == "VT"].iloc[0]
            before_qty = float(before_vt["새빛_보유수량"])
            before_avg = float(before_vt["평균단가"])

            self.assertEqual(app.apply_buys(buys), 1)
            tx = app.load_recent_buy_transactions(limit=5)[0]
            app.revert_buy_transaction(str(tx["거래ID"]))

            after = app.normalize_holdings(db.read_table("holdings"))
            after_vt = after[after["티커 또는 종목코드"] == "VT"].iloc[0]
            buy_transactions = app.normalize_buy_transactions(db.read_table("buy_transactions"))

            self.assertAlmostEqual(float(after_vt["새빛_보유수량"]), before_qty)
            self.assertAlmostEqual(float(after_vt["평균단가"]), before_avg)
            self.assertTrue(bool(buy_transactions.iloc[0]["되돌림여부"]))
            self.assertEqual(app.load_recent_buy_transactions(limit=5), [])
            with self.assertRaises(ValueError):
                app.revert_buy_transaction(str(tx["거래ID"]))
        finally:
            app.clear_cached_tables("holdings", "transactions", "buy_transactions")
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

    def test_revert_one_row_from_batch_and_recent_limit(self):
        old_backend = os.environ.get("DATABASE_BACKEND")
        old_sqlite_path = os.environ.get("SQLITE_DB_PATH")
        tmp_db = Path("data") / f"test_revert_batch_{uuid4().hex}.db"
        try:
            os.environ["DATABASE_BACKEND"] = "sqlite"
            os.environ["SQLITE_DB_PATH"] = str(tmp_db)
            db.initialize_database()
            app.clear_cached_tables("holdings", "transactions", "buy_transactions")

            rows = []
            for index in range(6):
                rows.append(
                    {
                        "매수계좌": "새빛",
                        "티커 또는 종목코드": f"BATCH{index}",
                        "종목명": f"Batch {index}",
                        "자산군": "ETF",
                        "시장": "US",
                        "통화": "USD",
                        "매수수량": 1 + index / 10,
                        "매수단가": 10.25 + index,
                        "메모": "",
                    }
                )
            self.assertEqual(app.apply_buys(pd.DataFrame(rows[:3])), 3)
            self.assertEqual(app.apply_buys(pd.DataFrame(rows[3:])), 3)

            recent = app.load_recent_buy_transactions(limit=5)
            self.assertEqual(len(recent), 5)
            target = recent[0]
            target_symbol = str(target["티커"])
            app.revert_buy_transaction(str(target["거래ID"]))

            holdings = app.normalize_holdings(db.read_table("holdings"))
            reverted_row = holdings[holdings["티커 또는 종목코드"] == target_symbol].iloc[0]
            active_symbols = {str(tx["티커"]) for tx in app.load_recent_buy_transactions(limit=5)}

            self.assertAlmostEqual(float(reverted_row["합산_보유수량"]), 0.0)
            self.assertNotIn(target_symbol, active_symbols)
            self.assertGreaterEqual(len(active_symbols), 4)
        finally:
            app.clear_cached_tables("holdings", "transactions", "buy_transactions")
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

    def test_buy_transaction_label_shows_ticker_name_and_readable_values(self):
        tx = {
            "거래ID": "tx-1",
            "일괄반영ID": "batch-1",
            "자산ID": "asset-1",
            "티커": "BR",
            "종목명": "Broadridge Financial Solutions",
            "계좌": "새빛",
            "수량": 1.3,
            "단가": 13.25,
            "금액": 17.225,
            "통화": "USD",
            "생성일시": "2026-06-30T12:39:38",
            "되돌림여부": False,
            "되돌림일시": "",
            "되돌림사유": "",
        }

        label = app.format_buy_transaction_label(tx)

        self.assertIn("BR · Broadridge Financial Solutions", label)
        self.assertIn("새빛 계좌 | 1.3주 × 13.2500 USD = 17.23 USD", label)
        self.assertIn("2026-06-30 12:39", label)
        self.assertNotIn("T12:39:38", label)

    def test_buy_transaction_label_falls_back_to_holding_when_batch_is_stored_as_ticker(self):
        holdings = sample_holdings().iloc[:1].copy()
        holding = holdings.iloc[0]
        tx = pd.DataFrame(
            [
                {
                    "거래ID": "tx-1",
                    "일괄반영ID": "batch-1",
                    "자산ID": str(holding.get("row_id", "")),
                    "티커": "BATCH3",
                    "종목명": "",
                    "계좌": "희주",
                    "수량": 3,
                    "단가": 78500,
                    "금액": 235500,
                    "통화": "KRW",
                    "생성일시": "2026-06-30T12:45:10",
                    "되돌림여부": False,
                    "되돌림일시": "",
                    "되돌림사유": "",
                }
            ]
        )

        enriched = app.enrich_buy_transactions_with_holdings(tx, holdings).iloc[0].to_dict()
        label = app.format_buy_transaction_label(enriched)

        self.assertIn(str(holding["티커 또는 종목코드"]), label)
        self.assertIn(str(holding["종목명"]), label)
        self.assertIn("희주 계좌 | 3주 × 78,500 KRW = 235,500 KRW", label)
        self.assertNotIn("BATCH3 ·", label)


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


class KoreanPriceFetcherTests(unittest.TestCase):
    @patch("src.price_fetcher.requests.get")
    def test_naver_mobile_price_supports_numeric_and_alphanumeric_codes(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"closePrice": "13,635"}
        mock_get.return_value = response

        self.assertEqual(fetch_kr_price_from_naver_mobile("0060H0"), 13635.0)
        self.assertIn("0060H0", mock_get.call_args.args[0])

    @patch("src.price_fetcher.requests.get")
    def test_naver_chart_price_reads_latest_close(self, mock_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.text = '<item data="20260710|13500|13800|13400|13635|100" />'
        mock_get.return_value = response

        self.assertEqual(fetch_kr_price_from_naver_chart("0060H0"), 13635.0)

    def test_failed_refresh_preserves_previous_price(self):
        latest = pd.DataFrame(
            [{"티커 또는 종목코드": "030190", "현재가": None, "USD/KRW": 0, "상태": "조회 실패"}]
        )
        previous = pd.DataFrame(
            [{"티커 또는 종목코드": "030190", "현재가": 13820.0, "USD/KRW": 1400.0, "상태": "정상"}]
        )

        result = app.preserve_previous_prices_on_failure(latest, previous)

        self.assertEqual(result.loc[0, "현재가"], 13820.0)
        self.assertEqual(result.loc[0, "상태"], "기존 저장가격 유지")

    def test_preserved_price_does_not_show_failure_warning(self):
        prices = pd.DataFrame(
            [{"티커 또는 종목코드": "0060H0", "현재가": 13635.0, "상태": "기존 저장가격 유지"}]
        )
        errors = [
            "0060H0 가격 조회에 실패했습니다. 국내 가격 데이터 없음",
            "VT 가격 조회에 실패했습니다. 티커가 올바른지 확인해주세요.",
        ]

        result = app.suppress_errors_for_preserved_prices(errors, prices)

        self.assertEqual(result, ["VT 가격 조회에 실패했습니다. 티커가 올바른지 확인해주세요."])


class BenchmarkAfterTaxReturnTests(unittest.TestCase):
    def test_cash_flow_adjusted_return_invests_each_contribution_on_next_trading_day(self):
        tr_index = pd.Series(
            [100.0, 110.0, 121.0],
            index=pd.to_datetime(["2025-12-31", "2026-01-02", "2026-01-05"]),
        )
        contributions = [("2025-12-31", 1_000.0), ("2026-01-01", 1_000.0)]

        result = calculate_cash_flow_adjusted_return_from_index(
            tr_index,
            contributions,
            tr_index.index,
        )

        expected_value = 1_000.0 * 121.0 / 100.0 + 1_000.0 * 121.0 / 110.0
        self.assertAlmostEqual(result, expected_value / 2_000.0 - 1)

    def test_dividend_after_tax_total_return_is_between_price_and_pretax_return(self):
        history = pd.DataFrame(
            {
                "Close": [100.0, 100.0, 102.0],
                "Dividends": [0.0, 10.0, 0.0],
            },
            index=pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-04"]),
        )

        tr = build_after_tax_total_return_index(history)
        price_return = history["Close"].iloc[-1] / history["Close"].iloc[0] - 1
        pretax_return = ((100.0 + 10.0) / 100.0) * (102.0 / 100.0) - 1
        after_tax_return = tr["after_tax_tr_index"].iloc[-1] - 1

        self.assertGreater(after_tax_return, price_return)
        self.assertLess(after_tax_return, pretax_return)
        self.assertAlmostEqual(after_tax_return, (1 + 10.0 * (1 - DIVIDEND_TAX_RATE) / 100.0) * 1.02 - 1)

    def test_no_dividend_total_return_matches_price_return(self):
        history = pd.DataFrame(
            {"Close": [200.0, 204.0, 210.0], "Dividends": [0.0, 0.0, 0.0]},
            index=pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-04"]),
        )

        tr = build_after_tax_total_return_index(history)
        self.assertAlmostEqual(tr["after_tax_tr_index"].iloc[-1] - 1, 210.0 / 200.0 - 1)

    def test_weighted_benchmark_compounds_daily_weighted_returns(self):
        returns = {
            "VT": pd.Series([0.0, 0.10, 0.00], index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"])),
            "BND": pd.Series([0.0, 0.00, 0.04], index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"])),
            "GLD": pd.Series([0.0, 0.02, 0.02], index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"])),
        }

        benchmark = build_weighted_benchmark_after_tax_tr(returns, {"VT": 0.6, "BND": 0.3, "GLD": 0.1})
        expected = (1 + 0.062) * (1 + 0.014) - 1
        self.assertAlmostEqual(benchmark["benchmark_after_tax_tr_index"].iloc[-1] - 1, expected)

    def test_calendar_year_return_uses_prior_year_end_baseline(self):
        tr_index = pd.Series(
            [1.00, 1.10, 1.21],
            index=pd.to_datetime(["2025-12-31", "2026-01-02", "2026-12-31"]),
        )

        self.assertAlmostEqual(calculate_calendar_year_return_from_index(tr_index, 2026), 0.21)

    def test_krw_adjusted_benchmark_reflects_usdkrw_change(self):
        usd_tr_index = pd.Series(
            [1.00, 1.10, 1.21],
            index=pd.to_datetime(["2025-12-31", "2026-01-02", "2026-12-31"]),
        )
        usdkrw = pd.Series(
            [1300.0, 1430.0, 1430.0],
            index=pd.to_datetime(["2025-12-31", "2026-01-02", "2026-12-31"]),
        )

        krw_benchmark = build_krw_adjusted_benchmark_tr(usd_tr_index, usdkrw)
        result = calculate_calendar_year_return_from_index(
            krw_benchmark["benchmark_after_tax_tr_krw_index"],
            2026,
        )

        self.assertAlmostEqual(result, (1.21 * 1430.0) / (1.00 * 1300.0) - 1)


if __name__ == "__main__":
    unittest.main()
