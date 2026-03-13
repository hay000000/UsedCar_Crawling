# -*- coding: utf-8 -*-
"""
기아 인증중고차(CPO) 제품 목록 페이지에서 차종/모델 트리 수집.

- URL: https://cpo.kia.com/products/
- DOM: #__next > .wrap > #content > .carlist-main > .buy-carlist > .buy-carlist__info >
  .buy-carlist__left-side.show-pc > (두번째 div) > .filter-info.js-select-scrollbar >
  (첫번째 .filter-info__item) > .filter-info__content > .css-hu289v
- .model-select__btn.depth1 선택 시 .active.checked 추가, .item-txt__name → car_list
- .child 내 .model-select__btn.depth2 → .item-txt__name → model_list
- .child 내 .model-select__btn.depth3 → .item-txt__name → model_list_1
- .child 내 .model-select__btn.depth4 → .item-txt__name → model_list_2

출력: result/kiacar/kiacar_brand_list.csv
  (model_sn, brand_list, car_type, car_list, model_list, model_list_1, model_list_2, data_crtr_pnttm, create_dt)
"""

import csv
import logging
import re
import os
import sys
from urllib.parse import urljoin
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from config import PROJECT_ROOT, get_list_image_save_dir

URL = "https://cpo.kia.com/products/"

# 필터 영역: .buy-carlist__left-side 내 두번째 div > .filter-info > 첫 .filter-info__item > .filter-info__content > .css-hu289v
SELECTOR_BASE = (
    ".buy-carlist__left-side.show-pc .filter-info.js-select-scrollbar "
    ".filter-info__item:first-child .filter-info__content .css-hu289v"
)
SELECTOR_BASE_FALLBACK = ".filter-info__content .css-hu289v"
# depth1: 차종(카테고리) 버튼 — 클릭 시 하위 .child 노출
SELECTOR_DEPTH1 = ".model-select__btn.depth1"
# 각 depth 버튼 내 이름
SELECTOR_ITEM_NAME = ".item-txt__name"
# depth1 클릭 후 펼쳐지는 하위: .child 내 depth2, 그 하위 .child 내 depth3, depth4
SELECTOR_CHILD = ".child"
SELECTOR_DEPTH2 = ".model-select__btn.depth2"
SELECTOR_DEPTH3 = ".model-select__btn.depth3"
SELECTOR_DEPTH4 = ".model-select__btn.depth4"

# 차량 카드 리스트(PC)
SELECTOR_CAR_LIST_ROOT = ".carcard-list"
SELECTOR_CAR_ITEM = f"{SELECTOR_CAR_LIST_ROOT} li.item-card.is-pc"
EXCLUDE_ITEM_CLASS = "css-1759cna"  # 광고/비정상 카드 제외
# 더보기 버튼(있으면 클릭하여 추가 로드)
SELECTOR_BTN_MORE = "button:has-text('더보기'), a:has-text('더보기'), button:has-text('더 보기'), a:has-text('더 보기')"

def _norm(s: str) -> str:
    return " ".join((s or "").strip().split())


def setup_logger():
    log_dir = Path(__file__).resolve().parent.parent / "logs" / "kiacar"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "kiacar_type_to_list.log"
    logger = logging.getLogger("KiaCarTypeList")
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


def _get_name(locator) -> str:
    """locator 범위 내 .item-txt__name 텍스트 반환."""
    try:
        el = locator.locator(SELECTOR_ITEM_NAME).first
        if el.count() == 0:
            return ""
        return _norm(el.inner_text())
    except Exception:
        return ""


def _get_count_from_btn(locator) -> int:
    """depth1 버튼 내 .item-txt__count 숫자 반환 (예: EV 122 → 122). 필터 적용 시 리스트 개수와 맞춤용."""
    try:
        el = locator.locator(".item-txt__count").first
        if el.count() == 0:
            return 0
        raw = (el.inner_text() or "").strip().replace(",", "")
        return int(raw) if raw.isdigit() else 0
    except Exception:
        return 0


def _activate_btn(page, locator, logger, timeout_ms: int = 4000) -> bool:
    """
    depth 버튼(왼쪽 원형 체크 포함 전체 라인)을 눌러 active+checked 상태가 될 때까지 대기.
    실제 UI에서 사람이 누르는 것처럼, 한 줄 전체를 타겟으로 클릭하도록 조정.
    """
    try:
        target = locator.first
        if target.count() == 0:
            return False

        # 화면 중앙 좌표를 직접 클릭 (overlay/이벤트 위임을 모두 우회)
        el = target.element_handle()
        if el is None:
            return False
        box = el.bounding_box()
        if not box:
            return False

        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_timeout(150)
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

        # 약간 기다렸다가 active/checked 여부 확인 (단, 클래스 위치는 유연하게 검사)
        page.wait_for_timeout(300)
        try:
            cls_here = (target.get_attribute("class") or "")
        except Exception:
            cls_here = ""
        if "active" in cls_here and "checked" in cls_here:
            return True

        # 부모에도 클래스가 붙는 구조일 수 있으니 한 단계 위도 확인
        try:
            parent = locator.locator("xpath=..").first
            if parent.count() > 0:
                cls_p = parent.get_attribute("class") or ""
                if "active" in cls_p and "checked" in cls_p:
                    return True
        except Exception:
            pass

    except Exception as e:
        logger.debug("depth 버튼 활성화 실패: %s", e)
    return False


def _deactivate_all_depth1(page, base_selector: str, logger, timeout_ms: int = 4000):
    """
    depth1(EV/승용/RV)가 여러 개 동시에 선택(active checked)돼 있으면
    모두 한 번씩 클릭해서 체크를 해제한다.
    이후에 개별 depth1만 다시 켜서 해당 필터만 적용하는 용도.
    """
    try:
        depth1_all = page.locator(f"{base_selector} {SELECTOR_DEPTH1}")
        cnt = depth1_all.count()
        if cnt == 0:
            return
        for i in range(cnt):
            btn = depth1_all.nth(i)
            try:
                cls = btn.get_attribute("class") or ""
            except Exception:
                cls = ""
            if "active" in cls and "checked" in cls:
                name = _get_name(btn)
                logger.info("  → 기존 선택 depth1 해제: %s", name or "(이름 없음)")
                try:
                    btn.scroll_into_view_if_needed(timeout=timeout_ms)
                    page.wait_for_timeout(150)
                    btn.click(timeout=timeout_ms, force=True)
                    page.wait_for_timeout(300)
                except Exception as e:
                    logger.debug("depth1 해제 실패(%s): %s", name, e)
    except Exception as e:
        logger.debug("depth1 전체 해제 중 오류(무시): %s", e)


def _timestamps():
    now = datetime.now()
    return now.strftime("%Y%m%d"), now.strftime("%Y%m%d%H%M")


def _parse_product_id(href: str) -> str:
    """href '/products/detail/?id=10379' 또는 ?id=10379 에서 10379 추출."""
    if not href:
        return ""
    if "id=" in href:
        m = re.search(r"[?&]id=(\d+)", href)
        if m:
            return (m.group(1) or "").strip()
    return ""


def _strip_dot(s: str) -> str:
    """ㆍ 제거 후 정규화."""
    return _norm((s or "").replace("ㆍ", ""))


def _extract_row_from_kiacar_card(li, car_list: str) -> dict:
    """한 개 li.item-card.is-pc에서 locator만으로 행 dict 추출 (JS 없음)."""
    row = {
        "car_list": car_list or "",
        "product_id": "",
        "car_name_1": "",
        "car_name_2": "",
        "line_up": "",
        "release_dt": "",
        "car_navi": "",
        "car_num": "",
        "price": "",
        "underline": "",
        "discount": "",
        "badge_discount": "",
        "reserve": "",
    }
    try:
        cls = li.get_attribute("class") or ""
        if "reserved" in cls and "css-ozhxoy" in cls:
            row["reserve"] = "예약중인 차량"
    except Exception:
        pass
    try:
        a = li.locator("a[rel='noopener noreferrer']").first
        if a.count() > 0:
            href = a.get_attribute("href") or ""
            row["product_id"] = _parse_product_id(href)
    except Exception:
        pass
    try:
        name1_el = li.locator(".css-1laq3le > div .css-1lk1ywa").first
        if name1_el.count() > 0:
            row["car_name_1"] = _norm(name1_el.inner_text())
    except Exception:
        pass
    try:
        spans = li.locator(".css-1laq3le > div span")
        if spans.count() > 0:
            row["line_up"] = _norm(spans.nth(0).inner_text())
            # car_name_1에서 line_up 문자열 제거
            if row["line_up"] and row["car_name_1"] and row["line_up"] in row["car_name_1"]:
                row["car_name_1"] = _norm(row["car_name_1"].replace(row["line_up"], "", 1))
    except Exception:
        pass
    try:
        name2_el = li.locator(".css-jk1y7a").first
        if name2_el.count() > 0:
            row["car_name_2"] = _norm(name2_el.inner_text())
    except Exception:
        pass
    try:
        year_el = li.locator(".css-8lid69 .year").first
        if year_el.count() > 0:
            row["release_dt"] = _strip_dot(year_el.inner_text())
    except Exception:
        pass
    try:
        km_el = li.locator(".css-8lid69 .km").first
        if km_el.count() > 0:
            row["car_navi"] = _strip_dot(km_el.inner_text())
    except Exception:
        pass
    try:
        plate_el = li.locator(".css-8lid69 .plateNumber").first
        if plate_el.count() > 0:
            row["car_num"] = _norm(plate_el.inner_text())
    except Exception:
        pass
    try:
        price_el = li.locator(".css-1sdsv7u .price").first
        if price_el.count() > 0:
            row["price"] = _norm(price_el.inner_text())
    except Exception:
        pass
    try:
        ul_el = li.locator(".css-1sdsv7u .underline").first
        if ul_el.count() > 0:
            row["underline"] = _norm(ul_el.inner_text())
    except Exception:
        pass
    try:
        disc_el = li.locator(".css-1sdsv7u .discount").first
        if disc_el.count() > 0:
            row["discount"] = _norm(disc_el.inner_text())
    except Exception:
        pass
    try:
        if li.locator("[class*='img-wrap__discount']").count() > 0:
            badge_el = li.locator(".css-1u214re strong").first
            if badge_el.count() > 0:
                row["badge_discount"] = _norm(badge_el.inner_text())
    except Exception:
        pass
    return row


def _download_kiacar_card_first_img(page, li, save_dir: Path, file_stem: str, logger) -> str:
    """
    li.item-card.is-pc 내부의 첫번째 썸네일 이미지를 찾아 다운로드 후 저장.
    - 다양한 DOM 케이스(할인 뱃지/예약 등)에 대해 selector를 여러 개 시도.
    - 성공 시 저장 경로(str) 반환, 실패 시 "" 반환.
    """
    try:
        save_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.debug("이미지 폴더 생성 실패: %s (%s)", save_dir, e)
        return ""

    out_path = save_dir / f"{file_stem}.png"
    if out_path.exists():
        try:
            return str(out_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        except Exception:
            return str(out_path).replace("\\", "/")

    selectors = [
        # 요청하신 케이스들(할인 wrapper 유무 / reserved 클래스 유무)
        "div.img-wrap__discount.css-kn97bq a[rel='noopener noreferrer'] img.item-card__img",
        "div.css-kn97bq a[rel='noopener noreferrer'] img.item-card__img",
        "div.img-wrap__discount.css-kn97bq a[rel='noopener noreferrer'] img",
        "div.css-kn97bq a[rel='noopener noreferrer'] img",
        # 최후 fallback
        "a[rel='noopener noreferrer'] img.item-card__img",
        "a[rel='noopener noreferrer'] img",
    ]

    img_src = ""
    for sel in selectors:
        try:
            img = li.locator(sel).first
            if img.count() == 0:
                continue
            src = (img.get_attribute("src") or "").strip()
            if not src:
                # lazy loading 케이스
                src = (img.get_attribute("data-src") or "").strip()
            if src:
                img_src = src
                break
        except Exception:
            continue

    if not img_src:
        return ""

    img_url = img_src if img_src.startswith("http") else urljoin(page.url or URL, img_src)
    try:
        resp = page.request.get(img_url, timeout=20000)
        if not resp or not resp.ok:
            return ""
        body = resp.body()
        if not body:
            return ""
        out_path.write_bytes(body)
        try:
            return str(out_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        except Exception:
            return str(out_path).replace("\\", "/")
    except Exception as e:
        logger.debug("이미지 다운로드 실패: %s (%s)", img_url, e)
        return ""


def _dismiss_popups_kiacar(page, logger):
    """
    기아 CPO 사이트 진입 시 뜨는 상담/배너 팝업 등을 최대한 닫는다.
    - '오늘 그만 보기', '닫기' 버튼 우선 클릭
    - 모달 배경(.ReactModal__Overlay 등)이 있으면 닫기 버튼 추정해서 클릭
    """
    try:
        for _ in range(4):
            clicked = False
            # 1) 오늘 그만 보기 / 닫기
            for txt in ["오늘 그만 보기", "오늘만 보기", "닫기", "닫 기"]:
                try:
                    btn = page.locator(f"button:has-text('{txt}'), a:has-text('{txt}')").first
                    if btn.count() > 0 and btn.is_visible(timeout=800):
                        btn.click()
                        page.wait_for_timeout(800)
                        logger.info("팝업 버튼 클릭: %s", txt)
                        clicked = True
                        break
                except Exception:
                    continue
            if clicked:
                continue
            # 2) 모달 닫기(X 아이콘 추정)
            try:
                close_icon = page.locator("button[aria-label*='닫기'], button[aria-label*='close']").first
                if close_icon.count() > 0 and close_icon.is_visible(timeout=800):
                    close_icon.click()
                    page.wait_for_timeout(800)
                    logger.info("모달 닫기 버튼 클릭(aria-label).")
                    clicked = True
            except Exception:
                pass
            if not clicked:
                break
    except Exception as e:
        logger.debug("팝업 닫기 중 오류(무시): %s", e)


def _next_child_container(btn_locator):
    """
    버튼(depth1~4) 바로 다음 형제 div.child를 반환.
    (현재 페이지 HTML: <div class='model-select__btn depthX'>...</div><div class='child'>...</div>)
    """
    try:
        # playwright locator에서 following-sibling은 xpath로 처리
        sib = btn_locator.locator("xpath=following-sibling::div[contains(@class,'child')][1]").first
        if sib.count() > 0:
            return sib
    except Exception:
        pass
    try:
        # fallback: 부모에서 child를 찾되, 첫번째로 뭉뚱그려 잡히는 경우가 있어 최후수단
        parent = btn_locator.locator("xpath=..")
        return parent.locator(SELECTOR_CHILD).first
    except Exception:
        return btn_locator.locator(SELECTOR_CHILD).first


def _collect_rows_in_page(page, base_selector: str, logger):
    """
    브라우저 페이지 내부 JS로 depth1~4 트리를 순회하며 rows(list of dict)를 반환.
    - 각 depth 버튼을 click()하여 active+checked 상태가 되도록 시도
    - 버튼의 nextElementSibling(.child) 기준으로 하위 탐색 (사용자가 준 HTML 구조와 동일)
    """
    js = r"""
    (baseSel) => {
      const base = document.querySelector(baseSel) || document.querySelector('.css-hu289v');
      if (!base) return { ok: false, reason: 'base_not_found', rows: [] };

      const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
      const nameOf = (btn) => norm(btn?.querySelector?.('.item-txt__name')?.textContent || '');
      const isActiveChecked = (btn) => !!(btn && btn.classList && btn.classList.contains('active') && btn.classList.contains('checked'));
      const clickAndMark = (btn) => {
        if (!btn) return false;
        try { btn.scrollIntoView({ block: 'center' }); } catch(e) {}
        try { btn.click(); } catch(e) {}
        // 일부 UI는 클릭 후 즉시 class가 붙음. 안 붙으면 그대로 진행(수집은 DOM 기반).
        return isActiveChecked(btn);
      };
      const nextChild = (btn) => {
        const sib = btn?.nextElementSibling;
        if (sib && sib.classList && sib.classList.contains('child')) return sib;
        return null;
      };

      const rows = [];

      const depth1Btns = Array.from(base.querySelectorAll('.model-select__btn.depth1'));
      for (const d1 of depth1Btns) {
        clickAndMark(d1);
        const car_list = nameOf(d1);
        const c1 = nextChild(d1);
        if (!c1) {
          rows.push({ car_list, model_list: '', model_list_1: '', model_list_2: '' });
          continue;
        }
        const depth2Btns = Array.from(c1.querySelectorAll(':scope > .model-select__btn.depth2'));
        if (depth2Btns.length === 0) {
          rows.push({ car_list, model_list: '', model_list_1: '', model_list_2: '' });
          continue;
        }
        for (const d2 of depth2Btns) {
          clickAndMark(d2);
          const model_list = nameOf(d2);
          const c2 = nextChild(d2);
          if (!c2) {
            rows.push({ car_list, model_list, model_list_1: '', model_list_2: '' });
            continue;
          }
          const depth3Btns = Array.from(c2.querySelectorAll(':scope > .model-select__btn.depth3'));
          if (depth3Btns.length === 0) {
            rows.push({ car_list, model_list, model_list_1: '', model_list_2: '' });
            continue;
          }
          for (const d3 of depth3Btns) {
            clickAndMark(d3);
            const model_list_1 = nameOf(d3);
            const c3 = nextChild(d3);
            if (!c3) {
              rows.push({ car_list, model_list, model_list_1, model_list_2: '' });
              continue;
            }
            const depth4Btns = Array.from(c3.querySelectorAll(':scope > .model-select__btn.depth4'));
            if (depth4Btns.length === 0) {
              rows.push({ car_list, model_list, model_list_1, model_list_2: '' });
              continue;
            }
            for (const d4 of depth4Btns) {
              clickAndMark(d4);
              const model_list_2 = nameOf(d4);
              rows.push({ car_list, model_list, model_list_1, model_list_2 });
            }
          }
        }
      }
      return { ok: true, rows };
    }
    """
    try:
        res = page.evaluate(js, base_selector)
    except Exception as e:
        logger.warning("페이지 내 트리 수집(evaluate) 실패: %s", e)
        return []
    if not res or not res.get("ok"):
        logger.warning("페이지 내 트리 수집 결과 ok 아님: %s", (res or {}).get("reason"))
        return []
    return res.get("rows") or []


def _collect_depth4_rows(page, base_locator, car_list, model_list, model_list_1, depth3_locator, writer, model_sn_ref, now, logger):
    """depth3 한 개에 대해 depth4 목록 수집 후 행 기록. depth4 없으면 1행만."""
    data_crtr_pnttm, create_dt = _timestamps()
    child3 = _next_child_container(depth3_locator)
    if child3.count() == 0:
        model_sn_ref[0] += 1
        writer.writerow({
            "model_sn": model_sn_ref[0],
            "car_list": car_list or "",
            "model_list": model_list or "",
            "model_list_1": model_list_1 or "",
            "model_list_2": "",
            "data_crtr_pnttm": data_crtr_pnttm,
            "create_dt": create_dt,
        })
        return
    depth4_btns = child3.locator(SELECTOR_DEPTH4)
    n4 = depth4_btns.count()
    if n4 == 0:
        model_sn_ref[0] += 1
        writer.writerow({
            "model_sn": model_sn_ref[0],
            "car_list": car_list or "",
            "model_list": model_list or "",
            "model_list_1": model_list_1 or "",
            "model_list_2": "",
            "data_crtr_pnttm": data_crtr_pnttm,
            "create_dt": create_dt,
        })
        return
    for i in range(n4):
        model_list_2 = _get_name(depth4_btns.nth(i))
        model_sn_ref[0] += 1
        writer.writerow({
            "model_sn": model_sn_ref[0],
            "car_list": car_list or "",
            "model_list": model_list or "",
            "model_list_1": model_list_1 or "",
            "model_list_2": model_list_2 or "",
            "data_crtr_pnttm": data_crtr_pnttm,
            "create_dt": create_dt,
        })


def _collect_depth3_rows(page, base_locator, car_list, model_list, depth2_locator, writer, model_sn_ref, now, logger):
    """depth2 한 개에 대해 depth3 목록 수집 후 depth4까지 재귀."""
    _activate_btn(page, depth2_locator, logger)
    page.wait_for_timeout(300)
    child2 = _next_child_container(depth2_locator)
    if child2.count() == 0:
        data_crtr_pnttm, create_dt = _timestamps()
        model_sn_ref[0] += 1
        writer.writerow({
            "model_sn": model_sn_ref[0],
            "car_list": car_list or "",
            "model_list": model_list or "",
            "model_list_1": "",
            "model_list_2": "",
            "data_crtr_pnttm": data_crtr_pnttm,
            "create_dt": create_dt,
        })
        return
    depth3_btns = child2.locator(SELECTOR_DEPTH3)
    n3 = depth3_btns.count()
    if n3 == 0:
        data_crtr_pnttm, create_dt = _timestamps()
        model_sn_ref[0] += 1
        writer.writerow({
            "model_sn": model_sn_ref[0],
            "car_list": car_list or "",
            "model_list": model_list or "",
            "model_list_1": "",
            "model_list_2": "",
            "data_crtr_pnttm": data_crtr_pnttm,
            "create_dt": create_dt,
        })
        return
    for i in range(n3):
        d3 = depth3_btns.nth(i)
        model_list_1 = _get_name(d3)
        _activate_btn(page, d3, logger)
        page.wait_for_timeout(250)
        _collect_depth4_rows(page, base_locator, car_list, model_list, model_list_1, d3, writer, model_sn_ref, now, logger)


def _collect_depth2_rows(page, base_locator, car_list, depth1_locator, writer, model_sn_ref, now, logger):
    """depth1 한 개에 대해 depth2 목록 수집 후 depth3/depth4까지 재귀."""
    _activate_btn(page, depth1_locator, logger)
    page.wait_for_timeout(400)
    child1 = _next_child_container(depth1_locator)
    if child1.count() == 0:
        data_crtr_pnttm, create_dt = _timestamps()
        model_sn_ref[0] += 1
        writer.writerow({
            "model_sn": model_sn_ref[0],
            "car_list": car_list or "",
            "model_list": "",
            "model_list_1": "",
            "model_list_2": "",
            "data_crtr_pnttm": data_crtr_pnttm,
            "create_dt": create_dt,
        })
        return
    depth2_btns = child1.locator(SELECTOR_DEPTH2)
    n2 = depth2_btns.count()
    if n2 == 0:
        data_crtr_pnttm, create_dt = _timestamps()
        model_sn_ref[0] += 1
        writer.writerow({
            "model_sn": model_sn_ref[0],
            "car_list": car_list or "",
            "model_list": "",
            "model_list_1": "",
            "model_list_2": "",
            "data_crtr_pnttm": data_crtr_pnttm,
            "create_dt": create_dt,
        })
        return
    for i in range(n2):
        d2 = depth2_btns.nth(i)
        model_list = _get_name(d2)
        _collect_depth3_rows(page, base_locator, car_list, model_list, d2, writer, model_sn_ref, now, logger)


def run_kiacar_brand_list(page, result_dir: Path, logger):
    """
    기아 CPO products 페이지에서 필터 트리(depth1→depth2→depth3→depth4) 수집.
    brand_list, car_type, car_list, model_list, model_list_1, model_list_2(빈값) 및 model_sn, data_crtr_pnttm, create_dt 저장.
    """
    result_dir.mkdir(parents=True, exist_ok=True)
    csv_path = result_dir / "kiacar_brand_list.csv"
    if csv_path.exists():
        csv_path.unlink()

    headers = [
        "model_sn",
        "brand_list",
        "car_type",
        "car_list",
        "model_list",
        "model_list_1",
        "model_list_2",
        "data_crtr_pnttm",
        "create_dt",
    ]

    try:
        logger.info("============================================================")
        logger.info("기아 인증중고차(CPO) 차종/모델 목록 수집 시작: %s", URL)
        logger.info("============================================================")

        if URL not in (page.url or ""):
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)

        base = None
        for sel in (SELECTOR_BASE, SELECTOR_BASE_FALLBACK, ".filter-info .filter-info__content", ".css-hu289v"):
            try:
                loc = page.locator(sel)
                loc.first.wait_for(state="visible", timeout=10000)
                base = loc
                # logger.info("필터 영역 로드됨: %s", sel)
                break
            except Exception as e:
                logger.debug("셀렉터 실패 %s: %s", sel, e)
                continue

        if base is None:
            logger.warning("필터 영역(.css-hu289v 또는 .filter-info__content)을 찾지 못했습니다.")
            return

        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            w.writeheader()
            f.flush()

            rows = _collect_rows_in_page(page, SELECTOR_BASE, logger)
            if not rows:
                # fallback: base selector가 다른 경우를 위해 대체 셀렉터로도 시도
                rows = _collect_rows_in_page(page, SELECTOR_BASE_FALLBACK, logger)
            if not rows:
                logger.warning("수집된 rows가 0건입니다. (DOM이 아직 렌더링되지 않았거나 셀렉터가 변경됨)")
                return

            logger.info("트리 rows %d건 수집, CSV 기록 시작", len(rows))
            model_sn = 0
            for r in rows:
                model_sn += 1
                data_crtr_pnttm, create_dt = _timestamps()
                w.writerow({
                    "model_sn": model_sn,
                    "brand_list": "기아",
                    "car_type": (r.get("car_list") or "").strip(),
                    "car_list": (r.get("model_list") or "").strip(),
                    "model_list": (r.get("model_list_1") or "").strip(),
                    "model_list_1": (r.get("model_list_2") or "").strip(),
                    "model_list_2": "",
                    "data_crtr_pnttm": data_crtr_pnttm,
                    "create_dt": create_dt,
                })
            f.flush()

        logger.info("============================================================")
        logger.info("저장 완료: %s", csv_path)
        logger.info("============================================================")
    except Exception as e:
        logger.error("기아 브랜드 목록 수집 오류: %s", e, exc_info=True)


def run_kiacar_product_list(page, result_dir: Path, logger):
    """
    EV/승용/RV 선택 없이, 페이지 로드 후 무한 스크롤만으로 전체 차량 목록 수집.

    - li.item-card.is-pc 중 EXCLUDE_ITEM_CLASS(css-1759cna) 제외
    - brand 매칭(car_name_1↔model_list)으로 brand_list, car_type, car_list, model_list 까지만 합침. car_num, underline 컬럼 없음.
    """
    result_dir.mkdir(parents=True, exist_ok=True)
    csv_path = result_dir / "kiacar_list.csv"
    # 프로그램 시작 시(이 함수 진입 시)에만 list.csv 삭제 → 같은 실행 안에서는 행만 계속 추가
    if csv_path.exists():
        csv_path.unlink()

    headers = [
        "model_sn",
        "product_id",
        "car_type",
        "brand_list",
        "car_list",
        "model_list",
        "car_name",
        "line_up",
        "release_dt",
        "car_navi",
        "price",
        "discount",
        "badge_discount",
        "reserve",
        "detail_url",
        "car_imgs",
        "date_crtr_pnttm",
        "create_dt",
    ]

    try:
        logger.info("============================================================")
        logger.info("기아 인증중고차(CPO) 차량 목록 수집 (필터 없음, 무한스크롤만): %s", URL)
        logger.info("============================================================")

        if URL not in (page.url or ""):
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3500)

        # 항상 '오늘 그만 보기' 등 팝업 먼저 닫기
        _dismiss_popups_kiacar(page, logger)
        page.wait_for_timeout(1000)

        page.wait_for_selector(SELECTOR_CAR_LIST_ROOT, timeout=20000)
        page.wait_for_timeout(800)

        # 무한 스크롤로 끝까지 로딩
        prev_n = -1
        stable = 0
        for step in range(1, 260):
            items_loc = page.locator(SELECTOR_CAR_ITEM)
            n = items_loc.count()
            delta = 0 if prev_n < 0 else (n - prev_n)
            # logger.info("  - 스크롤 %d회차: 로드된 카드 수=%d (Δ %s)", step, n, delta)
            if n == prev_n:
                stable += 1
                if stable >= 4 and n > 0:
                    break
            else:
                stable = 0
            prev_n = n
            if n == 0:
                page.wait_for_timeout(800)
                continue
            try:
                items_loc.nth(n - 1).scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass
            page.wait_for_timeout(900)

        items_loc = page.locator(SELECTOR_CAR_ITEM)
        total_li = items_loc.count()
        logger.info("  → 최종 카드 수(스크롤 후): %d", total_li)

        # 이미지 저장 폴더: config 기반 공통 경로(imgs/kiacar/list/{연도}년/{YYYYMMDD})
        img_dir = get_list_image_save_dir("kiacar", datetime.now())

        # brand.csv를 미리 로드해서, 수집하면서 바로 brand 컬럼 채우기
        brand_path = result_dir / "kiacar_brand_list.csv"
        brand_map = {}
        if brand_path.exists():
            try:
                with open(brand_path, "r", encoding="utf-8-sig") as bf:
                    br = csv.DictReader(bf)
                    for brow in br:
                        key = (brow.get("model_list") or "").strip()
                        if not key or key in brand_map:
                            continue
                        brand_map[key] = {
                            "brand_list": (brow.get("brand_list") or "").strip(),
                            "car_type": (brow.get("car_type") or "").strip(),
                            "car_list": (brow.get("car_list") or "").strip(),
                            "model_list": (brow.get("model_list") or "").strip(),
                        }
                logger.info("brand 매핑 로드: %d건", len(brand_map))
            except Exception as e:
                logger.warning("brand 매핑 로드 실패(무시): %s", e)
        else:
            logger.warning("brand.csv 없음: %s (brand 컬럼은 enrich 또는 후처리 필요)", brand_path)

        def _match_key_from_car_name(car_name_val: str) -> str:
            s = (car_name_val or "").strip()
            if not s:
                return ""
            parts = s.split()
            if len(parts) >= 2 and len(parts[0]) == 4 and parts[0].isdigit():
                return (parts[0] + " " + parts[1]).strip()
            return parts[0].strip() if parts else ""

        seen = set()
        model_sn = 0
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            w.writeheader()
            f.flush()
            for idx in range(total_li):
                li = items_loc.nth(idx)
                try:
                    cls = li.get_attribute("class") or ""
                    if EXCLUDE_ITEM_CLASS in cls:
                        continue
                except Exception:
                    continue
                row = _extract_row_from_kiacar_card(li, "")
                pid = (row.get("product_id") or "").strip()
                if not pid:
                    continue
                if pid in seen:
                    continue
                seen.add(pid)
                model_sn += 1
                date_crtr_pnttm, create_dt = _timestamps()
                car_name = ((row.get("car_name_1") or "").strip() + " " + (row.get("car_name_2") or "").strip()).strip()
                match_key = _match_key_from_car_name(row.get("car_name_1") or car_name)
                bm = brand_map.get(match_key) if match_key else None

                # 카드 썸네일(첫번째 img) 저장: {product_id}_list.png
                car_imgs = ""
                try:
                    car_imgs = _download_kiacar_card_first_img(page, li, img_dir, f"{pid}_list", logger) or ""
                except Exception:
                    pass

                w.writerow({
                    "model_sn": model_sn,
                    "product_id": pid,
                    "car_type": (bm.get("car_type") if bm else "") or "",
                    "brand_list": (bm.get("brand_list") if bm else "") or "",
                    "car_list": (bm.get("car_list") if bm else "") or "",
                    "model_list": (bm.get("model_list") if bm else "") or "",
                    "car_name": car_name,
                    "line_up": row.get("line_up") or "",
                    "release_dt": row.get("release_dt") or "",
                    "car_navi": row.get("car_navi") or "",
                    "price": row.get("price") or "",
                    "discount": row.get("discount") or "",
                    "badge_discount": row.get("badge_discount") or "",
                    "reserve": row.get("reserve") or "",
                    "detail_url": f"https://cpo.kia.com/products/detail/?id={pid}",
                    "car_imgs": car_imgs,
                    "date_crtr_pnttm": date_crtr_pnttm,
                    "create_dt": create_dt,
                })
                f.flush()
                if model_sn <= 5 or model_sn % 50 == 0:
                    logger.info("  [%d/%d] product_id=%s", model_sn, total_li, pid)
            f.flush()

        logger.info("============================================================")
        logger.info("저장 완료: %s (총 %d건)", csv_path, model_sn)
        logger.info("============================================================")
        # list 저장 직후에도 한번 더 보정 (brand.csv가 늦게 생기거나 일부 누락 대비)
        enrich_kiacar_list_with_brand(result_dir, logger)
    except Exception as e:
        logger.error("기아 차량 카드 목록 수집 오류: %s", e, exc_info=True)


def enrich_kiacar_list_with_brand(result_dir: Path, logger):
    """
    list의 car_name 앞부분(연도+모델) == brand model_list 로 매칭하여 brand_list, car_type, car_list, model_list 넣는다. list에는 car_name만 저장(car_name_1 컬럼 없음). car_num, underline 제거.
    """
    result_dir = result_dir.resolve()
    brand_path = result_dir / "kiacar_brand_list.csv"
    list_path = result_dir / "kiacar_list.csv"
    logger.info("enrich: brand_path=%s list_path=%s", brand_path, list_path)
    if not brand_path.exists():
        logger.warning("brand 목록 없음, 매칭 생략: %s", brand_path)
        return
    if not list_path.exists():
        logger.warning("list 목록 없음, 매칭 생략: %s", list_path)
        return

    # brand_list.csv에서 model_list(또는 구형식 model_list_1) → (brand_list, car_type, car_list, model_list, model_list_1) 맵 구성
    # 새 형식: car_type, car_list, model_list(depth3), model_list_1(depth4) / 구 형식: car_list(depth1), model_list(depth2), model_list_1(depth3)
    key_to_brand = {}
    with open(brand_path, "r", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        for row in r:
            ml = (row.get("model_list") or "").strip()
            ml1 = (row.get("model_list_1") or "").strip()
            # 매칭 키: depth3 값 (연도로 시작하면 model_list가 depth3, 아니면 model_list_1이 depth3)
            k = ml if (ml and len(ml) > 0 and ml[0].isdigit()) else ml1
            if not k:
                k = ml or ml1
            if k and k not in key_to_brand:
                # 새 형식: car_type 있음, car_list=depth2. 구 형식: car_list=depth1, model_list=depth2
                has_car_type = bool((row.get("car_type") or "").strip())
                key_to_brand[k] = {
                    "brand_list": (row.get("brand_list") or "").strip(),
                    "car_type": (row.get("car_type") or row.get("car_list") or "").strip(),
                    "car_list": (row.get("car_list") or row.get("model_list") or "").strip() if has_car_type else (row.get("model_list") or "").strip(),
                    "model_list": (row.get("model_list") or row.get("model_list_1") or "").strip(),
                    "model_list_1": (row.get("model_list_1") or row.get("model_list_2") or "").strip(),
                }
    logger.info("enrich: brand 키 %d건 로드", len(key_to_brand))

    rows = []
    list_headers = None
    with open(list_path, "r", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        list_headers = list(r.fieldnames) if r.fieldnames else []
        for row in r:
            rows.append(dict(row))

    # list.csv에서 car_num, underline, model_list_1, car_name_1 제거. 매칭은 car_name 앞부분(연도+모델)으로 수행
    list_headers = [x for x in list_headers if x not in ("car_num", "underline", "model_list_1", "car_name_1")]
    if "car_name" not in list_headers:
        idx = list_headers.index("model_list") + 1 if "model_list" in list_headers else len(list_headers)
        list_headers.insert(idx, "car_name")
    if "car_imgs" not in list_headers:
        # product_id 다음(brand 컬럼들 앞쪽)에 두고 싶으면 여기 위치 조정 가능. 기본은 model_list 다음에 추가.
        idx = list_headers.index("model_list") + 1 if "model_list" in list_headers else len(list_headers)
        list_headers.insert(idx, "car_imgs")

    # list.csv 컬럼 순서를 model_sn, product_id, car_type, brand_list, ... 로 맞추기 위해
    # car_type 을 brand_list 보다 앞에 두도록 키 순서를 정의
    enrich_keys = ("car_type", "brand_list", "car_list", "model_list")
    for h in enrich_keys:
        if h not in list_headers:
            list_headers = list(list_headers)
            idx = next((i + 1 for i, n in enumerate(list_headers) if n == "product_id"), len(list_headers))
            list_headers = list_headers[:idx] + list(enrich_keys) + [x for x in list_headers if x not in enrich_keys]
            break

    def _car_name_to_match_key(car_name_val: str):
        """car_name 등에서 brand model_list와 비교할 키 추출 (연도+모델명). car_name_1이 없을 때만 사용."""
        s = (car_name_val or "").strip()
        if not s:
            return ""
        parts = s.split()
        if len(parts) >= 2 and len(parts[0]) == 4 and parts[0].isdigit():
            return (parts[0] + " " + parts[1]).strip()
        return parts[0].strip() if parts else ""

    def find_brand(match_key: str):
        """car_name에서 뽑은 연도+모델(match_key)로 brand model_list와 비교."""
        c = (match_key or "").strip()
        if not c:
            return None
        if c in key_to_brand:
            return key_to_brand[c]
        # 1) startswith 매칭: "2024 니로" ↔ "2024 니로 EV"
        candidates = [k for k in key_to_brand if k.startswith(c) or c.startswith(k)]
        if candidates:
            return key_to_brand[max(candidates, key=len)]
        # 2) 모델명 포함 매칭: "2021 쏘렌토" → 모델 "쏘렌토", 연도 "2021" / brand 키 중 "쏘렌토" 포함·같은 연도 우선
        parts = c.split()
        year = parts[0] if (len(parts) >= 1 and len(parts[0]) == 4 and parts[0].isdigit()) else ""
        model = parts[1] if len(parts) >= 2 else (parts[0] if parts else "")
        if not model:
            return None
        candidates = [k for k in key_to_brand if (model in k or k in model or (year and k.startswith(year + " " + model)))]
        if not candidates:
            return None
        # 같은 연도로 시작하는 키 우선, 그 다음 가장 긴 키
        with_year = [k for k in candidates if year and k.startswith(year)]
        pool = with_year if with_year else candidates
        return key_to_brand[max(pool, key=len)]

    for row in rows:
        # 매칭은 car_name 앞부분(연도+모델)으로. list에는 car_name만 있음
        match_key = _car_name_to_match_key(row.get("car_name") or "")
        b = find_brand(match_key)
        if b:
            row["brand_list"] = b["brand_list"]
            row["car_type"] = b["car_type"]
            row["car_list"] = b["car_list"]
            row["model_list"] = b["model_list"]
        else:
            for k in enrich_keys:
                if k not in row:
                    row[k] = ""
                else:
                    row[k] = row.get(k) or ""

        # car_imgs 컬럼은 enrich에서 건드리지 않음 (있으면 유지, 없으면 빈값)
        if "car_imgs" in list_headers and "car_imgs" not in row:
            row["car_imgs"] = ""

    list_path = list_path.resolve()
    try:
        with open(list_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list_headers, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
            f.flush()
            if hasattr(f, "fileno"):
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
    except Exception as e:
        logger.error("enrich list 저장 실패: %s → %s", list_path, e, exc_info=True)
        return

    matched = sum(1 for r in rows if find_brand(_car_name_to_match_key(r.get("car_name") or "")))
    logger.info("list↔brand 매칭 완료: %d/%d건 (car_name↔model_list) → 저장: %s", matched, len(rows), list_path)


def main():
    logger = setup_logger()
    result_dir = Path(__file__).resolve().parent.parent / "result" / "kiacar"
    with sync_playwright() as p:
        # 창 띄워서(headed) 동작 확인용
        # KIA_HEADED=1 이면 headed, 0 이면 headless
        # KIA_SLOWMO=500 처럼 주면 클릭/스크롤을 천천히(밀리초) 재생
        headed = os.environ.get("KIA_HEADED", "1").strip().lower() in ("1", "true", "yes")
        try:
            slow_mo = int(os.environ.get("KIA_SLOWMO", "0").strip() or "0")
        except Exception:
            slow_mo = 0
        # headed로 볼 때 기본 slow_mo를 줘서 클릭이 눈에 보이게
        if headed and slow_mo == 0:
            slow_mo = 250
        try:
            browser = p.chromium.launch(channel="chrome", headless=not headed, slow_mo=slow_mo or None)
        except Exception:
            browser = p.chromium.launch(headless=not headed, slow_mo=slow_mo or None)
        try:
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = context.new_page()
            run_kiacar_brand_list(page, result_dir, logger)
            run_kiacar_product_list(page, result_dir, logger)
            enrich_kiacar_list_with_brand(result_dir, logger)
        finally:
            browser.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].strip() in ("--enrich-only", "-e"):
        # list.csv / kiacar_brand_list.csv 가 있는 경로에서 enrich만 실행 (브랜드 컬럼 채우기)
        logger = setup_logger()
        result_dir = Path(__file__).resolve().parent.parent / "result" / "kiacar"
        result_dir = result_dir.resolve()
        logger.info("enrich만 실행: result_dir=%s", result_dir)
        enrich_kiacar_list_with_brand(result_dir, logger)
        sys.exit(0)
    main()
