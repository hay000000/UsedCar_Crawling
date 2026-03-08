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

# 제조사/모델: .body-ctn-search-list #wrap #container #reactMainPage ... .search-condition .condition-item.item-model .select-type-checked.mnfc
# mnfc > li → label[for^="br"] = brand_list, 클릭 시 .select-type-checked.model > li = car_list
# car 클릭 시 .select-type-checked.dmodel > li = model_list, 그 하위 dmodel = model_list_1, 그 하위 = model_list_2
# 리프마다 1행: model_sn, brand_list, car_list, model_list, model_list_1, model_list_2
SELECTOR_BRAND_SECTION = ".search-condition .condition-item.item-model .select-type-checked.mnfc"
SELECTOR_MNFC_LI = f"{SELECTOR_BRAND_SECTION} > li"
SELECTOR_MODEL = "ul.select-type-checked.model"
SELECTOR_DMODEL = "ul.select-type-checked.dmodel"
# 직계 자식 ul 아래의 li만 참조 (중첩 단계 혼입 방지)
MODEL_CHILD_LI = "> ul.select-type-checked.model > li"
DMODEL_CHILD_LI = "> ul.select-type-checked.dmodel > li"


def _normalize_text(text):
    """줄바꿈/여러 공백을 하나로."""
    return " ".join((text or "").strip().split())


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
        logger.info("====================롯데렌터카 차종 목록 수집 시작 ====================")
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


def _get_label_text(locator_li):
    """li 로케이터 하위 label 텍스트 반환 (img 제외 텍스트만)."""
    try:
        label = locator_li.locator("label").first
        if label.count() == 0:
            return ""
        return _normalize_text(label.inner_text())
    except Exception:
        return ""


def _click_expand(page, locator_li, logger):
    """펼치기용 클릭: 해당 li의 직계 자식 p.icon_toggle(화살표) 먼저, 없으면 label 시도.
    HTML: li > input, label, var, ul?, p.icon_toggle → 직계 자식만 클릭해야 중첩 li 화살표와 혼동 안 함."""
    for _ in range(2):
        try:
            locator_li.scroll_into_view_if_needed(timeout=3000)
            page.wait_for_timeout(200)
            # 직계 자식 p.icon_toggle만 클릭 (중첩된 하위 li의 화살표 제외)
            toggle = locator_li.locator("> p.icon_toggle")
            if toggle.count() > 0 and toggle.first.is_visible(timeout=1000):
                toggle.first.click()
                page.wait_for_timeout(450)
                return True
        except Exception as e:
            logger.debug("p.icon_toggle 클릭 실패: %s", e)
        try:
            lbl = locator_li.locator("> label").first
            if lbl.count() > 0:
                lbl.click()
                page.wait_for_timeout(450)
                return True
        except Exception as e:
            logger.debug("label 클릭 실패: %s", e)
        page.wait_for_timeout(300)
    return False


def _ensure_children_visible(page, locator_li, child_li_selector: str, logger, timeout_ms: int = 8000) -> bool:
    """이미 펼쳐져 있으면 클릭하지 않고, 비어있을 때만 펼치기 클릭 후 하위 li가 나타날 때까지 대기."""
    try:
        if locator_li.locator(child_li_selector).count() > 0:
            return True
    except Exception:
        pass

    if not _click_expand(page, locator_li, logger):
        return False

    try:
        locator_li.locator(child_li_selector).first.wait_for(state="visible", timeout=timeout_ms)
        return True
    except Exception:
        return locator_li.locator(child_li_selector).count() > 0


def run_lotterentacar_brand_list(page, result_dir: Path, logger):
    """
    롯데렌터카 제조사/모델 트리 수집 → lotterentacar_brand_list.csv
    - brand_list: .select-type-checked.mnfc > li 내 label[for^="br"] 텍스트
    - car_list: .select-type-checked.model > li (클릭 후 표시)
    - model_list: .select-type-checked.dmodel > li (car 클릭 후)
    - model_list_1: 그 하위 .select-type-checked.dmodel > li
    - model_list_2: 그 하위 .select-type-checked.dmodel > li
    리프 경로마다 1행 (예: 기아, K3, 더 뉴 K3, 1.6 가솔린, 트렌디).
    """
    result_dir.mkdir(parents=True, exist_ok=True)
    csv_path = result_dir / "lotterentacar_brand_list.csv"
    if csv_path.exists():
        csv_path.unlink()
    headers = [
        "model_sn", "brand_list", "car_list", "model_list",
        "model_list_1", "model_list_2", "date_crtr_pnttm", "create_dt",
    ]
    need_header = True
    model_sn = 0

    def write_row(f, w, brand_list, car_list, model_list, model_list_1, model_list_2):
        nonlocal model_sn, need_header
        model_sn += 1
        now = datetime.now()
        row = {
            "model_sn": model_sn,
            "brand_list": brand_list or "",
            "car_list": car_list or "",
            "model_list": model_list or "",
            "model_list_1": model_list_1 or "",
            "model_list_2": model_list_2 or "",
            "date_crtr_pnttm": now.strftime("%Y%m%d"),
            "create_dt": now.strftime("%Y%m%d%H%M"),
        }
        if need_header:
            w.writeheader()
            need_header = False
        w.writerow(row)
        f.flush()

    try:
        logger.info("==================== 롯데렌터카 브랜드/차종/모델 목록 수집 시작 ====================")
        if URL not in (page.url or ""):
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        try:
            page.wait_for_selector(SELECTOR_MNFC_LI, timeout=15000)
            page.wait_for_timeout(1500)
        except Exception as e:
            logger.warning("브랜드 영역(ul.select-type-checked.mnfc > li) 대기 실패: %s", e)
            return

        brand_lis = page.locator(SELECTOR_MNFC_LI)
        brand_count = brand_lis.count()
        if brand_count == 0:
            logger.warning("브랜드 li가 0개입니다.")
            return
        logger.info("브랜드 %d개 탐색 시작", brand_count)

        with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=headers)

            for i in range(brand_count):
                try:
                    brand_li = page.locator(SELECTOR_MNFC_LI).nth(i)
                    # brand_list = label[for^="br"] 텍스트 (예: 현대, 기아)
                    brand_name = ""
                    if brand_li.locator("label[for^='br']").count() > 0:
                        brand_name = _normalize_text(brand_li.locator("label[for^='br']").first.inner_text())
                    if not brand_name:
                        brand_name = _get_label_text(brand_li)
                    if not brand_name:
                        continue
                    logger.info("[브랜드 %d/%d] %s", i + 1, brand_count, brand_name)
                    _ensure_children_visible(page, brand_li, MODEL_CHILD_LI, logger, timeout_ms=12000)
                    page.wait_for_timeout(300)
                except Exception as e:
                    logger.debug("브랜드 %d 클릭/이름 실패: %s", i, e)
                    continue

                car_lis = page.locator(SELECTOR_MNFC_LI).nth(i).locator(MODEL_CHILD_LI)
                car_count = car_lis.count()
                if car_count == 0:
                    write_row(f, w, brand_name, "", "", "", "")
                    continue

                for j in range(car_count):
                    try:
                        car_li = page.locator(SELECTOR_MNFC_LI).nth(i).locator(MODEL_CHILD_LI).nth(j)
                        car_name = _get_label_text(car_li)
                        if not car_name:
                            continue
                        # 차종 클릭 후 직계 자식 dmodel(더 뉴아이오닉 5 등) 노출
                        _ensure_children_visible(page, car_li, DMODEL_CHILD_LI, logger, timeout_ms=12000)
                        page.wait_for_timeout(250)

                    except Exception as e:
                        logger.debug("차종 %d 클릭/이름 실패: %s", j, e)
                        continue

                    # 직계 자식 ul.dmodel > li 만 사용 (model_list: 더 뉴아이오닉 5 등)
                    d1_lis = page.locator(SELECTOR_MNFC_LI).nth(i).locator(MODEL_CHILD_LI).nth(j).locator(DMODEL_CHILD_LI)
                    d1_count = d1_lis.count()
                    if d1_count == 0:
                        logger.debug("[%s > %s] dmodel li 0개 → 1건만 기록", brand_name, car_name)
                        write_row(f, w, brand_name, car_name, "", "", "")
                        continue
                    logger.info("[%s > %s] model_list %d개", brand_name, car_name, d1_count)

                    for k in range(d1_count):
                        try:
                            d1_li = page.locator(SELECTOR_MNFC_LI).nth(i).locator(MODEL_CHILD_LI).nth(j).locator(DMODEL_CHILD_LI).nth(k)
                            model_list_val = _get_label_text(d1_li)
                        except Exception:
                            model_list_val = ""
                        # model_list(더 뉴아이오닉 5 등) 클릭 후 직계 자식 dmodel(model_list_1) 노출
                        _ensure_children_visible(page, d1_li, DMODEL_CHILD_LI, logger, timeout_ms=10000)
                        page.wait_for_timeout(200)
                        d2_lis = d1_li.locator(DMODEL_CHILD_LI)
                        d2_count = d2_lis.count()
                        if d2_count == 0:
                            write_row(f, w, brand_name, car_name, model_list_val, "", "")
                            continue
                        for k2 in range(d2_count):
                            try:
                                d2_li = d1_li.locator(DMODEL_CHILD_LI).nth(k2)
                                model_list_1_val = _get_label_text(d2_li)
                            except Exception:
                                model_list_1_val = ""
                            # model_list_1(EV 2WD 등) 클릭 후 직계 자식 dmodel(model_list_2) 노출 (없을 수도 있음)
                            _ensure_children_visible(page, d2_li, DMODEL_CHILD_LI, logger, timeout_ms=8000)
                            page.wait_for_timeout(150)
                            d3_lis = d2_li.locator(DMODEL_CHILD_LI)
                            d3_count = d3_lis.count()
                            if d3_count == 0:
                                write_row(f, w, brand_name, car_name, model_list_val, model_list_1_val, "")
                                continue
                            for k3 in range(d3_count):
                                try:
                                    d3_li = d2_li.locator(DMODEL_CHILD_LI).nth(k3)
                                    model_list_2_val = _get_label_text(d3_li)
                                except Exception:
                                    model_list_2_val = ""
                                write_row(f, w, brand_name, car_name, model_list_val, model_list_1_val, model_list_2_val)

                # 다음 브랜드로 가기 전 현재 브랜드 접기(같은 li 다시 클릭)
                try:
                    page.locator(SELECTOR_MNFC_LI).nth(i).locator("label").first.click()
                    page.wait_for_timeout(300)
                except Exception:
                    pass

        logger.info("저장 완료: %s (총 %d건)", csv_path, model_sn)
    except Exception as e:
        logger.error("브랜드 목록 수집 오류: %s", e, exc_info=True)


def main():
    logger = setup_logger()
    result_dir = Path(__file__).resolve().parent.parent / "result" / "lotterentacar"
    result_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # headed: 브라우저 창 띄워서 클릭/크롤링 과정 확인 가능 (구글 Chrome 사용)
        browser = p.chromium.launch(headless=False, channel="chrome")
        try:
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = context.new_page()
            # run_lotterentacar_car_type_list(page, result_dir, logger)  # 브랜드 수집 문제 해결 시 재활성화
            run_lotterentacar_brand_list(page, result_dir, logger)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
