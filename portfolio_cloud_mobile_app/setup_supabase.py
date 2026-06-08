from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
ENV_PATH = APP_DIR / ".env"
SCHEMA_PATH = APP_DIR / "db" / "schema_supabase.sql"


def env_value(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def main() -> int:
    os.chdir(APP_DIR)
    env_values = build_env_values()
    write_env(env_values)
    print(".env 설정 완료")
    os.environ.update(env_values)
    if not env_values["SUPABASE_POOLER_DATABASE_URL"] and not env_values["DATABASE_URL"]:
        print("SUPABASE_POOLER_DATABASE_URL 또는 DATABASE_URL을 먼저 설정하세요.")
        return 1
    ensure_packages()

    from src import db

    diagnostics = db.supabase_connection_diagnostics()
    print(f"사용 중인 연결 종류: {diagnostics['connection_type']}")
    print(f"사용 중인 host: {diagnostics['host']}")
    if diagnostics["connection_type"] != "pooler":
        print("Pooler 연결이 아닙니다. Streamlit Cloud에서는 pooler URL 사용을 권장합니다.")

    ok, message = db.test_supabase_connection_with_url()
    if not ok:
        print("Supabase 연결 실패.")
        print("DATABASE_URL, DB 비밀번호, 네트워크 상태, Supabase 프로젝트 상태를 확인하세요.")
        print(message)
        return 1
    print("Supabase PostgreSQL 연결 성공")

    ok, schema_message = db.run_supabase_schema(SCHEMA_PATH)
    if not ok:
        print(schema_message)
        return 1
    print(schema_message)
    print("필요 테이블 생성 또는 점검 완료")
    return 0


def build_env_values() -> dict[str, str]:
    existing = read_env()
    return {
        "DATABASE_BACKEND": env_value("DATABASE_BACKEND", existing.get("DATABASE_BACKEND", "supabase")) or "supabase",
        "SQLITE_DB_PATH": env_value("SQLITE_DB_PATH", existing.get("SQLITE_DB_PATH", "data/portfolio.db")) or "data/portfolio.db",
        "DATABASE_URL": env_value("DATABASE_URL", existing.get("DATABASE_URL", "")),
        "SUPABASE_POOLER_DATABASE_URL": env_value("SUPABASE_POOLER_DATABASE_URL", existing.get("SUPABASE_POOLER_DATABASE_URL", "")),
        "SUPABASE_DIRECT_DATABASE_URL": env_value("SUPABASE_DIRECT_DATABASE_URL", existing.get("SUPABASE_DIRECT_DATABASE_URL", "")),
        "SUPABASE_PROJECT_URL": env_value("SUPABASE_PROJECT_URL", existing.get("SUPABASE_PROJECT_URL", "")),
        "OPENAI_API_KEY": env_value("OPENAI_API_KEY", existing.get("OPENAI_API_KEY", "")),
        "OPENDART_API_KEY": env_value("OPENDART_API_KEY", existing.get("OPENDART_API_KEY", "")),
        "SEC_USER_AGENT": env_value(
            "SEC_USER_AGENT",
            existing.get("SEC_USER_AGENT", "Personal Portfolio Disclosure Tracker your_email@example.com"),
        ),
    }


def write_env(values: dict[str, str]) -> None:
    lines = [
        f"{key}={values.get(key, '')}"
        for key in [
            "DATABASE_BACKEND",
            "SQLITE_DB_PATH",
            "DATABASE_URL",
            "SUPABASE_POOLER_DATABASE_URL",
            "SUPABASE_DIRECT_DATABASE_URL",
            "SUPABASE_PROJECT_URL",
            "OPENAI_API_KEY",
            "OPENDART_API_KEY",
            "SEC_USER_AGENT",
        ]
    ]
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    values: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def ensure_packages() -> None:
    missing = []
    for module_name, package_name in [("sqlalchemy", "SQLAlchemy"), ("psycopg2", "psycopg2-binary"), ("dotenv", "python-dotenv")]:
        try:
            __import__(module_name)
        except ImportError:
            missing.append(package_name)
    if not missing:
        return
    print("필요 패키지 설치:", ", ".join(missing))
    subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])


if __name__ == "__main__":
    raise SystemExit(main())
