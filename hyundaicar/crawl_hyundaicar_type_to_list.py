#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
현대/제네시스 인증중고차 차량 검색 페이지에서 차종 목록 수집.

- URL: https://certified.hyundai.com/p/search/vehicle
- DOM 경로(요청 기준):
  body > #CPOwrap > #CPOcontents > #layoutWrap > .tab_txt.type02 > #searchCar
  > .container > .search_cont > .search_filter > .filterarea > #saleVehicleFilter
  > li[data-ref="toggleBox"].isShow (첫번째 li)
  > .cont > .form_filter.model > label[for*="filter_car_type"] > .txt

출력:
- result/hyundaicar/hyundaicar_car_type_list.csv
  컬럼: car_type_sn, car_type_name, date_crtr_pnttm, create_dt
- logs/hyundaicar/hyundaicar_type_to_list.log
"""

import csv
import logging
import os
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://certified.hyundai.com/p/search/vehicle"


def _norm(s: str) -> str:
    return " ".join((s or "").strip().split())


def setup_logger():
    log_dir = Path(__file__).resolve().parent.parent / "logs" / "hyundaicar"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "hyundaicar_type_to_list.log"

    logger = logging.getLogger("HyundaiCarTypeList")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    return logger


def _click_if_visible(page, selector: str, logger, timeout_ms: int = 800):
    """짧은 시간 내 보이면 클릭. 실패해도 예외를 올리지 않음."""
    try:
        el = page.locator(selector).first
        if el.count() > 0 and el.is_visible(timeout=timeout_ms):
            el.click()
            page.wait_for_timeout(400)
            logger.info("팝업/버튼 클릭: %s", selector)
            return True
    except Exception:
        return False
    return False


def dismiss_common_popups(page, logger):
    """
    페이지 진입 시 자주 뜨는 팝업(동의/확인/닫기/제네시스 이동 여부 등)을 최대한 무해하게 처리.
    - 버튼 텍스트 기반으로 시도하되, 사이트/시점에 따라 없을 수 있으니 best-effort.
    """
    for _ in range(5):
        clicked = False
        # 1) 개인정보/약관 동의
        clicked |= _click_if_visible(page, "button:has-text('동의하기')", logger)
        clicked |= _click_if_visible(page, "a:has-text('동의하기')", logger)

        # 2) 제네시스 브랜드 이동 유도 팝업: '닫기'를 눌러 현재 페이지 유지
        clicked |= _click_if_visible(page, "button:has-text('닫기')", logger)
        clicked |= _click_if_visible(page, "a:has-text('닫기')", logger)

        # 3) 확인 팝업
        clicked |= _click_if_visible(page, "button:has-text('확인')", logger)
        clicked |= _click_if_visible(page, "a:has-text('확인')", logger)

        if not clicked:
            break


def run_hyundaicar_car_type_list(page, result_dir: Path, logger):
    result_dir.mkdir(parents=True, exist_ok=True)
    csv_path = result_dir / "hyundaicar_car_type_list.csv"
    if csv_path.exists():
        csv_path.unlink()

    headers = ["car_type_sn", "car_type_name", "date_crtr_pnttm", "create_dt"]

    logger.info("============================================================")
    logger.info("현대 인증중고차 차종 목록 수집 시작")
    logger.info("URL: %s", URL)
    logger.info("============================================================")

    try:
        page.goto(URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(2000)

        dismiss_common_popups(page, logger)

        # 필터 컨테이너 대기
        page.wait_for_selector("#CPOwrap, #saleVehicleFilter", timeout=30000)
        page.wait_for_timeout(1200)

        dismiss_common_popups(page, logger)

        # 첫번째 toggleBox 선택 (isShow 우선)
        box = page.locator("#saleVehicleFilter li[data-ref='toggleBox'].isShow").first
        if box.count() == 0:
            box = page.locator("#saleVehicleFilter li[data-ref='toggleBox']").first

        if box.count() == 0:
            logger.warning("saleVehicleFilter 내 toggleBox li를 찾지 못했습니다.")
            return

        # 차종 텍스트: label[for*="filter_car_type"] 아래 .txt
        txt_locator = box.locator(".cont .form_filter.model label[for*='filter_car_type'] .txt")
        try:
            txt_locator.first.wait_for(state="visible", timeout=15000)
        except Exception:
            # fallback: form_filter.model 범위만 유지하고 label 조건 완화
            txt_locator = box.locator(".cont .form_filter.model .txt")
            try:
                txt_locator.first.wait_for(state="visible", timeout=8000)
            except Exception:
                pass

        n = txt_locator.count()
        if n == 0:
            logger.warning("차종 텍스트(.txt) 요소를 찾지 못했습니다. (count=0)")
            return

        now = datetime.now()
        date_crtr_pnttm = now.strftime("%Y%m%d")
        create_dt = now.strftime("%Y%m%d%H%M")

        seen = set()
        rows = []
        for i in range(n):
            name = _norm(txt_locator.nth(i).inner_text())
            if not name:
                continue
            if name in seen:
                continue
            seen.add(name)
            rows.append(name)

        if not rows:
            logger.warning("차종 텍스트를 추출했지만 유효 데이터가 없습니다.")
            return

        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            w.writeheader()
            for idx, name in enumerate(rows, start=1):
                w.writerow(
                    {
                        "car_type_sn": idx,
                        "car_type_name": name,
                        "date_crtr_pnttm": date_crtr_pnttm,
                        "create_dt": create_dt,
                    }
                )
                logger.info("[%d/%d] %s", idx, len(rows), name)

        logger.info("============================================================")
        logger.info("✅ 저장 완료: %s", csv_path)
        logger.info("총 수집 차종 수: %d", len(rows))
        logger.info("============================================================")
    except Exception as e:
        logger.error("차종 수집 오류: %s", e, exc_info=True)


def main():
    logger = setup_logger()
    result_dir = Path(__file__).resolve().parent.parent / "result" / "hyundaicar"
    result_dir.mkdir(parents=True, exist_ok=True)

    # 기본값: WSL/서버 환경을 고려해 headless=True. 필요 시 HYUNDAICAR_HEADED=1 로 브라우저 창 표시.
    use_headed = os.environ.get("HYUNDAICAR_HEADED", "0").strip().lower() in ("1", "true", "yes")

    with sync_playwright() as p:
        launch_kwargs = {"headless": (not use_headed)}
        # 로컬 GUI 환경이면 Chrome 채널이 더 안정적인 경우가 있어 옵션 제공
        if os.environ.get("HYUNDAICAR_CHROME_CHANNEL", "0").strip().lower() in ("1", "true", "yes"):
            launch_kwargs["channel"] = "chrome"

        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        try:
            run_hyundaicar_car_type_list(page, result_dir, logger)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
