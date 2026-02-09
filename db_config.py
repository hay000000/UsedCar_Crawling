#!/usr/bin/env python3
"""
DB 연결 정보만 정의합니다.
쿼리·테이블명·조회 로직은 crawl_heydealer.py에서 직접 작성하세요.

DB 호스트 등은 아래 둘 중 편한 쪽에 적으면 됩니다.
  1) 프로젝트 폴더의 .env 파일 (이 파일과 같은 폴더에 .env 생성)
  2) 터미널에서 export DB_HOST=172.22.208.1 후 실행
"""

import os
from pathlib import Path

# 프로젝트 폴더의 .env 또는 .env.example 로드 (.env 없으면 .env.example 사용)
_conf_dir = Path(__file__).resolve().parent
for _env_name in (".env", ".env.example"):
    _env_path = _conf_dir / _env_name
    if _env_path.exists():
        with open(_env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key, value = key.strip(), value.strip()
                    if key and key not in os.environ:
                        os.environ[key] = value
        break

# --- 연결 정보 (.env 또는 환경 변수, 없으면 기본값) ---
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "15432"))
DB_NAME = os.environ.get("DB_NAME", "postgres")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "5815")


def get_db_connection():
    """PostgreSQL 연결 반환. 연결 정보는 위 설정값 사용."""
    import psycopg2
    print(f"   DB 연결 시도: host={DB_HOST} port={DB_PORT}")
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )
