from __future__ import annotations

import os
import shutil
import sqlite3
import socket
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from uuid import uuid4

import pandas as pd

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
except Exception:
    pass


def apply_streamlit_secrets() -> None:
    """Apply Streamlit secrets over OS/.env values for cloud deployments."""
    try:
        import streamlit as st

        secrets = st.secrets
    except Exception:
        return

    for key in [
        "DATABASE_BACKEND",
        "DATABASE_URL",
        "SUPABASE_POOLER_DATABASE_URL",
        "SUPABASE_DIRECT_DATABASE_URL",
        "SUPABASE_PROJECT_URL",
        "APP_PASSWORD",
        "OPENAI_API_KEY",
        "OPENDART_API_KEY",
        "SEC_USER_AGENT",
        "SQLITE_DB_PATH",
    ]:
        try:
            value = secrets.get(key)
        except Exception:
            value = None
        if value is not None and str(value).strip():
            os.environ[key] = str(value).strip()


apply_streamlit_secrets()

from src.excel_manager import (
    DISCLOSURE_COLUMNS,
    DISCLOSURE_LOG_COLUMNS,
    DISCLOSURE_WATCHLIST_COLUMNS,
    default_settings,
    normalize_disclosure_logs,
    normalize_disclosure_watchlist,
    normalize_disclosures,
    normalize_settings,
    save_full_workbook,
)
from src.portfolio_calculator import (
    BUY_TRANSACTION_COLUMNS,
    PRICE_COLUMNS,
    SNAPSHOT_COLUMNS,
    TRANSACTION_COLUMNS,
    empty_capital_flows,
    empty_buy_transactions,
    empty_prices,
    empty_snapshots,
    empty_transactions,
    normalize_capital_flows,
    normalize_holdings,
    normalize_snapshots,
    sample_holdings,
)


APP_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = APP_DIR / "data"
EXPORTS_DIR = APP_DIR / "exports"
BACKUPS_DIR = APP_DIR / "backups"
DEFAULT_SQLITE_PATH = DATA_DIR / "portfolio.db"

TABLES = [
    "holdings",
    "prices",
    "transactions",
    "buy_transactions",
    "capital_flows",
    "portfolio_snapshots",
    "disclosures",
    "disclosure_logs",
    "disclosure_watchlist",
    "settings",
]

PUBLIC_API_ROLES = ("anon", "authenticated", "public")

TABLE_NORMALIZERS: dict[str, Callable[[pd.DataFrame | None], pd.DataFrame]] = {
    "holdings": normalize_holdings,
    "prices": lambda df: _ensure_columns(df, PRICE_COLUMNS),
    "transactions": lambda df: _ensure_columns(df, TRANSACTION_COLUMNS),
    "buy_transactions": lambda df: _ensure_columns(df, BUY_TRANSACTION_COLUMNS),
    "capital_flows": normalize_capital_flows,
    "portfolio_snapshots": normalize_snapshots,
    "disclosures": normalize_disclosures,
    "disclosure_logs": normalize_disclosure_logs,
    "disclosure_watchlist": normalize_disclosure_watchlist,
    "settings": normalize_settings,
}

EMPTY_TABLES: dict[str, pd.DataFrame] = {
    "holdings": sample_holdings(),
    "prices": empty_prices(),
    "transactions": empty_transactions(),
    "buy_transactions": empty_buy_transactions(),
    "capital_flows": empty_capital_flows(),
    "portfolio_snapshots": empty_snapshots(),
    "disclosures": pd.DataFrame(columns=DISCLOSURE_COLUMNS),
    "disclosure_logs": pd.DataFrame(columns=DISCLOSURE_LOG_COLUMNS),
    "disclosure_watchlist": pd.DataFrame(columns=DISCLOSURE_WATCHLIST_COLUMNS),
    "settings": default_settings(),
}

POSTGRES_COLUMN_MAP: dict[str, dict[str, str]] = {
    "holdings": {
        "표시순서": "display_order",
        "상위자산군": "major_asset_class",
        "세부자산군": "sub_asset_class",
        "자산군": "asset_class",
        "시장": "market",
        "티커 또는 종목코드": "symbol",
        "종목명": "name",
        "새빛_보유수량": "saebit_quantity",
        "희주_보유수량": "heeju_quantity",
        "합산_보유수량": "total_quantity",
        "보유수량": "quantity",
        "평균단가": "avg_price",
        "통화": "currency",
        "메모": "memo",
    },
    "prices": {
        "티커 또는 종목코드": "symbol",
        "현재가": "current_price",
        "통화": "currency",
        "USD/KRW": "usd_krw",
        "마지막 가격 업데이트 시각": "last_price_updated_at",
        "상태": "status",
    },
    "transactions": {
        "거래일시": "trade_datetime",
        "거래유형": "trade_type",
        "계좌": "account",
        "상위자산군": "major_asset_class",
        "세부자산군": "sub_asset_class",
        "자산군": "asset_class",
        "시장": "market",
        "티커 또는 종목코드": "symbol",
        "종목명": "name",
        "매수수량": "quantity",
        "매수단가": "price",
        "매수금액": "amount",
        "통화": "currency",
        "메모": "memo",
        "반영 후 새빛_보유수량": "after_saebit_quantity",
        "반영 후 희주_보유수량": "after_heeju_quantity",
        "반영 후 합산_보유수량": "after_total_quantity",
        "반영 후 보유수량": "after_quantity",
        "반영 후 평균단가": "after_avg_price",
    },
    "buy_transactions": {
        "거래ID": "id",
        "일괄반영ID": "batch_id",
        "자산ID": "asset_id",
        "티커": "ticker",
        "종목명": "asset_name",
        "계좌": "account",
        "수량": "quantity",
        "단가": "unit_price",
        "금액": "amount",
        "통화": "currency",
        "메모": "memo",
        "생성일시": "created_at",
        "되돌림여부": "is_reverted",
        "되돌림일시": "reverted_at",
        "되돌림사유": "revert_reason",
    },
    "capital_flows": {
        "일시": "flow_datetime",
        "유형": "flow_type",
        "금액": "amount",
        "통화": "currency",
        "메모": "memo",
        "반영 후 투자원금": "after_principal",
    },
    "portfolio_snapshots": {
        "날짜시간": "snapshot_datetime",
        "연도": "year",
        "스냅샷유형": "snapshot_type",
        "총평가금액": "total_value",
        "투자원금": "principal",
        "평가손익": "profit_loss",
        "누적수익률": "cumulative_return",
        "메모": "memo",
    },
    "disclosures": {
        "저장일시": "saved_at",
        "시장": "market",
        "티커_또는_종목코드": "symbol",
        "종목명": "name",
        "공시일": "disclosure_date",
        "공시유형": "disclosure_type",
        "공시제목": "title",
        "공시원문URL": "source_url",
        "공시ID": "disclosure_id",
        "요약": "summary",
        "중요도": "importance",
        "처리상태": "status",
    },
    "disclosure_logs": {
        "실행일시": "run_datetime",
        "조회모드": "query_mode",
        "조회시작일": "start_date",
        "조회종료일": "end_date",
        "조회대상종목수": "target_count",
        "조회대상종목목록": "target_symbols",
        "성공종목수": "success_count",
        "실패종목수": "failure_count",
        "조회된공시수": "fetched_count",
        "신규저장공시수": "new_saved_count",
        "중복제외공시수": "duplicate_count",
        "필터후표시공시수": "filtered_count",
        "오류메시지": "error_message",
        "상세로그": "detail_log",
    },
    "disclosure_watchlist": {
        "시장": "market",
        "티커_또는_종목코드": "symbol",
        "종목명": "name",
        "추적상태": "tracking_status",
        "추가방식": "add_method",
        "추가일시": "added_at",
        "메모": "memo",
    },
    "settings": {
        "설정": "setting_key",
        "값": "setting_value",
    },
}


def database_backend() -> str:
    return os.getenv("DATABASE_BACKEND", "supabase").strip().lower() or "supabase"


def sqlite_path() -> Path:
    raw_path = os.getenv("SQLITE_DB_PATH", "data/portfolio.db").strip() or "data/portfolio.db"
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = APP_DIR / path
    return path.resolve()


def get_database_url(backend: str | None = None) -> str:
    selected = (backend or database_backend()).lower()
    if selected == "sqlite":
        return f"sqlite:///{sqlite_path().as_posix()}"
    if selected == "supabase":
        url = os.getenv("SUPABASE_POOLER_DATABASE_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()
        if not url:
            raise ValueError(
                "DATABASE_BACKEND=supabase 이지만 SUPABASE_POOLER_DATABASE_URL과 DATABASE_URL이 비어 있습니다. "
                "Streamlit Cloud의 App settings > Secrets에 기존 Supabase pooler URL을 넣어야 이전 데이터가 보입니다."
            )
        return _normalize_postgres_url(url)
    raise ValueError("DATABASE_BACKEND는 sqlite 또는 supabase만 지원합니다.")


def get_engine(backend: str | None = None):
    url = get_database_url(backend)
    import sqlalchemy as sa

    return sa.create_engine(url, pool_pre_ping=True, future=True)


def is_sqlite() -> bool:
    return database_backend() == "sqlite"


def is_supabase() -> bool:
    return database_backend() == "supabase"


def initialize_database() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    if is_supabase():
        get_database_url("supabase")
        return
    if is_sqlite():
        sqlite_path().parent.mkdir(parents=True, exist_ok=True)
    for table_name, empty_df in EMPTY_TABLES.items():
        if table_exists(table_name):
            continue
        write_table(table_name, empty_df)


def table_exists(table_name: str, backend: str | None = None) -> bool:
    _validate_table(table_name)
    selected = backend or database_backend()
    if selected == "sqlite":
        path = sqlite_path()
        if not path.exists():
            return False
        with sqlite3.connect(path) as conn:
            result = conn.execute(
                "select name from sqlite_master where type='table' and name=?",
                (table_name,),
            ).fetchone()
        return result is not None
    engine = get_engine(backend)
    try:
        import sqlalchemy as sa

        return sa.inspect(engine).has_table(table_name)
    finally:
        engine.dispose()


def read_table(table_name: str) -> pd.DataFrame:
    return read_table_from_backend(table_name, database_backend())


def read_tables(table_names: list[str] | tuple[str, ...]) -> dict[str, pd.DataFrame]:
    selected = database_backend()
    for table_name in table_names:
        _validate_table(table_name)
    if selected == "sqlite":
        return {table_name: read_table_from_backend(table_name, selected) for table_name in table_names}

    engine = get_engine(selected)
    result: dict[str, pd.DataFrame] = {}
    try:
        for table_name in table_names:
            try:
                df = pd.read_sql_query(f'select * from "{table_name}"', engine)
            except Exception as exc:
                if "does not exist" in str(exc).lower() or "undefinedtable" in str(exc).lower():
                    result[table_name] = EMPTY_TABLES[table_name].copy()
                    continue
                raise
            df = _from_storage_columns(table_name, df, selected)
            df = _drop_metadata_columns(df)
            result[table_name] = TABLE_NORMALIZERS[table_name](df)
    finally:
        engine.dispose()
    return result


def read_table_from_backend(table_name: str, backend: str) -> pd.DataFrame:
    _validate_table(table_name)
    if backend == "sqlite":
        if not table_exists(table_name, backend):
            return EMPTY_TABLES[table_name].copy()
        with sqlite3.connect(sqlite_path()) as conn:
            df = pd.read_sql_query(f'select * from "{table_name}"', conn)
        return TABLE_NORMALIZERS[table_name](_drop_metadata_columns(df))
    engine = get_engine(backend)
    try:
        df = pd.read_sql_query(f'select * from "{table_name}"', engine)
    except Exception as exc:
        if "does not exist" in str(exc).lower() or "undefinedtable" in str(exc).lower():
            return EMPTY_TABLES[table_name].copy()
        raise
    finally:
        engine.dispose()
    df = _from_storage_columns(table_name, df, backend)
    df = _drop_metadata_columns(df)
    return TABLE_NORMALIZERS[table_name](df)


def write_table(table_name: str, df: pd.DataFrame | None) -> None:
    write_table_to_backend(table_name, df, database_backend(), replace=True)


def write_table_to_backend(table_name: str, df: pd.DataFrame | None, backend: str, replace: bool = True) -> None:
    _validate_table(table_name)
    normalized = TABLE_NORMALIZERS[table_name](df)
    normalized = normalized.where(pd.notna(normalized), "")
    if backend == "sqlite":
        sqlite_path().parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(sqlite_path()) as conn:
            normalized.to_sql(table_name, conn, if_exists="replace" if replace else "append", index=False)
        return
    engine = get_engine(backend)
    try:
        try:
            existing_columns = _table_columns(engine, table_name)
        except Exception:
            storage = _to_storage_columns(table_name, normalized, backend)
            storage = storage.replace({"": None})
            storage = _with_timestamps(storage, replace=replace, backend=backend, existing_columns=None)
            storage.to_sql(table_name, engine, if_exists="replace", index=False)
            _protect_supabase_table(engine, table_name)
            return
        storage = _to_existing_table_columns(table_name, normalized, backend, existing_columns)
        storage = storage.replace({"": None})
        storage = _with_timestamps(storage, replace=replace, backend=backend, existing_columns=existing_columns)
        if replace:
            with engine.begin() as conn:
                conn.exec_driver_sql(f'delete from "{table_name}"')
        if not storage.empty:
            storage.to_sql(table_name, engine, if_exists="append", index=False)
    finally:
        engine.dispose()


def append_rows(table_name: str, rows: pd.DataFrame) -> None:
    _validate_table(table_name)
    if rows is None or rows.empty:
        return
    append_rows_to_backend(table_name, rows, database_backend())


def append_rows_to_backend(table_name: str, rows: pd.DataFrame, backend: str) -> None:
    normalized = TABLE_NORMALIZERS[table_name](rows)
    normalized = normalized.where(pd.notna(normalized), "")
    if backend == "sqlite":
        sqlite_path().parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(sqlite_path()) as conn:
            normalized.to_sql(table_name, conn, if_exists="append", index=False)
        return
    engine = get_engine(backend)
    try:
        existing_columns = _table_columns(engine, table_name) if table_exists(table_name, backend) else None
        if existing_columns is None:
            storage = _to_storage_columns(table_name, normalized, backend)
        else:
            storage = _to_existing_table_columns(table_name, normalized, backend, existing_columns)
        storage = storage.replace({"": None})
        storage = _with_timestamps(storage, replace=False, backend=backend, existing_columns=existing_columns)
        storage.to_sql(table_name, engine, if_exists="append", index=False)
    finally:
        engine.dispose()


def backup_database(reason: str = "manual") -> Path | None:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    if is_sqlite():
        source = sqlite_path()
        if not source.exists():
            return None
        target = BACKUPS_DIR / f"portfolio_db_{reason}_{datetime.now():%Y%m%d_%H%M%S}.db"
        shutil.copy2(source, target)
        return target
    if str(os.getenv("ENABLE_SUPABASE_EXCEL_BACKUP", "")).strip().lower() not in {"1", "true", "yes", "y", "on"}:
        return None
    target = BACKUPS_DIR / f"portfolio_db_{reason}_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    export_excel(target)
    return target


def import_excel(excel_path: Path) -> dict[str, int]:
    report = import_excel_to_current_backend(excel_path, mode="replace")
    return {table: values["imported"] for table, values in report.items()}


def find_pc_portfolio_excels() -> list[Path]:
    candidates = [
        APP_DIR.parent / "portfolio.xlsx",
        APP_DIR.parent / "data" / "portfolio.xlsx",
        APP_DIR / "portfolio.xlsx",
        APP_DIR / "data" / "portfolio.xlsx",
    ]
    found: list[Path] = []
    for candidate in candidates:
        if candidate.exists() and candidate.resolve() not in [path.resolve() for path in found]:
            found.append(candidate.resolve())
    return found


def preview_excel(excel_path: Path) -> dict[str, dict[str, object]]:
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel 파일을 찾을 수 없습니다: {excel_path}")
    workbook = pd.ExcelFile(excel_path)
    preview: dict[str, dict[str, object]] = {}
    for table_name in TABLES:
        if table_name not in workbook.sheet_names:
            preview[table_name] = {"exists": False, "rows": 0, "columns": []}
            continue
        df = pd.read_excel(excel_path, sheet_name=table_name, nrows=5)
        preview[table_name] = {"exists": True, "rows": _sheet_row_count(excel_path, table_name), "columns": list(df.columns)}
    return preview


def import_excel_to_current_backend(excel_path: Path, mode: str = "replace") -> dict[str, dict[str, object]]:
    return import_excel_to_backend(excel_path, database_backend(), mode)


def import_excel_to_backend(excel_path: Path, backend: str, mode: str = "replace") -> dict[str, dict[str, object]]:
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel 파일을 찾을 수 없습니다: {excel_path}")
    backup_database("before_pc_excel_import")
    imported: dict[str, int] = {}
    report: dict[str, dict[str, object]] = {}
    sheets = pd.ExcelFile(excel_path).sheet_names
    for table_name in TABLES:
        if table_name not in sheets:
            report[table_name] = {"imported": 0, "status": "시트 없음"}
            continue
        dtype = str if table_name in {"settings", "disclosures", "disclosure_logs", "disclosure_watchlist"} else None
        df = pd.read_excel(excel_path, sheet_name=table_name, dtype=dtype)
        df = _harmonize_excel_columns(table_name, df)
        normalized = TABLE_NORMALIZERS[table_name](df)
        if table_name == "holdings":
            normalized = _prepare_import_holdings(normalized)
        if mode == "append":
            current = read_table_from_backend(table_name, backend)
            combined = pd.concat([current, normalized], ignore_index=True) if not current.empty else normalized
            normalized = _dedupe_rows(table_name, combined)
        write_table_to_backend(table_name, normalized, backend, replace=True)
        imported[table_name] = len(normalized)
        report[table_name] = {"imported": len(normalized), "status": "가져옴"}
    return report


def export_excel(target_path: Path | None = None) -> Path:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    target = target_path or EXPORTS_DIR / f"portfolio_export_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    holdings = read_table("holdings")
    prices = read_table("prices")
    from src.portfolio_calculator import calculate_portfolio

    calculated = calculate_portfolio(holdings, prices)
    save_full_workbook(
        workbook_path=target,
        holdings=holdings,
        prices=prices,
        calculated=calculated,
        settings=read_table("settings"),
        transactions=read_table("transactions"),
        capital_flows=read_table("capital_flows"),
        snapshots=read_table("portfolio_snapshots"),
        disclosures=read_table("disclosures"),
        disclosure_logs=read_table("disclosure_logs"),
        disclosure_watchlist=read_table("disclosure_watchlist"),
        create_backup=False,
    )
    return target


def test_supabase_connection() -> tuple[bool, str]:
    if database_backend() != "supabase":
        return False, "DATABASE_BACKEND가 supabase가 아닙니다."
    diagnostics = supabase_connection_diagnostics()
    try:
        import sqlalchemy as sa

        engine = get_engine("supabase")
        try:
            with engine.connect() as conn:
                conn.execute(sa.text("select 1"))
            return True, _format_connection_message(diagnostics, postgresql_ok=True)
        finally:
            engine.dispose()
    except Exception as exc:
        return False, _format_connection_message(diagnostics, postgresql_ok=False, error=exc)


def upload_sqlite_to_supabase(mode: str = "append") -> dict[str, int]:
    if not active_supabase_url():
        raise ValueError("Supabase 업로드를 위해 SUPABASE_POOLER_DATABASE_URL 또는 DATABASE_URL을 설정해야 합니다.")
    ok, message = test_supabase_connection_with_url()
    if not ok:
        raise RuntimeError(message)
    uploaded: dict[str, int] = {}
    for table_name in TABLES:
        source = read_table_from_backend(table_name, "sqlite")
        if mode == "replace":
            write_table_to_backend(table_name, source, "supabase", replace=True)
            uploaded[table_name] = len(source)
            continue
        target = read_table_from_backend(table_name, "supabase")
        combined = pd.concat([target, source], ignore_index=True) if not target.empty else source
        combined = _dedupe_rows(table_name, combined)
        write_table_to_backend(table_name, combined, "supabase", replace=True)
        uploaded[table_name] = len(source)
    return uploaded


def test_supabase_connection_with_url() -> tuple[bool, str]:
    diagnostics = supabase_connection_diagnostics()
    try:
        import sqlalchemy as sa

        engine = get_engine("supabase")
        try:
            with engine.connect() as conn:
                conn.execute(sa.text("select 1"))
            return True, _format_connection_message(diagnostics, postgresql_ok=True)
        finally:
            engine.dispose()
    except Exception as exc:
        return False, _format_connection_message(diagnostics, postgresql_ok=False, error=exc)


def test_supabase_direct_connection() -> tuple[bool, str]:
    diagnostics = supabase_connection_diagnostics(use_direct=True)
    try:
        import sqlalchemy as sa

        engine = get_engine_for_url(diagnostics["url"])
        try:
            with engine.connect() as conn:
                conn.execute(sa.text("select 1"))
            return True, _format_connection_message(diagnostics, postgresql_ok=True)
        finally:
            engine.dispose()
    except Exception as exc:
        return False, _format_connection_message(diagnostics, postgresql_ok=False, error=exc)


def run_supabase_schema(schema_path: Path | None = None) -> tuple[bool, str]:
    ok, message = test_supabase_connection_with_url()
    if not ok:
        return False, message
    path = schema_path or APP_DIR / "db" / "schema_supabase.sql"
    if not path.exists():
        return False, f"Supabase schema 파일을 찾을 수 없습니다: {path}"
    sql = path.read_text(encoding="utf-8")
    try:
        engine = get_engine("supabase")
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(sql)
            return True, "Supabase 테이블 생성/점검 완료"
        finally:
            engine.dispose()
    except Exception as exc:
        return False, f"Supabase schema 실행 실패: {exc}"


def _protect_supabase_table(engine, table_name: str) -> None:
    _validate_table(table_name)
    roles = ", ".join(PUBLIC_API_ROLES)
    with engine.begin() as conn:
        conn.exec_driver_sql(f'alter table "{table_name}" enable row level security')
        conn.exec_driver_sql(f'revoke all on table "{table_name}" from {roles}')
        conn.exec_driver_sql(f"revoke all on all sequences in schema public from {roles}")


def get_engine_for_url(url: str):
    import sqlalchemy as sa

    return sa.create_engine(_normalize_postgres_url(url), pool_pre_ping=True, future=True)


def db_label() -> str:
    backend = database_backend()
    if backend == "sqlite":
        return f"SQLite: {sqlite_path()}"
    raw = active_supabase_url()
    masked = mask_database_url(raw) if raw else "Supabase URL 미설정"
    return f"Supabase PostgreSQL: {masked}"


def active_supabase_url() -> str:
    return os.getenv("SUPABASE_POOLER_DATABASE_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()


def supabase_connection_diagnostics(use_direct: bool = False) -> dict[str, object]:
    url = os.getenv("SUPABASE_DIRECT_DATABASE_URL", "").strip() if use_direct else active_supabase_url()
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or 5432
    connection_type = "direct" if use_direct else ("pooler" if "pooler.supabase.com" in host else "database_url")
    dns_ok = False
    dns_error = ""
    if host:
        try:
            socket.getaddrinfo(host, port)
            dns_ok = True
        except Exception as exc:
            dns_error = str(exc)
    return {
        "backend": database_backend(),
        "connection_type": connection_type,
        "host": host,
        "port": port,
        "dns_ok": dns_ok,
        "dns_error": dns_error,
        "url": url,
        "masked_url": mask_database_url(url),
    }


def mask_database_url(url: str) -> str:
    if not url:
        return "미설정"
    if "@" not in url:
        return url[:12] + "..." if len(url) > 12 else "***"
    prefix, suffix = url.rsplit("@", 1)
    scheme = prefix.split("://", 1)[0] if "://" in prefix else "postgresql"
    return f"{scheme}://****@{suffix}"


def _format_connection_message(diagnostics: dict[str, object], postgresql_ok: bool, error: Exception | None = None) -> str:
    lines = [
        "Supabase PostgreSQL 연결 성공" if postgresql_ok else "Supabase 연결 실패. Supabase URL, DB 비밀번호, 네트워크 상태를 확인하세요.",
        f"DATABASE_BACKEND: {diagnostics.get('backend')}",
        f"사용 중인 연결 종류: {diagnostics.get('connection_type')}",
        f"사용 중인 host: {diagnostics.get('host')}",
        f"사용 중인 port: {diagnostics.get('port')}",
        f"DNS 해석: {'성공' if diagnostics.get('dns_ok') else '실패'}",
        f"PostgreSQL 연결: {'성공' if postgresql_ok else '실패'}",
    ]
    if diagnostics.get("dns_error"):
        lines.append(f"DNS 오류: {diagnostics.get('dns_error')}")
    if error is not None:
        lines.append(f"오류 원인: {error}")
    return "\n".join(lines)


def _ensure_columns(df: pd.DataFrame | None, columns: list[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=columns)
    normalized = df.copy()
    for column in columns:
        if column not in normalized.columns:
            normalized[column] = ""
    return normalized[columns]


def _validate_table(table_name: str) -> None:
    if table_name not in EMPTY_TABLES:
        raise ValueError(f"지원하지 않는 테이블입니다: {table_name}")


def _to_storage_columns(table_name: str, df: pd.DataFrame, backend: str) -> pd.DataFrame:
    if backend == "sqlite":
        return df.copy()
    mapping = _storage_mapping(table_name, df.columns)
    return df.rename(columns=mapping)


def _to_existing_table_columns(table_name: str, df: pd.DataFrame, backend: str, existing_columns: set[str]) -> pd.DataFrame:
    if backend == "sqlite":
        return df.copy()
    mapped = _to_storage_columns(table_name, df, backend)
    mapped_required = {column for column in mapped.columns if column not in {"created_at", "updated_at"}}
    original_required = {column for column in df.columns if column not in {"created_at", "updated_at"}}
    if mapped_required and mapped_required.issubset(existing_columns):
        selected = mapped
    elif original_required and original_required.issubset(existing_columns):
        selected = df
    else:
        mapped_overlap = len(mapped_required.intersection(existing_columns))
        original_overlap = len(original_required.intersection(existing_columns))
        selected = mapped if mapped_overlap >= original_overlap else df
    keep_columns = [column for column in selected.columns if column in existing_columns]
    return selected[keep_columns].copy()


def _table_columns(engine, table_name: str) -> set[str]:
    import sqlalchemy as sa

    inspector = sa.inspect(engine)
    return {str(column["name"]) for column in inspector.get_columns(table_name)}


def _from_storage_columns(table_name: str, df: pd.DataFrame, backend: str) -> pd.DataFrame:
    if backend == "sqlite":
        return df.copy()
    mapping = _storage_mapping(table_name, EMPTY_TABLES[table_name].columns)
    reverse = {value: key for key, value in mapping.items()}
    renamed = df.rename(columns=reverse)
    return _coalesce_duplicate_columns(renamed)


def _storage_mapping(table_name: str, columns) -> dict[str, str]:
    explicit = POSTGRES_COLUMN_MAP.get(table_name, {})
    mapping: dict[str, str] = {}
    for column in columns:
        if column in explicit:
            mapping[column] = explicit[column]
        else:
            mapping[column] = str(column).replace(" ", "_").replace("/", "_").lower() if _is_ascii(str(column)) else str(column).replace(" ", "_")
    return mapping


def _is_ascii(value: str) -> bool:
    try:
        value.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _drop_metadata_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop(columns=[c for c in ["id", "created_at", "updated_at"] if c in df.columns], errors="ignore")


def _coalesce_duplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    if not df.columns.has_duplicates:
        return df
    output = pd.DataFrame(index=df.index)
    for column in dict.fromkeys(df.columns):
        same_name = df.loc[:, df.columns == column]
        if same_name.shape[1] == 1:
            output[column] = same_name.iloc[:, 0]
        else:
            output[column] = same_name.bfill(axis=1).iloc[:, 0]
    return output


def _with_timestamps(df: pd.DataFrame, replace: bool, backend: str, existing_columns: set[str] | None = None) -> pd.DataFrame:
    if backend == "sqlite" or df.empty:
        return df
    output = df.copy()
    now = datetime.now().isoformat(timespec="seconds")
    can_write_created = existing_columns is None or "created_at" in existing_columns
    can_write_updated = existing_columns is None or "updated_at" in existing_columns
    if can_write_created and "created_at" in output.columns and not replace:
        output["created_at"] = output["created_at"].replace("", now).fillna(now)
    elif can_write_created and "created_at" not in output.columns:
        output["created_at"] = now
    if can_write_updated:
        output["updated_at"] = now
    return output


def _dedupe_rows(table_name: str, df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    keys_by_table = {
        "holdings": ["row_id"],
        "settings": ["설정"],
        "prices": ["티커 또는 종목코드"],
        "transactions": ["거래일시", "계좌", "티커 또는 종목코드", "매수수량", "매수단가"],
        "buy_transactions": ["거래ID"],
        "capital_flows": ["일시", "유형", "금액", "메모"],
        "portfolio_snapshots": ["날짜시간", "스냅샷유형"],
        "disclosures": ["공시ID"],
        "disclosure_logs": ["실행일시"],
        "disclosure_watchlist": ["시장", "티커_또는_종목코드"],
    }
    keys = [key for key in keys_by_table.get(table_name, []) if key in df.columns]
    if not keys:
        return df.drop_duplicates(keep="last").reset_index(drop=True)
    non_empty = df[keys].astype(str).agg("|".join, axis=1).str.strip("|") != ""
    deduped = pd.concat(
        [
            df[non_empty].drop_duplicates(subset=keys, keep="last"),
            df[~non_empty],
        ],
        ignore_index=True,
    )
    return deduped.reset_index(drop=True)


def _sheet_row_count(excel_path: Path, sheet_name: str) -> int:
    try:
        return int(len(pd.read_excel(excel_path, sheet_name=sheet_name, usecols=[0])))
    except Exception:
        return 0


def _harmonize_excel_columns(table_name: str, df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    output = df.copy()
    rename_candidates = {
        "holdings": {
            "티커_또는_종목코드": "티커 또는 종목코드",
            "티커": "티커 또는 종목코드",
            "종목코드": "티커 또는 종목코드",
            "major_asset_class": "상위자산군",
            "sub_asset_class": "세부자산군",
            "market": "시장",
            "symbol": "티커 또는 종목코드",
            "name": "종목명",
            "saebit_quantity": "새빛_보유수량",
            "heeju_quantity": "희주_보유수량",
            "total_quantity": "합산_보유수량",
            "avg_price": "평균단가",
            "currency": "통화",
            "memo": "메모",
        },
        "transactions": {
            "매수계좌": "계좌",
            "account": "계좌",
            "trade_datetime": "거래일시",
            "trade_type": "거래유형",
            "티커_또는_종목코드": "티커 또는 종목코드",
            "symbol": "티커 또는 종목코드",
            "name": "종목명",
            "quantity": "매수수량",
            "price": "매수단가",
            "amount": "매수금액",
            "currency": "통화",
            "memo": "메모",
            "after_saebit_quantity": "반영 후 새빛_보유수량",
            "after_heeju_quantity": "반영 후 희주_보유수량",
            "after_total_quantity": "반영 후 합산_보유수량",
            "after_avg_price": "반영 후 평균단가",
        },
        "prices": {
            "티커_또는_종목코드": "티커 또는 종목코드",
            "symbol": "티커 또는 종목코드",
            "current_price": "현재가",
            "currency": "통화",
            "usd_krw": "USD/KRW",
            "last_price_updated_at": "마지막 가격 업데이트 시각",
            "status": "상태",
        },
        "settings": {"setting_key": "설정", "setting_value": "값"},
        "capital_flows": {
            "flow_datetime": "일시",
            "flow_type": "유형",
            "amount": "금액",
            "currency": "통화",
            "memo": "메모",
            "after_principal": "반영 후 투자원금",
        },
        "disclosure_watchlist": {
            "symbol": "티커_또는_종목코드",
            "market": "시장",
            "name": "종목명",
            "tracking_status": "추적상태",
            "add_method": "추가방식",
            "added_at": "추가일시",
            "memo": "메모",
        },
        "disclosures": {
            "symbol": "티커_또는_종목코드",
            "market": "시장",
            "name": "종목명",
            "source_url": "공시원문URL",
            "disclosure_id": "공시ID",
        },
    }
    rename_map = {
        source: target
        for source, target in rename_candidates.get(table_name, {}).items()
        if source in output.columns and target not in output.columns
    }
    if rename_map:
        output = output.rename(columns=rename_map)
    return output


def _prepare_import_holdings(df: pd.DataFrame) -> pd.DataFrame:
    holdings = normalize_holdings(df)
    if "row_id" not in holdings.columns:
        holdings["row_id"] = ""
    missing_row_id = holdings["row_id"].fillna("").astype(str).str.strip() == ""
    holdings.loc[missing_row_id, "row_id"] = [str(uuid4()) for _ in range(int(missing_row_id.sum()))]
    if "sort_order" not in holdings.columns:
        holdings["sort_order"] = holdings["표시순서"] if "표시순서" in holdings.columns else range(1, len(holdings) + 1)
    if "표시순서" not in holdings.columns:
        holdings["표시순서"] = holdings["sort_order"]
    holdings["새빛_보유수량"] = holdings["새빛_보유수량"].map(_parse_number_safe)
    holdings["희주_보유수량"] = holdings["희주_보유수량"].map(_parse_number_safe)
    holdings["합산_보유수량"] = holdings["새빛_보유수량"] + holdings["희주_보유수량"]
    holdings["보유수량"] = holdings["합산_보유수량"]
    return normalize_holdings(holdings)


def _parse_number_safe(value) -> float:
    from src.formatters import parse_number

    return parse_number(value)


def _normalize_postgres_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://") :]
    return url


if __name__ == "__main__":
    initialize_database()
    print(f"DB initialized: {db_label()}")
