# -*- coding: utf-8 -*-
"""
중고차 크롤러 공통 설정 (이미지 저장 경로 등).
사이트명만 다르고 경로 패턴은 동일: imgs/{사이트}/{list|detail}/{연도}년/{YYYYMMDD}
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# 이미지 경로에 쓰는 사이트 목록 (여기만 추가하면 list/detail 경로 자동 생성)
IMAGE_SITES = ("heydealer", "reborncar", "kcar", "autoinside", "lotterentacar", "hyundaicar")

# 사이트별 리스트/상세 이미지 상대 경로 (공통 패턴: imgs/{site}/list, imgs/{site}/detail)
IMG_LIST_REL = {site: f"imgs/{site}/list" for site in IMAGE_SITES}
IMG_DETAIL_REL = {site: f"imgs/{site}/detail" for site in IMAGE_SITES}


def get_image_rel(site: str, kind: str) -> str:
    """사이트·종류별 이미지 상대 경로 prefix (연도/날짜 제외). kind는 'list' 또는 'detail'."""
    rel_map = IMG_LIST_REL if kind == "list" else IMG_DETAIL_REL
    return rel_map.get(site, f"imgs/{site}/{kind}")


def get_list_image_rel(site: str) -> str:
    """사이트별 리스트 이미지 상대 경로 prefix (연도/날짜 제외)."""
    return get_image_rel(site, "list")


def get_detail_image_rel(site: str) -> str:
    """사이트별 상세 이미지 상대 경로 prefix (연도/날짜 제외)."""
    return get_image_rel(site, "detail")


def get_image_save_dir(site: str, kind: str, date=None) -> Path:
    """사이트·종류별 이미지 저장 디렉터리 (연도년/YYYYMMDD 포함). kind는 'list' 또는 'detail'."""
    from datetime import datetime
    dt = date or datetime.now()
    rel = get_image_rel(site, kind)
    return PROJECT_ROOT / rel / f"{dt.year}년" / dt.strftime("%Y%m%d")


def get_list_image_base_dir(site: str) -> Path:
    """사이트별 리스트 이미지 부모 디렉터리 (imgs/heydealer 등). 절대 경로."""
    return (PROJECT_ROOT / get_image_rel(site, "list")).parent


def get_list_image_save_dir(site: str, date=None) -> Path:
    """사이트별 리스트 이미지 저장 디렉터리 (연도년/YYYYMMDD 포함)."""
    return get_image_save_dir(site, "list", date)


def get_detail_image_save_dir(site: str, date=None) -> Path:
    """사이트별 상세 이미지 저장 디렉터리 (연도년/YYYYMMDD 포함)."""
    return get_image_save_dir(site, "detail", date)
