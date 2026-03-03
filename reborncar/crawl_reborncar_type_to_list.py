import csv
import logging
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

def setup_logger():
    log_dir = Path("./logs/reborncar")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "reborncar_list_detail.log"
    logger = logging.getLogger("RebornCar")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh = logging.FileHandler(log_path, encoding='utf-8'); logger.addHandler(fh)
        sh = logging.StreamHandler(); logger.addHandler(sh)
    return logger

def load_brand_model_map(result_dir):
    """reborncar_brand_list.csv 또는 reborncar_brand.csv에서 model_list(| 앞부분) -> brand_list, car_list 매핑 로드."""
    model_to_brand = {}
    model_to_car_list = {}
    brand_path = result_dir / "reborncar_brand_list.csv"
    if not brand_path.exists():
        brand_path = result_dir / "reborncar_brand.csv"
    if not brand_path.exists():
        return model_to_brand, model_to_car_list
    try:
        with open(brand_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                model_list_raw = (row.get("model_list") or "").strip()
                brand_list = (row.get("brand_list") or "").strip()
                car_list = (row.get("car_list") or "").strip()
                if not brand_list:
                    continue
                # model_list에서 | 앞부분만 키로 사용 (e.g. '올 뉴K3|(18~21년)' -> '올 뉴K3')
                model_key = model_list_raw.split("|")[0].strip() if model_list_raw else ""
                if model_key and model_key not in model_to_brand:
                    model_to_brand[model_key] = brand_list
                    model_to_car_list[model_key] = car_list if car_list else "-"
    except Exception:
        pass
    return model_to_brand, model_to_car_list

def _get_model_key_for_lp_car_name(lp_car_name, model_keys):
    """lp_car_name으로 model_keys 중 매칭되는 키 반환. 없으면 None."""
    name = (lp_car_name or "").strip()
    if not name or not model_keys:
        return None
    if name in model_keys:
        return name
    parts = name.rsplit(maxsplit=1)
    if len(parts) >= 2:
        last_part = parts[-1].strip()
        if last_part in model_keys:
            return last_part
    return None

def get_brand_for_lp_car_name(lp_car_name, model_to_brand):
    """lp_car_name과 brand의 model_list(| 앞) 매칭. 실패 시 lp_car_name 뒤에서 띄어쓰기 기준 마지막 부분으로 재매칭."""
    key = _get_model_key_for_lp_car_name(lp_car_name, model_to_brand)
    return model_to_brand[key] if key else "-"

def get_car_list_for_lp_car_name(lp_car_name, model_to_car_list):
    """lp_car_name으로 brand의 model_list(| 앞) 매칭 후 해당 car_list 반환."""
    key = _get_model_key_for_lp_car_name(lp_car_name, model_to_car_list)
    return model_to_car_list.get(key, "-") if key else "-"

def split_boname_by_last_paren(text):
    """뒤에서부터 첫 번째 ()를 기준으로 나누어 '앞부분|(괄호내용)' 형태로 반환 (crawl_reborncar_brand.py와 동일)."""
    if not text or "(" not in text:
        return text
    last_open = text.rfind("(")
    prefix = text[:last_open].strip()
    suffix = text[last_open:].strip()
    if not prefix:
        return text
    return f"{prefix}|{suffix}"

def run_reborncar_brand(page, result_dir, logger):
    """브랜드·차종·모델 계층 수집 → reborncar_brand_list.csv (기존 삭제 후 행 단위 append, 중간 끊겨도 유지)."""
    now = datetime.now()
    pnttm = now.strftime("%Y%m%d")
    create_dt = now.strftime("%Y%m%d%H%M")
    csv_path = result_dir / "reborncar_brand_list.csv"
    if csv_path.exists():
        csv_path.unlink()
    headers = ["model_sn", "brand_list", "car_list", "model_list", "date_crtr_pnttm", "create_dt"]
    model_sn = 1
    try:
        logger.info("리본카 브랜드 계층 수집 시작...")
        page.goto("https://www.reborncar.co.kr/smartbuy/SB1001.rb", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector(".filter-brand .brand-list", timeout=30000)
        page.wait_for_timeout(1500)
        brand_selectors = page.locator(".filter-brand .brand-list")
        brand_count = brand_selectors.count()
        for i in range(brand_count):
            brand_box = brand_selectors.nth(i)
            brand_list = brand_box.locator(".brand-name label span").inner_text().strip()
            logger.info(f"[{brand_list}] 처리 중...")
            brand_box.locator(".brand-name label").click()
            page.wait_for_timeout(400)
            car_items = brand_box.locator(".car-list .check-box[class*='car-']")
            car_count = car_items.count()
            for j in range(car_count):
                car_box = car_items.nth(j)
                car_list = car_box.locator("label span").first.inner_text().strip()
                car_box.locator("label").first.click()
                page.wait_for_timeout(300)
                detail_boxes = car_box.locator(".model-list .check-box")
                detail_count = detail_boxes.count()
                if detail_count > 0:
                    for k in range(detail_count):
                        full_boname = detail_boxes.nth(k).locator("label span").inner_text().strip()
                        row = {
                            "model_sn": model_sn, "brand_list": brand_list, "car_list": car_list,
                            "model_list": split_boname_by_last_paren(full_boname),
                            "date_crtr_pnttm": pnttm, "create_dt": create_dt
                        }
                        with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
                            w = csv.DictWriter(f, fieldnames=headers)
                            if model_sn == 1:
                                w.writeheader()
                            w.writerow(row)
                        model_sn += 1
                else:
                    row = {
                        "model_sn": model_sn, "brand_list": brand_list, "car_list": car_list,
                        "model_list": split_boname_by_last_paren(car_list),
                        "date_crtr_pnttm": pnttm, "create_dt": create_dt
                    }
                    with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
                        w = csv.DictWriter(f, fieldnames=headers)
                        if model_sn == 1:
                            w.writeheader()
                        w.writerow(row)
                    model_sn += 1
        if model_sn > 1:
            logger.info(f"브랜드 CSV 저장 완료: {csv_path} ({model_sn - 1}행)")
        else:
            logger.warning("브랜드 수집 데이터 없음.")
    except Exception as e:
        logger.error(f"브랜드 수집 오류: {e}")

def run_reborncar_car_type(page, result_dir, logger):
    """차종(car_type) 수집 → reborncar_car_type_list.csv (기존 삭제 후 행 단위 append, 중간 끊겨도 유지)."""
    result_path = result_dir / "reborncar_car_type_list.csv"
    if result_path.exists():
        result_path.unlink()
    headers = ["car_type_sn", "cate_cb", "car_type_name"]
    car_type_sn = 1
    try:
        logger.info("리본카 차종(car_type) 수집 시작...")
        page.goto("https://www.reborncar.co.kr/smartbuy/SB1001.rb", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("input.cate-cb[id^='car_type']", state="attached", timeout=30000)
        page.wait_for_timeout(1000)
        car_type_elements = page.locator("input.cate-cb[id^='car_type']").all()
        for el in car_type_elements:
            el_id = el.get_attribute("id")
            cate_cb = el.get_attribute("value")
            label_span = page.locator(f"label[for='{el_id}'] span")
            if label_span.count() > 0:
                car_type_name = label_span.inner_text().strip()
                row = {"car_type_sn": car_type_sn, "cate_cb": cate_cb, "car_type_name": car_type_name}
                with open(result_path, "a", newline="", encoding="utf-8-sig") as f:
                    w = csv.DictWriter(f, fieldnames=headers)
                    if car_type_sn == 1:
                        w.writeheader()
                    w.writerow(row)
                car_type_sn += 1
        if car_type_sn > 1:
            logger.info(f"차종 CSV 저장 완료: {result_path} ({car_type_sn - 1}건)")
        else:
            logger.warning("차종 데이터 없음.")
    except Exception as e:
        logger.error(f"차종 수집 오류: {e}")

def save_detail_images(page, product_id, save_dir, detail_url, logger):
    """상세 페이지 vip-visual 영역 이미지를 product_id_1.png, product_id_2.png ... 로 저장."""
    if not product_id or not save_dir:
        return
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    base_url = detail_url.rsplit("?", 1)[0] if "?" in detail_url else detail_url
    urls = []
    # 1) #wrap .vip-section .vip-visual .vip-visual-detail .visual-detail .detail-img 내 이미지
    detail_imgs = page.locator("#wrap .vip-section .vip-visual .vip-visual-detail .visual-detail .detail-img img")
    for i in range(detail_imgs.count()):
        src = detail_imgs.nth(i).get_attribute("src")
        if src:
            urls.append(src)
    if not urls:
        single = page.locator("#wrap .vip-section .vip-visual .vip-visual-detail .visual-detail img.detail-img").first
        if single.count() > 0:
            src = single.get_attribute("src")
            if src:
                urls.append(src)
    # 2) .vip-visual-list .visual-box .visual-con 내 이미지
    list_imgs = page.locator("#wrap .vip-section .vip-visual .vip-visual-list .visual-box .visual-con img")
    for i in range(list_imgs.count()):
        src = list_imgs.nth(i).get_attribute("src")
        if src:
            urls.append(src)
    saved_count = 0
    for idx, src in enumerate(urls, start=1):
        try:
            full_url = urljoin(base_url, src) if not (src.startswith("http") or src.startswith("//")) else ("https:" + src if src.startswith("//") else src)
            resp = page.request.get(full_url)
            if resp.ok:
                path = save_dir / f"{product_id}_{idx}.png"
                path.write_bytes(resp.body())
                # logger.info(f"이미지 저장: {path}")
                saved_count += 1
        except Exception as e:
            logger.warning(f"이미지 저장 실패 ({product_id}_{idx}): {e}")
    if saved_count > 0:
        logger.info(f"{product_id} 이미지 수집 완료")

def fetch_detail_images_only(page, product_id, img_save_dir, logger):
    """상세 페이지 접속 후 vip-visual 이미지만 저장 (detail CSV 없음)."""
    detail_url = f"https://www.reborncar.co.kr/smartbuy/SB1002.rb?productId={product_id}"
    try:
        page.goto(detail_url, wait_until="domcontentloaded")
        page.wait_for_selector(".vip-section .vip-visual", state="visible", timeout=10000)
        save_detail_images(page, product_id, img_save_dir, detail_url, logger)
    except Exception as e:
        logger.warning(f"이미지 저장 스킵 ({product_id}): {e}")

def run_full_crawler():
    logger = setup_logger()
    now = datetime.now()
    pnttm, create_dt_full = now.strftime("%Y%m%d"), now.strftime("%Y%m%d%H%M")

    # result/reborncar (프로젝트 루트 기준)
    result_dir = Path(__file__).resolve().parent.parent / "result" / "reborncar"
    result_dir.mkdir(parents=True, exist_ok=True)
    list_path = result_dir / "reborncar_list.csv"
    if list_path.exists():
        list_path.unlink()
    # 이미지 저장: imgs/reborncar/2026년/20260226 형태 (오늘 날짜)
    img_save_dir = Path(__file__).resolve().parent.parent / "imgs" / "reborncar" / f"{now.year}년" / now.strftime("%Y%m%d")
    img_save_dir.mkdir(parents=True, exist_ok=True)

    list_headers = [
        "model_sn", "product_id", "car_type_name", "brand_list", "car_list", "lp_car_name", "lp_car_trim", "release_dt", "car_navi", "car_seat",
        "car_main_pay", "amtsel", "status", "copytext", "endtimedeal", "date_crtr_pnttm", "create_dt"
    ]

    # [테스트] N페이지까지만 수집 (전체 수집 시 None 유지)
    TEST_PAGE_LIMIT = 1   # ← 테스트 시 사용
    # TEST_PAGE_LIMIT = None  # ← 전체 수집 시 사용

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(user_agent="Mozilla/5.0...", viewport={'width': 1900, 'height': 1000})
        page = context.new_page()

        try:
            # [0단계] 브랜드 CSV 수집 (crawl_reborncar_brand.py와 동일)
            logger.info("=" * 50)
            logger.info("[0단계] 브랜드 계층 수집 → reborncar_brand_list.csv")
            logger.info("=" * 50)
            run_reborncar_brand(page, result_dir, logger)

            # [1단계] 차종 CSV 수집 (crawl_reborncar_car_type.py와 동일)
            logger.info("=" * 50)
            logger.info("[1단계] 차종 수집 → reborncar_car_type_list.csv")
            logger.info("=" * 50)
            run_reborncar_car_type(page, result_dir, logger)

            brand_model_map, model_to_car_list = load_brand_model_map(result_dir)
            detail_page = context.new_page()

            # [2단계] 목록 + 이미지 수집 (list.csv, 이미지만 저장 / detail CSV 없음)
            logger.info("=" * 50)
            logger.info("[2단계] 목록·이미지 수집 → reborncar_list.csv, imgs/reborncar/...")
            logger.info("=" * 50)
            logger.info("리본카 목록 페이지 접속...")
            car_counter = 1
            page.goto("https://www.reborncar.co.kr/smartbuy/SB1001.rb")
            page.wait_for_selector("ul.lp-box.smartbuy-lp", timeout=60000)

            # 차종 필터: .check-btn-box.car-type-filter 내 checkbox 버튼들
            car_type_filter_box = page.locator("#wrap .lp-section .lp-filter .lp-filter-form .lp-filter-box .lp-filter-con .check-btn-box.car-type-filter")
            car_type_buttons = car_type_filter_box.locator(".check-btn.check-btn-s.filter-chk") if car_type_filter_box.count() > 0 else page.locator(".check-btn-box.car-type-filter .check-btn.check-btn-s.filter-chk")
            n_car_types = car_type_buttons.count()
            if n_car_types == 0:
                n_car_types = 1  # 필터 없으면 전체 1번만 수집
                car_type_labels = [""]
            else:
                car_type_labels = []
                for i in range(n_car_types):
                    try:
                        lbl = car_type_buttons.nth(i).inner_text().strip()
                        car_type_labels.append(lbl or f"타입{i+1}")
                    except Exception:
                        car_type_labels.append(f"타입{i+1}")

            for car_type_idx in range(n_car_types):
                current_car_type = car_type_labels[car_type_idx]
                if n_car_types > 1:
                    try:
                        # 차종 버튼 클릭 → lp-filter-list 안에 lp-filter-choice(span[data-cls="cate-cb"]) 칩 생성
                        car_type_buttons.nth(car_type_idx).click()
                        page.wait_for_timeout(2500)
                        # 해당 차종 칩이 생겼는지 확인 (data-cls="cate-cb" 텍스트가 현재 차종명)
                        page.wait_for_selector('.lp-filter-list .lp-filter-choice span[data-cls="cate-cb"]', timeout=8000)
                        page.wait_for_timeout(800)
                        logger.info(f"차종 필터 선택 (칩 생성): {current_car_type}")
                    except Exception as e:
                        logger.warning(f"차종 필터 클릭 실패 ({current_car_type}): {e}")
                        continue

                while True:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(3000)

                    active_el = page.locator("li.pagination-con.page-num.active")
                    try: current_page = int(active_el.inner_text() or "1")
                    except: current_page = 1

                    items = page.locator("ul.lp-box.smartbuy-lp > li.lp-con.swiper-slide:not(.lp-banner):not(.swiper-slide-duplicate)").all()
                    logger.info(f"[{current_car_type}] 현재 {current_page}페이지 수집 중... (매물 {len(items)}개)")

                    for item in items:
                        try:
                            # 목록 데이터 추출
                            v_product_id = ""
                            href_value = item.locator("a.lp-thumnail").get_attribute("href")
                            if href_value:
                                match = re.search(r"fnDetailMove\('([^']+)'", href_value)
                                if match: v_product_id = match.group(1)

                            v_status = item.locator(".lp-status").inner_text().strip() or "판매중"

                            # 목록에서 가격 (상태별)
                            v_finamt, v_amtsel = "-", "-"
                            if v_status in ["판매중", "계약중", "상담중"]:
                                pay_b = item.locator(".car-pay .pay b")
                                if pay_b.count() > 0:
                                    v_finamt = pay_b.inner_text().strip() + "만원"
                                discount_el = item.locator(".car-pay .discount")
                                v_amtsel = discount_el.inner_text().strip() if discount_el.count() > 0 else "0"
                            elif v_status == "준비중":
                                v_finamt, v_amtsel = "0만원", "-"
                            elif v_status == "판매완료":
                                v_finamt, v_amtsel = "판매완료", "-"

                            # 연식/내비/좌석
                            summary_lis = item.locator(".lp-summery li").all()
                            v_year = summary_lis[0].inner_text().strip() if len(summary_lis) > 0 else ""
                            v_navi = summary_lis[1].inner_text().strip() if len(summary_lis) > 1 else ""
                            v_seat = summary_lis[2].inner_text().strip() if len(summary_lis) > 2 else ""

                            # 타임딜
                            is_td = item.locator(".lp-timedeal").count() > 0
                            v_copy = "타임딜" if is_td else ""
                            v_endtd = item.locator(".lp-timedeal-count").inner_text().strip() if is_td else ""

                            # list.csv 행 (목록 데이터만, car_type=현재 차종 필터, brand_list=brand 파일 매칭)
                            v_lp_car_name = item.locator(".lp-car-name").inner_text().strip()
                            list_row = {
                                "model_sn": car_counter, "product_id": v_product_id, "car_type_name": current_car_type,
                                "lp_car_name": v_lp_car_name,
                                "brand_list": get_brand_for_lp_car_name(v_lp_car_name, brand_model_map),
                                "car_list": get_car_list_for_lp_car_name(v_lp_car_name, model_to_car_list),
                                "lp_car_trim": item.locator(".lp-car-trim").inner_text().strip(),
                                "release_dt": v_year, "car_navi": v_navi, "car_seat": v_seat,
                                "car_main_pay": v_finamt, "amtsel": v_amtsel, "status": v_status,
                                "copytext": v_copy, "endtimedeal": v_endtd,
                                "date_crtr_pnttm": pnttm, "create_dt": create_dt_full
                            }
                            with open(list_path, "a", newline="", encoding="utf-8-sig") as fl:
                                wl = csv.DictWriter(fl, fieldnames=list_headers)
                                if car_counter == 1:
                                    wl.writeheader()
                                wl.writerow(list_row)

                            # 상세 페이지 이미지만 저장 (detail CSV 없음)
                            if v_product_id and v_status not in ["준비중", "판매완료"]:
                                fetch_detail_images_only(detail_page, v_product_id, img_save_dir, logger)

                            car_counter += 1
                        except Exception as e:
                            logger.error(f"항목 수집 실패: {e}")

                    logger.info(f"목록 {current_page}페이지 수집 완료 → list.csv 저장 (이번 페이지 {len(items)}건)")

                    # 페이지네이션: 다음 번호 있으면 클릭, 없으면 다음 블록(>) → 둘 다 없으면 수집 종료
                    # (테스트용: TEST_PAGE_LIMIT 설정 시 N페이지 도달하면 여기서 break)
                    if TEST_PAGE_LIMIT is not None and current_page >= TEST_PAGE_LIMIT:
                        break
                    prev_page = current_page
                    next_page_link = page.locator("li.pagination-con.page-num.active + li.pagination-con.page-num:not(.next):not(.prev) a").first
                    if next_page_link.count() > 0:
                        next_page_link.evaluate("el => el.click()")
                        page.wait_for_timeout(3000)
                    else:
                        next_grp = page.locator("li.pagination-con.next:not(.disabled) a").first
                        if next_grp.count() > 0:
                            next_grp.evaluate("el => el.click()")
                            page.wait_for_timeout(4000)
                            page.wait_for_selector("li.pagination-con.page-num.active", timeout=8000)
                        else:
                            break
                    page.wait_for_timeout(1500)
                    # 다음 페이지로 넘어갔는지 확인; 그대로면 마지막 페이지라서 종료 (중복 수집 방지)
                    try:
                        new_active = page.locator("li.pagination-con.page-num.active")
                        new_page = int(new_active.inner_text() or "0")
                        if new_page == prev_page:
                            page.wait_for_timeout(1500)
                            break
                    except Exception:
                        break

                # 현재 차종 수집이 끝났으면, lp-filter-choice-delete로 해당 칩 제거 후 다음 차종 선택 준비
                if n_car_types > 1:
                    try:
                        choice_delete = page.locator(
                            '.lp-filter-list .lp-filter-choice:has(span[data-cls="cate-cb"])'
                        ).filter(has_text=current_car_type).locator(".lp-filter-choice-delete").first
                        if choice_delete.count() > 0:
                            choice_delete.click()
                            page.wait_for_timeout(2000)
                            logger.info(f"차종 필터 칩 제거: {current_car_type}")
                    except Exception as e:
                        logger.warning(f"차종 칩 제거 실패 ({current_car_type}): {e}")

        finally:
            browser.close()

if __name__ == "__main__":
    run_full_crawler()