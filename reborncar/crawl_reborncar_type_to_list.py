import csv
import logging
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

try:
    import config
except ImportError:
    config = None

def setup_logger():
    log_dir = Path("./logs/reborncar")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "reborncar_type_to_list.log"
    logger = logging.getLogger("RebornCar")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh = logging.FileHandler(log_path, encoding='utf-8'); logger.addHandler(fh)
        sh = logging.StreamHandler(); logger.addHandler(sh)
    return logger

def _normalize_composite_key(*parts):
    """공백 정리 후 한 문자열로 합침 (brand의 model_list+model_list_1+model_list_2, list의 lp_car_name+lp_car_trim 비교용)."""
    return " ".join((p or "").strip() for p in parts).strip()


def load_brand_model_map(result_dir):
    """reborncar_brand_list.csv 또는 reborncar_brand.csv에서
    1) model_list(| 앞부분) -> brand_list, car_list 매핑
    2) (model_list + model_list_1 + model_list_2) full 키 -> (brand_list, car_list, model_list, model_list_1, model_list_2) 5-tuple
    3) (model_list + model_list_1) 짧은 키 -> 동일 5-tuple
    4) model_list 단독 -> 5-tuple (car_name에 model_list 포함 시 보완 매칭, 예: 더 뉴봉고Ⅲ화물)
    을 로드."""
    model_to_brand = {}
    model_to_car_list = {}
    composite_to_model = {}  # full key -> (brand_list, car_list, model_list, model_list_1, model_list_2)
    composite_short_to_model = {}  # short key -> 5-tuple
    model_list_to_row = {}  # model_list -> 5-tuple
    brand_path = result_dir / "reborncar_brand_list.csv"
    if not brand_path.exists():
        brand_path = result_dir / "reborncar_brand.csv"
    if not brand_path.exists():
        return model_to_brand, model_to_car_list, composite_to_model, composite_short_to_model, model_list_to_row
    try:
        with open(brand_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                model_list_raw = (row.get("model_list") or "").strip()
                brand_list = (row.get("brand_list") or "").strip()
                car_list = (row.get("car_list") or "").strip()
                model_list_val = model_list_raw.split("|")[0].strip() if model_list_raw else ""
                model_list_1 = (row.get("model_list_1") or "").strip()
                model_list_2 = (row.get("model_list_2") or "").strip()
                if not brand_list:
                    continue
                if model_list_val and model_list_val not in model_to_brand:
                    model_to_brand[model_list_val] = brand_list
                    model_to_car_list[model_list_val] = car_list if car_list else "-"
                row_5 = (brand_list or "-", car_list or "-", model_list_val or "-", model_list_1 or "-", model_list_2 or "-")
                comp_key = _normalize_composite_key(model_list_val, model_list_1, model_list_2)
                if comp_key and comp_key not in composite_to_model:
                    composite_to_model[comp_key] = row_5
                short_key = _normalize_composite_key(model_list_val, model_list_1)
                if short_key and short_key not in composite_short_to_model:
                    composite_short_to_model[short_key] = row_5
                if model_list_val and model_list_val not in model_list_to_row:
                    model_list_to_row[model_list_val] = row_5
    except Exception:
        pass
    return model_to_brand, model_to_car_list, composite_to_model, composite_short_to_model, model_list_to_row

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


def get_brand_car_model_for_list_row(lp_car_name, lp_car_trim, composite_to_model, composite_short_to_model=None, model_list_to_row=None):
    """list의 (lp_car_name + lp_car_trim) = car_name으로 brand 행 매칭 후 (brand_list, car_list, model_list, model_list_1, model_list_2) 5-tuple 반환.
    1) full 키 / 짧은 키 composite 매칭 (브랜드 첫 단어 제거한 car_name도 시도)
    2) 실패 시 car_name에 model_list가 포함된 행으로 보완 (예: '더 뉴봉고Ⅲ화물 1.2톤 LPG ...' -> model_list '더 뉴봉고Ⅲ화물')
    """
    if composite_short_to_model is None:
        composite_short_to_model = {}
    if model_list_to_row is None:
        model_list_to_row = {}
    name = (lp_car_name or "").strip()
    trim = (lp_car_trim or "").strip()
    car_name_full = _normalize_composite_key(name, trim)
    parts = name.split(None, 1)
    car_name_no_first = _normalize_composite_key(parts[1] if len(parts) >= 2 else "", trim)

    for key in (car_name_full, car_name_no_first):
        if not key:
            continue
        if composite_to_model and key in composite_to_model:
            return composite_to_model[key]
        if composite_short_to_model and key in composite_short_to_model:
            return composite_short_to_model[key]

    # 보완: car_name이 brand의 model_list로 시작하는 행 사용 (가장 긴 model_list 우선, 예: 더 뉴봉고Ⅲ화물)
    for model_list_key in sorted(model_list_to_row.keys(), key=len, reverse=True):
        if not model_list_key:
            continue
        if car_name_full.startswith(model_list_key) or car_name_no_first.startswith(model_list_key):
            return model_list_to_row[model_list_key]

    return "-", "-", "-", "-", "-"

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


def split_model_list_and_period(combined):
    """'앞부분|(괄호내용)' 형태에서 (model_list, production_period) 반환 (crawl_reborncar_brand.py와 동일)."""
    if not combined or "|" not in combined:
        return combined.strip(), ""
    parts = combined.split("|", 1)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")


def normalize_production_period(text):
    """'(21~24년)' → '21~24', '(23년~현재)' → '23~현재' 형태로 변환."""
    if not text:
        return ""
    s = text.strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    s = s.replace("년", "")
    return s


def run_reborncar_brand(page, result_dir, logger):
    """브랜드·차종·모델·트림·옵션 계층 수집 → reborncar_brand_list.csv (crawl_reborncar_brand.py와 동일 방식)."""
    now = datetime.now()
    pnttm = now.strftime("%Y%m%d")
    create_dt = now.strftime("%Y%m%d%H%M")
    csv_path = result_dir / "reborncar_brand_list.csv"
    headers = ["model_sn", "brand_list", "car_list", "model_list", "model_list_1", "model_list_2", "production_period", "date_crtr_pnttm", "create_dt"]
    model_sn = 1
    row_count = 0
    try:
        logger.info("리본카 브랜드 계층 수집 시작...")
        page.goto("https://www.reborncar.co.kr/smartbuy/SB1001.rb", wait_until="networkidle", timeout=60000)
        page.wait_for_selector(".filter-brand .brand-list", timeout=30000)
        page.wait_for_timeout(1500)
        brand_selectors = page.locator(".filter-brand .brand-list")
        brand_count = brand_selectors.count()

        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()

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

                    # 모델만 선택 (트림/옵션 check-box 제외: class에 model- 포함된 것만)
                    detail_boxes = car_box.locator(".model-list .check-box[class*='model-']")
                    detail_count = detail_boxes.count()

                    if detail_count > 0:
                        for k in range(detail_count):
                            model_box = detail_boxes.nth(k)
                            full_boname = model_box.locator("> label span").inner_text().strip()
                            model_list_val, production_period_val = split_model_list_and_period(
                                split_boname_by_last_paren(full_boname)
                            )
                            production_period_val = normalize_production_period(production_period_val)
                            model_box.locator("label").first.click()
                            page.wait_for_timeout(200)

                            trim_boxes = model_box.locator(".trim-list.depth04 .check-box[class*='trim-']")
                            trim_count = trim_boxes.count()

                            # 트림이 전혀 없는 모델(예: 더 뉴레이, 레이(11~17년))도 1행으로 수집
                            if trim_count == 0:
                                row = {
                                    "model_sn": model_sn,
                                    "brand_list": brand_list,
                                    "car_list": car_list,
                                    "model_list": model_list_val,
                                    "model_list_1": "",
                                    "model_list_2": "",
                                    "production_period": production_period_val,
                                    "date_crtr_pnttm": pnttm,
                                    "create_dt": create_dt
                                }
                                writer.writerow(row)
                                row_count += 1
                                model_sn += 1
                                continue

                            for t in range(trim_count):
                                trim_el = trim_boxes.nth(t)
                                try:
                                    trim_name = trim_el.locator("label span").inner_text().strip()
                                except Exception:
                                    trim_name = ""
                                trim_el.locator("label").click()
                                page.wait_for_timeout(250)
                                # 현재 트림 요소 안에서만 옵션 조회 (트렌디/프레스티지/노블레스 등 해당 트림 옵션만 수집)
                                option_boxes = trim_el.locator(".option-list.depth05 .check-box[class*='option-']")
                                opt_count = option_boxes.count()
                                if opt_count > 0:
                                    for o in range(opt_count):
                                        try:
                                            option_name = option_boxes.nth(o).locator("label span").inner_text().strip()
                                        except Exception:
                                            option_name = ""
                                        row = {
                                            "model_sn": model_sn,
                                            "brand_list": brand_list,
                                            "car_list": car_list,
                                            "model_list": model_list_val,
                                            "model_list_1": trim_name,
                                            "model_list_2": option_name,
                                            "production_period": production_period_val,
                                            "date_crtr_pnttm": pnttm,
                                            "create_dt": create_dt
                                        }
                                        writer.writerow(row)
                                        row_count += 1
                                        model_sn += 1
                                else:
                                    row = {
                                        "model_sn": model_sn,
                                        "brand_list": brand_list,
                                        "car_list": car_list,
                                        "model_list": model_list_val,
                                        "model_list_1": trim_name,
                                        "model_list_2": "",
                                        "production_period": production_period_val,
                                        "date_crtr_pnttm": pnttm,
                                        "create_dt": create_dt
                                    }
                                    writer.writerow(row)
                                    row_count += 1
                                    model_sn += 1
                    else:
                        car_model_list, car_production_period = split_model_list_and_period(
                            split_boname_by_last_paren(car_list)
                        )
                        car_production_period = normalize_production_period(car_production_period)
                        row = {
                            "model_sn": model_sn,
                            "brand_list": brand_list,
                            "car_list": car_list,
                            "model_list": car_model_list,
                            "model_list_1": "",
                            "model_list_2": "",
                            "production_period": car_production_period,
                            "date_crtr_pnttm": pnttm,
                            "create_dt": create_dt
                        }
                        writer.writerow(row)
                        row_count += 1
                        model_sn += 1

        if row_count > 0:
            logger.info(f"브랜드 CSV 저장 완료: {csv_path} ({row_count}행)")
        else:
            logger.warning("브랜드 수집 데이터 없음.")
    except Exception as e:
        logger.error(f"브랜드 수집 오류: {e}")

def run_reborncar_car_type(page, result_dir, logger):
    """차종(car_type) 수집 → reborncar_car_type_list.csv (cate_cb 제거, 날짜 컬럼 추가)."""
    result_path = result_dir / "reborncar_car_type_list.csv"
    if result_path.exists():
        result_path.unlink()
    # 시간 정보 생성
    now = datetime.now()
    pnttm = now.strftime("%Y%m%d")
    create_dt = now.strftime("%Y%m%d%H%M")
    # cate_cb 제거, 날짜 컬럼 추가
    headers = ["car_type_sn", "car_type_name", "date_crtr_pnttm", "create_dt"]
    car_type_sn = 1
    try:
        logger.info("리본카 차종(car_type) 수집 시작...")
        page.goto("https://www.reborncar.co.kr/smartbuy/SB1001.rb", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("input.cate-cb[id^='car_type']", state="attached", timeout=30000)
        page.wait_for_timeout(1000)
        car_type_elements = page.locator("input.cate-cb[id^='car_type']").all()
        for el in car_type_elements:
            el_id = el.get_attribute("id")
            label_span = page.locator(f"label[for='{el_id}'] span")
            if label_span.count() > 0:
                car_type_name = label_span.inner_text().strip()
                row = {
                    "car_type_sn": car_type_sn,
                    "car_type_name": car_type_name,
                    "date_crtr_pnttm": pnttm,
                    "create_dt": create_dt,
                }
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

def save_list_thumbnail(item_locator, page, product_id, save_dir, list_page_url, logger):
    """목록 아이템의 .lp-thumnail > img 를 product_id_list.png 로 저장. 저장 경로(imgs부터) 반환."""
    if not product_id or not save_dir:
        return ""
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    project_root = config.PROJECT_ROOT if (config and hasattr(config, "PROJECT_ROOT")) else Path(__file__).resolve().parent.parent
    base_url = list_page_url.rsplit("?", 1)[0] if "?" in list_page_url else list_page_url
    img_el = item_locator.locator(".lp-thumnail img").first
    if img_el.count() == 0:
        return ""
    src = img_el.get_attribute("src")
    if not src:
        return ""
    try:
        full_url = urljoin(base_url, src) if not (src.startswith("http") or src.startswith("//")) else ("https:" + src if src.startswith("//") else src)
        resp = page.request.get(full_url)
        if resp.ok:
            path = save_dir / f"{product_id}_list.png"
            path.write_bytes(resp.body())
            try:
                rel = path.relative_to(project_root)
                return str(rel).replace("\\", "/")
            except ValueError:
                return f"imgs/reborncar/list/{save_dir.parent.name}/{save_dir.name}/{product_id}_list.png"
    except Exception as e:
        logger.warning(f"리스트 썸네일 저장 실패 ({product_id}_list): {e}")
    return ""


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
    # 이미지 저장 경로: config.py 의 IMG_LIST_REL / IMG_DETAIL_REL["reborncar"] 사용 (헤이딜러와 동일 방식)
    if config and hasattr(config, "get_list_image_save_dir"):
        list_img_save_dir = Path(config.get_list_image_save_dir("reborncar", now))
    else:
        list_img_save_dir = Path(__file__).resolve().parent.parent / "imgs" / "reborncar" / "list" / f"{now.year}년" / now.strftime("%Y%m%d")
    if config and hasattr(config, "get_detail_image_save_dir"):
        img_save_dir = Path(config.get_detail_image_save_dir("reborncar", now))
    else:
        img_save_dir = Path(__file__).resolve().parent.parent / "imgs" / "reborncar" / f"{now.year}년" / now.strftime("%Y%m%d")
    list_img_save_dir.mkdir(parents=True, exist_ok=True)
    img_save_dir.mkdir(parents=True, exist_ok=True)

    list_headers = [
        "model_sn", "product_id", "car_type_name", "brand_list", "car_list", "model_list", "model_list_1", "model_list_2", "car_name",
        "release_dt", "car_navi", "car_seat",
        "car_main_pay", "amtsel", "status", "copytext", "endtimedeal", "detail_url", "car_imgs", "date_crtr_pnttm", "create_dt"
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
            # logger.info("=" * 50)
            # logger.info("[0단계] 브랜드 계층 수집 → reborncar_brand_list.csv")
            # logger.info("=" * 50)
            # run_reborncar_brand(page, result_dir, logger)

            # [1단계] 차종 CSV 수집 (crawl_reborncar_car_type.py와 동일)
            # logger.info("=" * 50)
            # logger.info("[1단계] 차종 수집 → reborncar_car_type_list.csv")
            # logger.info("=" * 50)
            # run_reborncar_car_type(page, result_dir, logger)

            brand_model_map, model_to_car_list, composite_to_model, composite_short_to_model, model_list_to_row = load_brand_model_map(result_dir)
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

                            # list.csv 행 (목록 데이터만, brand/list 매칭으로 model_list, model_list_1, model_list_2 채움)
                            v_lp_car_name = item.locator(".lp-car-name").inner_text().strip()
                            v_lp_car_trim = item.locator(".lp-car-trim").inner_text().strip()
                            v_brand, v_car, v_model_list, v_model_list_1, v_model_list_2 = get_brand_car_model_for_list_row(
                                v_lp_car_name, v_lp_car_trim, composite_to_model, composite_short_to_model, model_list_to_row
                            )
                            if v_brand == "-" and v_car == "-":
                                v_brand = get_brand_for_lp_car_name(v_lp_car_name, brand_model_map)
                                v_car = get_car_list_for_lp_car_name(v_lp_car_name, model_to_car_list)
                            # 상세 URL: productId 쿼리
                            detail_url_val = f"https://www.reborncar.co.kr/smartbuy/SB1002.rb?productId={v_product_id}" if v_product_id else ""
                            # 리스트 썸네일: .lp-thumnail > img → product_id_list.png, car_imgs는 imgs부터 경로
                            list_page_url = page.url
                            car_imgs_val = save_list_thumbnail(
                                item, page, v_product_id, list_img_save_dir, list_page_url, logger
                            ) if v_product_id else ""

                            car_name_val = _normalize_composite_key(v_lp_car_name, v_lp_car_trim)
                            list_row = {
                                "model_sn": car_counter, "product_id": v_product_id, "car_type_name": current_car_type,
                                "brand_list": v_brand, "car_list": v_car,
                                "model_list": v_model_list, "model_list_1": v_model_list_1, "model_list_2": v_model_list_2,
                                "car_name": car_name_val,
                                "release_dt": v_year, "car_navi": v_navi, "car_seat": v_seat,
                                "car_main_pay": v_finamt, "amtsel": v_amtsel, "status": v_status,
                                "copytext": v_copy, "endtimedeal": v_endtd,
                                "detail_url": detail_url_val, "car_imgs": car_imgs_val, "date_crtr_pnttm": pnttm, "create_dt": create_dt_full
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