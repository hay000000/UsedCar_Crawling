# -*- coding: utf-8 -*-
"""
오토인사이드 중고차 목록 페이지에서 차종(model_list 내 li) 수집 후
autoinside_car_type_list.csv 생성.
"""
import csv
import logging
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://www.autoinside.co.kr/display/bu/display_bu_used_car_list.do"
# wrap > frm > container > container_inn > page page_buy_car_list > car_list_wrap > car_list_wrap_l > car_list_wrap_inn > category_box cate_model_list > model_list > li
SELECTOR_LI = "#wrap #frm .container .container_inn .page.page_buy_car_list .car_list_wrap .car_list_wrap_l .car_list_wrap_inn .category_box.cate_model_list .model_list li"
# 짧은 셀렉터 (구조 변경 시 대비)
SELECTOR_LI_FALLBACK = ".cate_model_list .model_list li"


def setup_logger():
    log_dir = Path(__file__).resolve().parent.parent / "logs" / "autoinside"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "autoinside_car_type_list.log"
    logger = logging.getLogger("AutoinsideTypeList")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(formatter)
        logger.addHandler(sh)
    return logger


def run_autoinside_car_type_list(page, result_dir: Path, logger):
    """
    오토인사이드 중고차 목록 페이지에서 차종(모델) 목록 수집.
    car_list_wrap > ... > category_box cate_model_list > model_list 내 li 텍스트를
    car_type_name으로, car_type_sn은 1,2,3... 으로 저장.
    """
    result_dir.mkdir(parents=True, exist_ok=True)
    csv_path = result_dir / "autoinside_car_type_list.csv"
    if csv_path.exists():
        csv_path.unlink()

    headers = ["car_type_sn", "car_type_name"]

    try:
        logger.info("오토인사이드 차종 목록 수집 시작: %s", URL)
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        # model_list 내 li 대기 (긴 셀렉터 먼저, 실패 시 fallback)
        li_locator = None
        for selector in (SELECTOR_LI, SELECTOR_LI_FALLBACK):
            try:
                loc = page.locator(selector)
                loc.first.wait_for(state="visible", timeout=10000)
                li_locator = loc
                # logger.info("차종 목록 영역 로드됨 (셀렉터: %s)", selector)
                break
            except Exception as e:
                logger.debug("셀렉터 실패 %s: %s", selector, e)
                continue

        if li_locator is None:
            logger.warning("차종 목록(li) 요소를 찾지 못했습니다.")
            return

        n = li_locator.count()
        if n == 0:
            logger.warning("차종 li 개수가 0입니다.")
            return

        logger.info("총 %d개 차종 수집 시작", n)

        car_type_sn = 1
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            w.writeheader()
            for i in range(n):
                name = (li_locator.nth(i).inner_text() or "").strip()
                # 줄바꿈/여러 공백을 하나의 공백으로
                name = " ".join(name.split()) if name else ""
                if not name:
                    continue
                w.writerow({"car_type_sn": car_type_sn, "car_type_name": name})
                logger.info("[%d/%d] %s", car_type_sn, n, name)
                car_type_sn += 1

        logger.info("저장 완료: %s (총 %d건)", csv_path, car_type_sn - 1)
    except Exception as e:
        logger.error("차종 수집 오류: %s", e, exc_info=True)


def main():
    result_dir = Path(__file__).resolve().parent.parent / "result" / "autoinside"
    logger = setup_logger()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            run_autoinside_car_type_list(page, result_dir, logger)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
