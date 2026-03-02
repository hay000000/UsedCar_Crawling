# -*- coding: utf-8 -*-
"""
K Car 검색 페이지(https://www.kcar.com/bc/search)에서
차종(차종 탭 패널 내 .el-checkbox__label) 목록을 수집하여 car_type_list.csv로 저장.
"""
import csv
import logging
from pathlib import Path

from playwright.sync_api import sync_playwright


def setup_logger():
    log_dir = Path(__file__).resolve().parent.parent / "logs" / "kcar"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "kcar_type_to_list.log"
    logger = logging.getLogger("KCarTypeList")
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


def run_kcar_car_type_list(page, result_dir: Path, logger):
    """
    K Car 검색 페이지에서 차종 목록 수집.
    body #__nuxt #__layout .Container .searchWrap ... .kcarSnb 내
    [aria-label="차종"] 하위 role="tabpanel" > .el-collapse-item__content > .menuItemList >
    .el-checkbox-group > .el-checkbox > .el-checkbox__label 텍스트 수집.
    """
    csv_path = result_dir / "kcar_car_type_to_list.csv"
    if csv_path.exists():
        csv_path.unlink()

    headers = ["car_type_sn", "car_type_name"]
    url = "https://www.kcar.com/bc/search"

    try:
        logger.info("================================================")
        logger.info("K Car 차종(car_type) 수집 시작...")
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(3000)

        # 약관/동의 팝업 확인 버튼 처리
        for _ in range(3):
            try:
                confirm_btn = page.locator("button:has-text('확인')").first
                if confirm_btn.is_visible(timeout=1000):
                    confirm_btn.click()
                    page.wait_for_timeout(800)
            except Exception:
                break

        # 사이드 SNB 로딩 대기 (차종이 첫 번째 아코디언인 경우 많음)
        page.wait_for_selector(".kcarSnb, .kcarSnbWrap, .menuItemList", timeout=20000)
        page.wait_for_timeout(1500)

        # 차종 영역 펼치기: aria-label="차종" 헤더 클릭
        try:
            header = page.locator('[aria-label="차종"]').first
            if header.is_visible(timeout=2000):
                header.click()
                page.wait_for_timeout(1000)
        except Exception:
            pass

        labels = None
        n = 0

        # 1) 차종 탭 패널 내 .el-checkbox__label (aria-label 차종 하위)
        try:
            section = page.locator(
                '.kcarSnb .el-collapse-item:has([aria-label="차종"]) .menuItemList .el-checkbox-group .el-checkbox'
            )
            section.first.wait_for(state="visible", timeout=5000)
            labels = section.locator(".el-checkbox__label")
            n = labels.count()
        except Exception:
            pass

        # 2) 첫 번째 .menuItemList 내 차종 체크박스 (차종이 첫 번째 메뉴인 경우)
        if n == 0:
            try:
                first_menu = page.locator(".kcarSnb .menuItemList").first
                first_menu.wait_for(state="visible", timeout=5000)
                labels = first_menu.locator(".el-checkbox .el-checkbox__label")
                n = labels.count()
            except Exception:
                pass

        # 3) .kcarSnb 내 모든 .el-checkbox__label 중 첫 번째 그룹만 (role=group 첫 번째)
        if n == 0:
            try:
                first_group = page.locator(".kcarSnb .el-checkbox-group.chkGroup").first
                first_group.wait_for(state="visible", timeout=5000)
                labels = first_group.locator(".el-checkbox .el-checkbox__label")
                n = labels.count()
            except Exception:
                pass

        if n == 0:
            logger.warning("차종 라벨 요소를 찾지 못했습니다.")
            return

        car_type_sn = 1
        wrote_any = False
        for i in range(n):
            name = labels.nth(i).inner_text().strip()
            if not name:
                continue

            # 한 종 발견될 때마다 바로 CSV append
            first_write = not csv_path.exists()
            with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=headers)
                if first_write:
                    w.writeheader()
                w.writerow({"car_type_sn": car_type_sn, "car_type_name": name})

            logger.info("차량 종류: %s", name)
            car_type_sn += 1
            wrote_any = True

        if wrote_any:
            logger.info("차종 CSV 저장 완료: %s (%d건)", csv_path, car_type_sn - 1)
            logger.info("차종 수집이 완료되었습니다.")
        else:
            logger.warning("차종 데이터 없음.")
    except Exception as e:
        logger.error("차종 수집 오류: %s", e, exc_info=True)


def main():
    logger = setup_logger()
    # result/kcar (프로젝트 루트 기준)
    result_dir = Path(__file__).resolve().parent.parent / "result" / "kcar"
    result_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        try:
            run_kcar_car_type_list(page, result_dir, logger)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
