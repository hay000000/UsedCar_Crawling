#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
현대/제네시스 인증중고차 차량 검색 페이지에서 차종·브랜드 목록 수집.

- URL: https://certified.hyundai.com/p/search/vehicle
- DOM: #saleVehicleFilter
  - 첫번째 li: 차종(car_type) → hyundaicar_car_type_list.csv
  - 두번째 li: 브랜드/모델 → .form_filter.brand(현대/제네시스), .brandalllist 트리
    → hyundaicar_brand_list.csv (brand_list, car_list, model_list, production_period, model_list_1, model_list_2)

출력:
- result/hyundaicar/hyundaicar_car_type_list.csv
- result/hyundaicar/hyundaicar_brand_list.csv
- result/hyundaicar/hyundaicar_list.csv (검색 결과 목록: product_id, name, release_dt, car_navi, car_num, local_dos, pay, del, sale, flag)
- logs/hyundaicar/hyundaicar_type_to_list.log
"""

import csv
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

URL = "https://certified.hyundai.com/p/search/vehicle"
DETAIL_URL_TEMPLATE = "https://certified.hyundai.com/p/goods/goodsDetail.do?goodsNo={}"
# 차종별 목록 테스트 수집 개수 (더보기 #btnSeeMore 로 추가 로드)
LIST_PER_CAR_TYPE = 20


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


def _normalize_production_period(s: str) -> str:
    """'23년~현재' → '23~현재', '21~24년' → '21~24' (년 제거)."""
    if not s:
        return ""
    t = _norm(s).replace("년", "").strip()
    return t


def _label_txt(locator, selector: str = "label[for^='filter'] .txt"):
    """locator 범위 내 selector 텍스트 수집. 없으면 label .txt 시도."""
    els = locator.locator(selector)
    n = els.count()
    if n == 0:
        els = locator.locator("label .txt")
        n = els.count()
    return [_norm(els.nth(i).inner_text()) for i in range(n)] if n else []


def _label_txt_first(locator, selector: str = "label[for^='filter'] .txt"):
    """첫 번째만 반환."""
    vals = _label_txt(locator, selector)
    return vals[0] if vals else ""


def _label_txt_exclude_small(locator):
    """label 내 .txt 텍스트에서 small 텍스트를 제외한 값 반환 (model_list용)."""
    txt_el = locator.locator("label[for^='filter'] .txt").first
    if txt_el.count() == 0:
        txt_el = locator.locator("label .txt").first
    if txt_el.count() == 0:
        return ""
    txt_text = _norm(txt_el.inner_text())
    small_el = locator.locator("small").first
    if small_el.count() > 0:
        small_text = _norm(small_el.inner_text())
        if small_text and small_text in txt_text:
            txt_text = txt_text.replace(small_text, "", 1).strip()
    return txt_text


def run_hyundaicar_brand_list(page, result_dir: Path, logger):
    """
    #saleVehicleFilter 두번째 li에서 브랜드(현대/제네시스) 및 .brandalllist 트리 수집.
    - brand_list: .form_filter.brand 내 radio ga-tx '현대'/'제네시스'
    - .brandalllist 내 li[data-ref=toggleBox] .btn_toggle 클릭 후
      ul > li(label.txt)=car_list → ul > li=model_list, small=production_period,
      ul > li=model_list_1, ul > li=model_list_2
    """
    result_dir.mkdir(parents=True, exist_ok=True)
    csv_path = result_dir / "hyundaicar_brand_list.csv"
    if csv_path.exists():
        csv_path.unlink()

    headers = [
        "model_sn",
        "brand_list",
        "car_list",
        "model_list",
        "model_list_1",
        "model_list_2",
        "production_period",
        "date_crtr_pnttm",
        "create_dt",
    ]
    now = datetime.now()
    date_crtr_pnttm = now.strftime("%Y%m%d")
    create_dt = now.strftime("%Y%m%d%H%M")
    model_sn = 0

    def write_row(f, w, brand_list, car_list, model_list, production_period, model_list_1, model_list_2):
        nonlocal model_sn
        model_sn += 1
        w.writerow({
            "model_sn": model_sn,
            "brand_list": brand_list or "",
            "car_list": car_list or "",
            "model_list": model_list or "",
            "model_list_1": model_list_1 or "",
            "model_list_2": model_list_2 or "",
            "production_period": production_period or "",
            "date_crtr_pnttm": date_crtr_pnttm,
            "create_dt": create_dt,
        })
        f.flush()

    try:
        logger.info("============================================================")
        logger.info("현대 인증중고차 브랜드/차종/모델 목록 수집 시작")
        logger.info("============================================================")

        if URL not in (page.url or ""):
            page.goto(URL, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(2000)
            dismiss_common_popups(page, logger)
        page.wait_for_selector("#saleVehicleFilter", timeout=15000)
        page.wait_for_timeout(800)

        # 두번째 li (index 1): 브랜드/모델 영역
        all_toggle = page.locator("#saleVehicleFilter li[data-ref='toggleBox']")
        if all_toggle.count() < 2:
            logger.warning("saleVehicleFilter toggleBox li가 2개 미만입니다.")
            return
        second_li = all_toggle.nth(1)

        # 브랜드명: .form_filter.brand 내 radio(ga-tx 또는 인접 label)에서 "현대"/"제네시스"
        brand_names = []
        for ga_part in ("현대", "제네시스"):
            try:
                radio = second_li.locator(f".form_filter.brand input[type='radio'][ga-tx*='{ga_part}']").first
                if radio.count() > 0 and radio.is_visible(timeout=300):
                    brand_names.append(ga_part)
            except Exception:
                pass
        if not brand_names:
            for node in second_li.locator(".form_filter.brand label").all():
                try:
                    t = _norm(node.inner_text())
                    if t and t in ("현대", "제네시스"):
                        brand_names.append(t)
                except Exception:
                    pass
        if not brand_names:
            brand_names = ["현대", "제네시스"]

        # .brandalllist 내 펼침 li들
        brandalllist = second_li.locator(".brandalllist")
        if brandalllist.count() == 0:
            logger.warning(".brandalllist를 찾지 못했습니다.")
            return

        toggle_items = brandalllist.locator("li[data-ref='toggleBox']")
        n_car_blocks = toggle_items.count()
        logger.info("브랜드: %s, .brandalllist 내 펼침 블록 %d개", brand_names, n_car_blocks)

        with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            w.writeheader()
            f.flush()

            for brand_name in brand_names:
                # 해당 브랜드 선택: radio 클릭
                try:
                    r = second_li.locator(f".form_filter.brand input[type='radio'][ga-tx*='{brand_name}']").first
                    if r.count() > 0 and r.is_visible(timeout=500):
                        r.click()
                        page.wait_for_timeout(600)
                except Exception:
                    pass

                # 다시 .brandalllist (선택에 따라 바뀔 수 있음)
                list_scope = second_li.locator(".brandalllist")
                items = list_scope.locator("li[data-ref='toggleBox']")
                count = items.count()
                if count == 0:
                    write_row(f, w, brand_name, "", "", "", "", "")
                    continue

                for idx in range(count):
                    item = items.nth(idx)
                    # 클래스명으로 현대/제네시스 구분 (예: brandlist brandhmclist ...)
                    cls = item.get_attribute("class") or ""
                    if brand_name == "현대" and "hmclist" not in cls:
                        continue
                    if brand_name == "제네시스" and "hmclist" in cls:
                        continue
                    try:
                        item.scroll_into_view_if_needed(timeout=3000)
                        page.wait_for_timeout(200)
                    except Exception:
                        pass
                    # 펼치기: .btn_toggle 클릭 → open 클래스 추가
                    try:
                        btn = item.locator(".btn_toggle").first
                        if btn.count() > 0 and btn.is_visible(timeout=500):
                            # 이미 open이면 스킵
                            cls = item.get_attribute("class") or ""
                            if "open" not in cls:
                                btn.click()
                                page.wait_for_timeout(500)
                    except Exception as e:
                        logger.debug("btn_toggle 클릭 실패 idx=%s: %s", idx, e)
                        continue

                    # 첫 번째 ul > li → car_list (각 li가 하나의 차종)
                    first_ul = item.locator("> ul").first
                    if first_ul.count() == 0:
                        continue
                    car_lis = first_ul.locator("> li")
                    num_car = car_lis.count()
                    if num_car == 0:
                        continue

                    for c in range(num_car):
                        car_li = car_lis.nth(c)
                        car_list_val = _label_txt_first(car_li)
                        if not car_list_val:
                            continue

                        # car_li 직계 첫 ul > li → model_list, small → production_period, 그 하위 ul → model_list_1, model_list_2
                        model_ul = car_li.locator("> ul").first
                        if model_ul.count() == 0:
                            write_row(f, w, brand_name, car_list_val, "", "", "", "")
                            continue
                        model_lis = model_ul.locator("> li")
                        for m in range(model_lis.count()):
                            model_li = model_lis.nth(m)
                            model_list_val = _label_txt_exclude_small(model_li)
                            small_el = model_li.locator("small").first
                            production_period_val = ""
                            if small_el.count() > 0:
                                production_period_val = _normalize_production_period(small_el.inner_text())

                            m1_uls = model_li.locator("> ul")
                            m1_count = m1_uls.count()
                            if m1_count == 0:
                                write_row(f, w, brand_name, car_list_val, model_list_val, production_period_val, "", "")
                                continue
                            for m1u in range(m1_count):
                                m1_ul = m1_uls.nth(m1u)
                                m1_lis = m1_ul.locator("> li")
                                for m1 in range(m1_lis.count()):
                                    m1_li = m1_lis.nth(m1)
                                    model_list_1_val = _label_txt_first(m1_li)
                                    m2_uls = m1_li.locator("> ul")
                                    m2_count = m2_uls.count()
                                    if m2_count == 0:
                                        write_row(f, w, brand_name, car_list_val, model_list_val, production_period_val, model_list_1_val, "")
                                        continue
                                    for m2u in range(m2_count):
                                        m2_ul = m2_uls.nth(m2u)
                                        for m2 in range(m2_ul.locator("> li").count()):
                                            m2_li = m2_ul.locator("> li").nth(m2)
                                            model_list_2_val = _label_txt_first(m2_li)
                                            write_row(f, w, brand_name, car_list_val, model_list_val, production_period_val, model_list_1_val, model_list_2_val)

                    logger.info("[%s] 블록 %d/%d 처리 완료", brand_name, idx + 1, count)

        logger.info("============================================================")
        logger.info("✅ 브랜드 목록 저장 완료: %s (총 %d건)", csv_path, model_sn)
        logger.info("============================================================")
    except Exception as e:
        logger.error("브랜드 목록 수집 오류: %s", e, exc_info=True)


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


def _extract_product_id_from_href(href: str) -> str:
    """href=\"javascript:common.link.goodsDeatil('GJX251113020892');\" 등에서 product_id 추출."""
    if not href:
        return ""
    m = re.search(r"goodsDeatil\s*\(\s*['\"]([^'\"]+)['\"]", href, re.I)
    if m:
        return (m.group(1) or "").strip()
    m = re.search(r"goodsDetail\s*\(\s*['\"]([^'\"]+)['\"]", href, re.I)
    if m:
        return (m.group(1) or "").strip()
    return ""


def _build_brand_match_key(text: str) -> str:
    """매칭용 키 정규화: 공백 정규화 후 ' (' → '(' 로 통일."""
    if not (text or "").strip():
        return ""
    key = _norm(text)
    return key.replace(" (", "(")


def _load_hyundaicar_brand_map(result_dir: Path, logger):
    """
    hyundaicar_brand_list.csv에서
    - 1순위: model_list + model_list_1 포함
    - 2순위: model_list만 포함
    - 3순위: car_list만 포함
    매칭을 위해, 각 행별로 세 가지 키를 모두 보관한 리스트를 반환.
    """
    csv_path = result_dir / "hyundaicar_brand_list.csv"
    rows = []
    if not csv_path.exists():
        logger.debug("브랜드 CSV 없음: %s", csv_path)
        return rows
    try:
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                model_list = (row.get("model_list") or "").strip()
                model_list_1 = (row.get("model_list_1") or "").strip()
                car_list = (row.get("car_list") or "").strip()
                brand_list = (row.get("brand_list") or "").strip()

                # 1순위: model_list + model_list_1
                combined_src = " ".join(p for p in [model_list, model_list_1] if p)
                combined_key = _build_brand_match_key(combined_src) if combined_src else ""
                # 2순위: model_list
                model_key = _build_brand_match_key(model_list) if model_list else ""
                # 3순위: car_list
                car_key = _build_brand_match_key(car_list) if car_list else ""

                if not (combined_key or model_key or car_key):
                    continue

                rows.append(
                    {
                        "combined": combined_key,
                        "model": model_key,
                        "car": car_key,
                        "brand_list": brand_list,
                        "car_list": car_list,
                    }
                )
        logger.info("브랜드 매핑 %d건 로드 (list 매칭용)", len(rows))
    except Exception as e:
        logger.warning("브랜드 CSV 로드 실패: %s", e)
    return rows


def _find_brand_for_name(name: str, brand_rows):
    """
    차량 이름(name)에 대해,
    1순위: model_list+model_list_1(combined)이 포함되는 행 중 가장 긴 키
    2순위: model_list만 포함되는 행 중 가장 긴 키
    3순위: car_list만 포함되는 행 중 가장 긴 키
    를 찾아 (brand_list, car_list) 반환.
    """
    if not name or not brand_rows:
        return None
    nm_norm = _norm(name).replace(" (", "(")
    if not nm_norm:
        return None
    # 1순위: combined
    best = None
    best_len = -1
    for row in brand_rows:
        key = row.get("combined") or ""
        if not key:
            continue
        if key in nm_norm and len(key) > best_len:
            best = row
            best_len = len(key)
    if best:
        return best["brand_list"], best["car_list"]

    # 2순위: model
    best = None
    best_len = -1
    for row in brand_rows:
        key = row.get("model") or ""
        if not key:
            continue
        if key in nm_norm and len(key) > best_len:
            best = row
            best_len = len(key)
    if best:
        return best["brand_list"], best["car_list"]

    # 3순위: car_list
    best = None
    best_len = -1
    for row in brand_rows:
        key = row.get("car") or ""
        if not key:
            continue
        if key in nm_norm and len(key) > best_len:
            best = row
            best_len = len(key)
    if best:
        return best["brand_list"], best["car_list"]

    return None


def _extract_list_row_from_li(li, date_crtr_pnttm: str, create_dt: str):
    """li.type02 한 개에서 product_id, name, release_dt, ... dict 생성."""
    row = {
        "model_sn": 0,
        "car_type_name": "",
        "product_id": "",
        "car_type": "",
        "name": "",
        "release_dt": "",
        "car_navi": "",
        "car_num": "",
        "local_dos": "",
        "pay": "",
        "del": "-",
        "sale": "",
        "flag": "",
        "date_crtr_pnttm": date_crtr_pnttm,
        "create_dt": create_dt,
    }
    try:
        link = li.locator("a[href*='goodsDeatil'], a[href*='goodsDetail']").first
        if link.count() > 0:
            href = link.get_attribute("href") or ""
            row["product_id"] = _extract_product_id_from_href(href)
        name_el = li.locator(".unit_info .name").first
        if name_el.count() > 0:
            row["name"] = _norm(name_el.inner_text())
        drive_spans = li.locator(".unit_info .drive span")
        for s in range(min(4, drive_spans.count())):
            val = _norm(drive_spans.nth(s).inner_text())
            if s == 0:
                row["release_dt"] = val
            elif s == 1:
                row["car_navi"] = val
            elif s == 2:
                row["car_num"] = val
            else:
                row["local_dos"] = val
        if li.locator(".price .txt.pay").first.count() > 0:
            row["pay"] = _norm(li.locator(".price .txt.pay").first.inner_text())
        if li.locator(".price .txt.del").first.count() > 0:
            row["del"] = _norm(li.locator(".price .txt.del").first.inner_text()) or "-"
        if li.locator(".price .txt.sale").first.count() > 0:
            row["sale"] = _norm(li.locator(".price .txt.sale").first.inner_text())
        flag_spans = li.locator(".flag span")
        flag_vals = [_norm(flag_spans.nth(j).inner_text()) for j in range(flag_spans.count()) if _norm(flag_spans.nth(j).inner_text())]
        row["flag"] = "|".join(flag_vals)
    except Exception:
        pass
    return row


def run_hyundaicar_list(page, result_dir: Path, logger):
    """
    차종(승용, SUV, 승합, EV)별로 선택 → 각 20건 수집(#btnSeeMore 페이징) → 해제 후 다음 차종 반복.
    .search_result .resultlist .product.productlist > li.type02 에서
    car_type_name, product_id, name, release_dt, car_navi, car_num, local_dos, pay, del, sale, flag 수집.
    """
    result_dir.mkdir(parents=True, exist_ok=True)
    csv_path = result_dir / "hyundaicar_list.csv"
    if csv_path.exists():
        csv_path.unlink()

    headers = [
        "model_sn",
        "product_id",
        "car_type_name",
        "car_type",
        "brand_list",
        "car_list",
        "name",
        "release_dt",
        "car_navi",
        "car_num",
        "local_dos",
        "pay",
        "del",
        "sale",
        "flag",
        "date_crtr_pnttm",
        "create_dt",
    ]
    now = datetime.now()
    date_crtr_pnttm = now.strftime("%Y%m%d")
    create_dt = now.strftime("%Y%m%d%H%M")

    # type02만 수집, type02.banner(광고) 제외
    list_selector = ".search_result .resultlist .product.productlist li.type02:not(.banner)"
    list_selector_fb = ".resultlist .productlist li.type02:not(.banner)"
    btn_more = "#btnSeeMore"

    try:
        logger.info("============================================================")
        logger.info("현대 인증중고차 검색 결과 목록 수집 (차종별 %d건)", LIST_PER_CAR_TYPE)
        logger.info("============================================================")

        if URL not in (page.url or ""):
            page.goto(URL, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(2000)
            dismiss_common_popups(page, logger)
        page.wait_for_selector("#CPOwrap, #saleVehicleFilter", timeout=20000)
        page.wait_for_timeout(1200)

        box = page.locator("#saleVehicleFilter li[data-ref='toggleBox'].isShow").first
        if box.count() == 0:
            box = page.locator("#saleVehicleFilter li[data-ref='toggleBox']").first
        if box.count() == 0:
            logger.warning("saleVehicleFilter toggleBox를 찾지 못했습니다.")
            return

        txt_locator = box.locator(".cont .form_filter.model label[for*='filter_car_type'] .txt")
        if txt_locator.count() == 0:
            txt_locator = box.locator(".cont .form_filter.model .txt")
        n_types = txt_locator.count()
        if n_types == 0:
            logger.warning("차종(.txt) 요소가 없습니다.")
            return

        car_type_names = []
        for i in range(n_types):
            t = _norm(txt_locator.nth(i).inner_text())
            if t and t not in car_type_names:
                car_type_names.append(t)
        if not car_type_names:
            logger.warning("차종 이름을 읽지 못했습니다.")
            return
        logger.info("차종 순서: %s", car_type_names)

        # brand.csv 기반 매핑 로드 (model_list+model_list_1 → brand_list, car_list)
        brand_map = _load_hyundaicar_brand_map(result_dir, logger)

        total_written = 0
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            w.writeheader()
            f.flush()

            for car_type_name in car_type_names:
                logger.info("---------- 차종 선택: %s ----------", car_type_name)
                label_el = box.locator("label").filter(has_text=car_type_name).first
                if label_el.count() == 0:
                    logger.warning("[%s] 차종 라벨 없음, 스킵", car_type_name)
                    continue
                label_el.click()
                page.wait_for_timeout(1800)

                items = page.locator(list_selector)
                if items.count() == 0:
                    items = page.locator(list_selector_fb)
                need = LIST_PER_CAR_TYPE
                while items.count() < need:
                    try:
                        btn = page.locator(btn_more).first
                        if btn.count() == 0 or not btn.is_visible(timeout=500):
                            break
                        btn.click()
                        page.wait_for_timeout(1500)
                        items = page.locator(list_selector)
                        if items.count() == 0:
                            items = page.locator(list_selector_fb)
                    except Exception:
                        break
                n = items.count()
                to_take = min(need, n)
                logger.info("[%s] 수집 %d건 (전체 %d건)", car_type_name, to_take, n)
                for i in range(to_take):
                    li = items.nth(i)
                    row = _extract_list_row_from_li(li, date_crtr_pnttm, create_dt)
                    total_written += 1
                    row["model_sn"] = total_written
                    row["car_type_name"] = car_type_name
                    row["car_type"] = car_type_name
                    # name 기준으로 브랜드/차종 매핑
                    if row.get("name") and brand_map:
                        matched = _find_brand_for_name(row["name"], brand_map)
                        if matched:
                            row["brand_list"], row["car_list"] = matched
                    w.writerow(row)
                    f.flush()
                    logger.info("[%s] %d/%d %s %s", car_type_name, i + 1, to_take, row["product_id"], (row["name"] or "")[:25])

                label_el.click()
                page.wait_for_timeout(800)

        logger.info("============================================================")
        logger.info("✅ 목록 저장 완료: %s (총 %d건)", csv_path, total_written)
        logger.info("============================================================")
    except Exception as e:
        logger.error("목록 수집 오류: %s", e, exc_info=True)


def _save_hyundaicar_detail_images(page, product_id: str, save_dir: Path, detail_url: str, logger):
    """
    상세 페이지에서 '이미지 보기' 클릭 후
    data-ref="uspGallery" 아래 .usp_main .usp_main_img, .usp_list [data-ref="uspGalleryItemList"] .item 이미지 수집
    → save_dir/product_id_1.png, product_id_2.png ... 저장.
    """
    if not product_id or not save_dir:
        return 0
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    base_url = detail_url.rsplit("?", 1)[0] if "?" in detail_url else detail_url
    urls = []

    try:
        # '이미지 보기' 버튼 클릭 (.btn_img 자체 또는 내부 버튼/링크)
        btn = page.locator(".btn_img button, .btn_img a, .btn_img").first
        if btn.count() > 0 and btn.is_visible(timeout=3000):
            btn.click()
            page.wait_for_timeout(1500)

        # data-ref="uspGallery" 갤러리 영역 대기 (클릭 시 .pdp01_car.ready → .uspGallisOpen 추가됨)
        gallery = page.locator('[data-ref="uspGallery"]').first
        gallery.wait_for(state="visible", timeout=8000)
        page.wait_for_timeout(500)

        # 1) .usp_main .usp_main_img (메인 이미지)
        main_img = gallery.locator(".usp_main .usp_main_img img").first
        if main_img.count() == 0:
            main_img = gallery.locator(".usp_main .usp_main_img").first
        if main_img.count() > 0:
            src = main_img.get_attribute("src") or main_img.get_attribute("data-src")
            if src:
                urls.append(src)

        # 2) .usp_list [data-ref="uspGalleryItemList"] .item (class에 item 포함) 내 이미지
        items = gallery.locator('.usp_list [data-ref="uspGalleryItemList"] [class*="item"]')
        for i in range(items.count()):
            item = items.nth(i)
            img = item.locator("img").first
            if img.count() > 0:
                src = img.get_attribute("src") or img.get_attribute("data-src")
                if src:
                    urls.append(src)
    except Exception as e:
        logger.debug("이미지 영역 추출 실패 %s: %s", product_id, e)

    saved = 0
    for idx, src in enumerate(urls, start=1):
        try:
            full_url = urljoin(base_url, src) if not (src.startswith("http") or src.startswith("//")) else ("https:" + src if src.startswith("//") else src)
            resp = page.request.get(full_url, timeout=15000)
            if resp.ok:
                path = save_dir / f"{product_id}_{idx}.png"
                path.write_bytes(resp.body())
                saved += 1
        except Exception as e:
            logger.warning("이미지 저장 실패 %s_%s: %s", product_id, idx, e)
    if saved > 0:
        logger.info("%s 이미지 %d장 저장: %s", product_id, saved, save_dir)
    return saved


def run_hyundaicar_detail_images(page, result_dir: Path, logger):
    """
    hyundaicar_list.csv의 product_id로 상세 페이지 접속 후
    이미지 보기 클릭 → data-ref="uspGallery" 내 이미지 수집
    저장: imgs/hyundaicar/YYYY년/YYYYMMDD/product_id_1.png, product_id_2.png ...
    """
    list_path = result_dir / "hyundaicar_list.csv"
    if not list_path.exists():
        logger.warning("목록 파일 없음: %s (이미지 수집 스킵)", list_path)
        return

    now = datetime.now()
    img_dir = Path(__file__).resolve().parent.parent / "imgs" / "hyundaicar" / f"{now.year}년" / now.strftime("%Y%m%d")
    img_dir.mkdir(parents=True, exist_ok=True)
    logger.info("이미지 저장 경로: %s", img_dir)

    product_ids = []
    try:
        with open(list_path, "r", encoding="utf-8-sig", newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                pid = (row.get("product_id") or "").strip()
                if pid:
                    product_ids.append(pid)
    except Exception as e:
        logger.error("목록 CSV 읽기 실패: %s", e)
        return

    if not product_ids:
        logger.warning("product_id 없음. 이미지 수집 스킵.")
        return

    logger.info("============================================================")
    logger.info("현대 인증중고차 상세 이미지 수집 시작 (총 %d건)", len(product_ids))
    logger.info("============================================================")

    for i, product_id in enumerate(product_ids, start=1):
        detail_url = DETAIL_URL_TEMPLATE.format(product_id)
        try:
            page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)
            page.wait_for_selector("#CPOwrap, .car_detail_cont, .pdp01_car", timeout=15000)
            page.wait_for_timeout(800)
            _save_hyundaicar_detail_images(page, product_id, img_dir, detail_url, logger)
        except Exception as e:
            logger.warning("[%d/%d] %s 상세 페이지 실패: %s", i, len(product_ids), product_id, e)
        if i < len(product_ids):
            page.wait_for_timeout(500)

    logger.info("============================================================")
    logger.info("✅ 상세 이미지 수집 완료")
    logger.info("============================================================")


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
            # run_hyundaicar_car_type_list(page, result_dir, logger)
            # run_hyundaicar_brand_list(page, result_dir, logger)
            # run_hyundaicar_list(page, result_dir, logger)
            run_hyundaicar_detail_images(page, result_dir, logger)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
