# -*- coding: utf-8 -*-
"""
롯데렌터카 T car 검색 페이지에서 차종 목록 수집.
- #carTypeField .select-type-checked 내 li(name=chkCartype) 텍스트 수집 → lotterentacar_car_type_list.csv
"""
import csv
import logging
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://tcar.lotterentacar.net/cr/search/list#page:1._.rows:15._.saleTyAll:true"

# body-ctn-search-list > #wrap > #container > #reactMainPage > .layout--container.ctn-search-list >
# .search-list-container > .search-element > .search-condition > #carTypeField > .select-type-checked > li (내부 input name=chkCartype)
SELECTOR_LI = "#carTypeField .select-type-checked li[name='chkCartype']"
SELECTOR_LI_INPUT = "#carTypeField .select-type-checked li:has(input[name='chkCartype'])"
SELECTOR_LI_FALLBACK = ".select-type-checked li[name='chkCartype'], .select-type-checked li:has(input[name='chkCartype'])"
SELECTOR_CONTAINER = "#wrap #container #reactMainPage .search-list-container"


def setup_logger():
    """로그 디렉터리: project_root/logs/lotterentacar, 파일명: lotterentacar_type_to_list.log"""
    log_dir = Path(__file__).resolve().parent.parent / "logs" / "lotterentacar"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "lotterentacar_type_to_list.log"
    logger = logging.getLogger("LotterentacarTypeList")
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


def run_lotterentacar_car_type_list(page, result_dir: Path, logger):
    """
    롯데렌터카 T car 검색 페이지에서 차종 목록 수집.
    #carTypeField .select-type-checked 내 li[name="chkCartype"] 텍스트를
    car_type_name으로, car_type_sn은 1,2,3... 으로 저장.
    """
    result_dir.mkdir(parents=True, exist_ok=True)
    csv_path = result_dir / "lotterentacar_car_type_list.csv"
    if csv_path.exists():
        csv_path.unlink()
    headers = ["car_type_sn", "car_type_name", "date_crtr_pnttm", "create_dt"]
    # append 모드: 행 단위로 쓰고 flush → 중간에 끊겨도 수집된 행까지 디스크에 남음
    need_header = True

    try:
        logger.info("롯데렌터카 차종 목록 수집 시작: %s", URL)
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        # React 영역 로드 대기
        try:
            page.wait_for_selector(SELECTOR_CONTAINER, timeout=15000)
            page.wait_for_timeout(2000)
        except Exception as e:
            logger.debug("컨테이너 대기 실패(무시 가능): %s", e)

        li_locator = None
        for selector in (SELECTOR_LI, SELECTOR_LI_INPUT, SELECTOR_LI_FALLBACK):
            try:
                loc = page.locator(selector)
                loc.first.wait_for(state="visible", timeout=10000)
                li_locator = loc
                break
            except Exception as e:
                logger.debug("셀렉터 실패 %s: %s", selector, e)
                continue

        if li_locator is None:
            logger.warning("차종 목록(li[name=chkCartype]) 요소를 찾지 못했습니다.")
            return

        n = li_locator.count()
        if n == 0:
            logger.warning("차종 li 개수가 0입니다.")
            return

        logger.info("총 %d개 차종 수집 시작", n)

        car_type_sn = 1
        with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            if need_header:
                w.writeheader()
                f.flush()
            for i in range(n):
                name = (li_locator.nth(i).inner_text() or "").strip()
                name = " ".join(name.split()) if name else ""
                if not name:
                    continue
                now = datetime.now()
                date_crtr_pnttm = now.strftime("%Y%m%d")
                create_dt = now.strftime("%Y%m%d%H%M")
                w.writerow({
                    "car_type_sn": car_type_sn,
                    "car_type_name": name,
                    "date_crtr_pnttm": date_crtr_pnttm,
                    "create_dt": create_dt,
                })
                f.flush()
                logger.info("[%d/%d] %s", car_type_sn, n, name)
                car_type_sn += 1

        logger.info("저장 완료: %s (총 %d건)", csv_path, car_type_sn - 1)
    except Exception as e:
        logger.error("차종 수집 오류: %s", e, exc_info=True)


def main():
    logger = setup_logger()
    result_dir = Path(__file__).resolve().parent.parent / "result" / "lotterentacar"
    result_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = context.new_page()
            run_lotterentacar_car_type_list(page, result_dir, logger)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
