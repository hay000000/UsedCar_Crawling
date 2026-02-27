#!/usr/bin/env python3
import csv
import logging
import re
import time
import requests
import sys
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

# --- 설정 및 경로 ---
# ----- 목록 수집 모드 (테스트 vs 전체 무한스크롤) -----
# [테스트] 몇 개만 수집: TARGET_COUNT = 숫자 (해당 개수 모이면 수집 종료)
# [전체]  무한스크롤 끝까지: TARGET_COUNT = None (새 매물 없을 때까지 스크롤)
# 사용법: 둘 중 하나만 유지하고 나머지는 주석 처리
TARGET_COUNT = 5
# TARGET_COUNT = None

BASE_URL = "https://www.heydealer.com"
BASE_DIR = Path(__file__).resolve().parent

# 폴더 경로 설정 (프로젝트 루트 기준)
# result: csv 저장
RESULT_DIR = BASE_DIR.parent / "result" / "heydealer"
# logs: 로그 저장
LOG_DIR = BASE_DIR.parent / "logs" / "heydealer"
# imgs: 이미지 베이스 (실제 저장은 imgs/heydealer/2026년/20250226/ 형태)
IMG_BASE = BASE_DIR.parent / "imgs" / "heydealer"

# 폴더 생성
RESULT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
IMG_BASE.mkdir(parents=True, exist_ok=True)

# 파일 경로
LIST_FILE = RESULT_DIR / "heydealer_list.csv"
CAR_TYPE_LIST_FILE = RESULT_DIR / "heydealer_car_type_list.csv"
BRAND_LIST_FILE = RESULT_DIR / "heydealer_brand_list.csv"

# --- 로그 설정 ---
LOG_FILE = LOG_DIR / f"heydealer_type_to_list.log"
# 브랜드 수집용: crawl_heydealer_brand.py와 동일한 로그 파일·포맷
BRAND_HIERARCHY_LOG = LOG_DIR / "heydealer_brand_hierarchy.log"
_logger_brand = logging.getLogger("heydealer_brand")
_logger_brand.setLevel(logging.INFO)
_logger_brand.handlers.clear()
_fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
_h_file = logging.FileHandler(BRAND_HIERARCHY_LOG, encoding="utf-8")
_h_file.setFormatter(_fmt)
_h_stream = logging.StreamHandler()
_h_stream.setFormatter(_fmt)
_logger_brand.addHandler(_h_file)
_logger_brand.addHandler(_h_stream)

class Logger(object):
    def __init__(self):
        self.terminal = sys.stdout
        self.log = open(LOG_FILE, "a", encoding="utf-8")
    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
    def flush(self):
        self.terminal.flush()
        self.log.flush()

sys.stdout = Logger()

_today_img_dir = IMG_BASE / f"{datetime.now().strftime('%Y')}년" / datetime.now().strftime("%Y%m%d")
print(f"[{datetime.now()}] 🏁 헤이딜러 수집 프로그램 시작")
print(f"📁 이미지 저장 경로: {_today_img_dir}")

BRAND_CSV_FIELDS = [
    "brand_id", "brand_name", "model_group_id", "model_group_name",
    "model_id", "model_name", "production_period", "data_crtr_pnttm", "create_dt"
]

def fetch_and_save_brand_csv():
    """crawl_heydealer_brand.py와 동일: API로 브랜드·모델 계층 수집 후 brand CSV 저장. 로그는 heydealer_brand_hierarchy.log 사용."""
    log = _logger_brand
    if BRAND_LIST_FILE.exists():
        BRAND_LIST_FILE.unlink()
    API_BASE = "https://api.heydealer.com/v2/customers/web/market/car_meta"
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json",
    })
    d_pnttm = datetime.now().strftime("%Y%m%d")
    c_dt = datetime.now().strftime("%Y%m%d%H%M")
    n_written = 0
    try:
        log.info("=" * 60)
        log.info("헤이딜러 브랜드-모델 계층 데이터 수집 시작 (날짜 정보 포함)")
        log.info("=" * 60)
        brands_resp = session.get(f"{API_BASE}/brands/", timeout=15)
        brands_resp.raise_for_status()
        raw = brands_resp.json()
        brands = raw if isinstance(raw, list) else (raw.get("brands") or raw.get("data") or []) if isinstance(raw, dict) else []
        n_brands = len(brands)
        log.info(f"총 {n_brands}개 브랜드 데이터 수집 시작")
        for b_idx, brand in enumerate(brands, 1):
            brand_id = brand.get("hash_id")
            brand_name = brand.get("name")
            log.info(f"[{b_idx}/{n_brands}] 브랜드 처리 중: {brand_name}")
            mg_resp = session.get(f"{API_BASE}/brands/{brand_id}/", timeout=15)
            if mg_resp.status_code != 200:
                continue
            for mg in mg_resp.json().get("model_groups", []):
                mg_id = mg.get("hash_id")
                mg_name = mg.get("name")
                sub_resp = session.get(f"{API_BASE}/model_groups/{mg_id}/", timeout=15)
                if sub_resp.status_code != 200:
                    continue
                for model in sub_resp.json().get("models", []):
                    row = {
                        "brand_id": brand_id,
                        "brand_name": brand_name,
                        "model_group_id": mg_id,
                        "model_group_name": mg_name,
                        "model_id": model.get("hash_id", ""),
                        "model_name": model.get("name", ""),
                        "production_period": model.get("period", ""),
                        "data_crtr_pnttm": d_pnttm,
                        "create_dt": c_dt,
                    }
                    save_to_csv_append(BRAND_LIST_FILE, BRAND_CSV_FIELDS, row)
                    n_written += 1
                time.sleep(0.1)
        if n_written:
            log.info("=" * 60)
            log.info(f"✅ 수집 완료! 파일: {BRAND_LIST_FILE}")
            log.info(f"총 수집 모델 수: {n_written:,}개")
            log.info("=" * 60)
        else:
            log.warning("⚠️ 수집된 데이터가 없습니다.")
    except Exception as e:
        log.error(f"❌ 크롤링 중 치명적 오류: {e}")
        import traceback
        traceback.print_exc()

def load_brand_mapping():
    """model_name(정확) -> {brand_id, brand_name}, brand_name(브랜드명) -> {brand_id, brand_name} 둘 다 반환."""
    brand_map = {}
    brand_by_name = {}
    if BRAND_LIST_FILE.exists():
        with open(BRAND_LIST_FILE, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                info = {"brand_id": row.get("brand_id", ""), "brand_name": row.get("brand_name", "").strip()}
                model_name = (row.get("model_name") or "").strip()
                if model_name:
                    brand_map[model_name] = info
                bn = info["brand_name"]
                if bn and bn not in brand_by_name:
                    brand_by_name[bn] = info
    else:
        print(f"⚠️ 매핑 파일이 없습니다: {BRAND_LIST_FILE}")
    return brand_map, brand_by_name

def get_now_times():
    now = datetime.now()
    return now.strftime("%Y%m%d"), now.strftime("%Y%m%d%H%M")

def save_to_csv_append(file_path, fieldnames, data_dict):
    file_exists = Path(file_path).exists()
    with open(file_path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        if not file_exists:
            writer.writeheader()
        writer.writerow(data_dict)

def download_image(img_url, model_cd, idx):
    """이미지 다운로드. 저장 경로: imgs/heydealer/연도/YYYYMMDD/model_cd_idx.ext"""
    try:
        if not img_url or "svg" in img_url.lower():
            return False
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": BASE_URL,
        }
        response = requests.get(img_url, stream=True, timeout=15, headers=headers)
        if response.status_code != 200:
            return False
        ext = img_url.split(".")[-1].split("?")[0].lower()
        if len(ext) > 4 or len(ext) < 2:
            ext = "jpg"
        now = datetime.now()
        save_dir = IMG_BASE / f"{now.strftime('%Y')}년" / now.strftime("%Y%m%d")
        save_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{model_cd}_{idx}.{ext}"
        save_path = save_dir / filename
        with open(save_path, "wb") as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
        return True
    except Exception:
        return False

def _collect_images_from_detail_page(page, model_cd):
    """상세 페이지에서 이미지만 수집·저장 (list_detail_brand와 동일 로직, detail CSV 없음)."""
    downloaded_urls = set()
    img_idx = 1
    try:
        try:
            page.wait_for_selector(".css-12qft46", timeout=20000)
        except Exception:
            try:
                page.wait_for_selector(".css-113wzqa", timeout=10000)
            except Exception:
                pass
        page.wait_for_timeout(2000)
        for i in range(1, 14):
            page.evaluate(f"window.scrollTo(0, {i * 500})")
            time.sleep(0.15)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(800)
        detail_container = page.query_selector(".css-1uus6sd .css-12qft46")
        if not detail_container:
            detail_container = page.query_selector(".css-12qft46")
        if detail_container:
            ltrevz_sections = detail_container.query_selector_all(".css-ltrevz")
            if len(ltrevz_sections) >= 2:
                sec2 = ltrevz_sections[1]
                for sel in [".css-5pr39e .css-1i3qy3r .css-1dpi6xl button.css-q47uzu img.css-q38rgl", "button.css-q47uzu img.css-q38rgl", "button img, .css-q47uzu img"]:
                    imgs = sec2.query_selector_all(sel)
                    if imgs:
                        for img in imgs:
                            src = img.get_attribute("src") or img.get_attribute("data-src")
                            if src and src not in downloaded_urls and "svg" not in src.lower():
                                if download_image(src, model_cd, img_idx):
                                    downloaded_urls.add(src)
                                    img_idx += 1
                        break
            if len(ltrevz_sections) >= 4:
                sec4 = ltrevz_sections[3]
                for sel in [".css-5pr39e .css-1i3qy3r .css-hf19cn .css-1a3591h img.css-158t7i4", ".css-5pr39e .css-1i3qy3r .css-w9nhgi img.css-158t7i4", ".css-hf19cn .css-1a3591h img", ".css-hf19cn .css-w9nhgi img", ".css-w9nhgi img.css-158t7i4"]:
                    for img in sec4.query_selector_all(sel):
                        src = img.get_attribute("src") or img.get_attribute("data-src")
                        if src and src not in downloaded_urls and "svg" not in src.lower():
                            if download_image(src, model_cd, img_idx):
                                downloaded_urls.add(src)
                                img_idx += 1
        if img_idx == 1:
            fallback_imgs = page.query_selector_all("img[src*='heydealer.com'], img[src*='cdn.'], .css-w9nhgi img, .css-1a3591h img, main img")
            for img in fallback_imgs:
                src = img.get_attribute("src") or img.get_attribute("data-src")
                if not src or "svg" in src.lower() or src in downloaded_urls:
                    continue
                if download_image(src, model_cd, img_idx):
                    downloaded_urls.add(src)
                    img_idx += 1
        if img_idx == 1:
            page.wait_for_timeout(2000)
            for i in range(1, 12):
                page.evaluate(f"window.scrollTo(0, {i * 600})")
                time.sleep(0.2)
            for img in page.query_selector_all("img[src], img[data-src]"):
                src = img.get_attribute("src") or img.get_attribute("data-src")
                if not src or "svg" in src.lower() or src in downloaded_urls:
                    continue
                if "heydealer" in src or "cdn." in src or len(src) > 20:
                    if download_image(src, model_cd, img_idx):
                        downloaded_urls.add(src)
                        img_idx += 1
    except Exception as e:
        print(f"      ❌ 이미지 수집 오류 ({model_cd}): {str(e)[:60]}")
    return img_idx - 1

def _extract_card_heydealer(elem, idx, brand_map, car_type="", brand_by_name=None) -> dict:
    data = {"model_sn": idx, "brand_id": "", "brand_name": "", "car_type": car_type}
    try:
        href = elem.get_attribute("href") or ""
        full_url = (BASE_URL + href).split("?")[0] if not href.startswith("http") else href.split("?")[0]
        data["model_cd"] = full_url.split("/")[-1]
        data["detail_url"] = full_url
        m_box = elem.query_selector(".css-9j6363")
        if m_box:
            names = m_box.query_selector_all(".css-jk6asd")
            raw_model_name = names[0].inner_text().strip() if len(names) > 0 else ""
            data["model_name"] = raw_model_name
            data["model_second_name"] = names[1].inner_text().strip() if len(names) > 1 else ""
            matched = brand_map.get(raw_model_name)
            if not matched and " " in raw_model_name:
                sub_name = raw_model_name.split(" ", 1)[1].strip()
                matched = brand_map.get(sub_name)
            if not matched and brand_by_name:
                for word in raw_model_name.replace("·", " ").split():
                    w = word.strip()
                    if w and brand_by_name.get(w):
                        matched = brand_by_name[w]
                        break
            if matched:
                data["brand_id"], data["brand_name"] = matched["brand_id"], matched["brand_name"]
            grade = m_box.query_selector(".css-13wylk3")
            data["grade_name"] = grade.inner_text().strip() if grade else ""
        yk_el = elem.query_selector(".css-6bza35")
        if yk_el:
            txt = yk_el.inner_text().strip()
            if "ㆍ" in txt:
                p = txt.split("ㆍ")
                data["year"], data["km"] = p[0].strip(), p[1].strip()
            else: data["year"], data["km"] = txt, ""
        price_area = elem.query_selector(".css-105xtr1 .css-1066lcq .css-dbu2tk")
        if price_area:
            sale = price_area.query_selector(".css-8sjynn")
            data["sale_price"] = sale.inner_text().strip() if sale else price_area.inner_text().strip()
        d_pnttm, c_dt = get_now_times()
        data["date_crtr_pnttm"], data["create_dt"] = d_pnttm, c_dt
    except: pass
    return data

def main():
    print(f"\n📄 [0단계] 브랜드 API 수집 → heydealer_brand_list.csv 생성")
    fetch_and_save_brand_csv()
    brand_map, brand_by_name = load_brand_mapping()
    list_fields = ["model_sn", "brand_id", "brand_name", "model_cd", "model_name", "model_second_name", "grade_name", "car_type", "year", "km", "sale_price", "detail_url", "date_crtr_pnttm", "create_dt"]

    if LIST_FILE.exists():
        LIST_FILE.unlink()
    if CAR_TYPE_LIST_FILE.exists():
        CAR_TYPE_LIST_FILE.unlink()

    print(f"\n🚀 [1단계] 목록 수집을 위해 브라우저를 실행합니다...")
    sys.stdout.flush()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        # 테스트(TARGET_COUNT 숫자) vs 전체(TARGET_COUNT=None) 에 따라 메시지 분기
        if TARGET_COUNT is not None:
            print(f"\n🚀 [1단계] 목록 수집 시작 (테스트: 목표 {TARGET_COUNT}개)")
        else:
            print(f"\n🚀 [1단계] 목록 수집 시작 (전체: 무한스크롤 끝까지)")
        list_url = f"{BASE_URL}/market/cars"
        for nav_try in range(3):
            try:
                page.goto(list_url, wait_until="commit", timeout=60000)
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                break
            except Exception as e:
                if nav_try < 2:
                    print(f"   ⚠️ 목록 페이지 재시도 ({nav_try + 2}/3)...")
                    time.sleep(3)
                else:
                    raise RuntimeError(f"목록 페이지 접속 실패: {list_url}") from e
        page.wait_for_timeout(3000)

        # ----- 차체: 클래스명 없이 텍스트·구조만 사용 (클래스 변경에 강함) -----
        # 흐름: [1] 차체 탭 클릭 → 오버레이에서 차종 버튼(경∙소형, 세단 등) 텍스트로 찾기 → 선택 → N대 보기 → 목록 수집
        # 정규화 후 비교용 (중점·공백 표기 차이 무시: SUV · RV, SUV∙RV, 경 · 소형 등)
        CANONICAL_CAR_BODY = {"경∙소형", "세단", "SUV∙RV", "쿠페", "리무진", "컨버터블", "해치백"}

        def _normalize_car_label(txt):
            """차종 텍스트 정규화: 공백·다양한 중점(·∙) 통일 후 비교"""
            if not txt:
                return ""
            s = (txt or "").strip()
            s = re.sub(r"\s*[·∙]\s*", "∙", s)  # ' · ' / '∙' -> '∙'
            s = re.sub(r"\s+", " ", s).strip()
            return s

        def _open_car_body_panel():
            """차체 탭: 텍스트 '차체'인 버튼 클릭 (클래스 무관)"""
            tab = page.get_by_role("button", name="차체")
            if tab.count() == 0:
                tab = page.locator("#root button").filter(has_text=re.compile(r"^차체$"))
            if tab.count() == 0:
                # 폴백: 필터 영역 6번째 버튼 (차체가 6번째인 경우)
                tab = page.locator("#root button[type='button']").nth(5)
            if tab.count() > 0:
                tab.first.scroll_into_view_if_needed()
                tab.first.click(force=True)
                page.wait_for_timeout(600)

        def _get_car_body_overlay():
            """차체 오버레이: '차체' 문구와 'N대 보기' 버튼이 함께 있는 컨테이너 (클래스 무관)"""
            overlay = page.locator("div").filter(
                has=page.locator("button").filter(has_text=re.compile(r"[\d,]+대\s*보기"))
            ).filter(has=page.get_by_text("차체"))
            return overlay.first

        def _get_car_type_labels_from_overlay(overlay):
            """오버레이 안에서 차종 버튼 텍스트만 수집 (순서 유지). 정규화 후 CANONICAL과 매칭, 클릭용으로는 페이지의 실제 텍스트 사용."""
            labels = []
            try:
                for node in overlay.locator("button").all():
                    raw = (node.inner_text() or "").strip()
                    if not raw or re.match(r"[\d,]+대\s*보기", raw) or raw == "초기화":
                        continue
                    canonical = _normalize_car_label(raw)
                    if canonical in CANONICAL_CAR_BODY:
                        labels.append(raw)
            except Exception:
                pass
            return labels

        _open_car_body_panel()
        page.wait_for_timeout(1500)
        car_type_entries = []
        try:
            for _ in range(2):
                overlay = _get_car_body_overlay()
                if overlay.count() > 0:
                    car_type_labels = _get_car_type_labels_from_overlay(overlay)
                    if car_type_labels:
                        car_type_entries = list(enumerate(car_type_labels))
                        break
                page.wait_for_timeout(1200)
            if not car_type_entries:
                page.keyboard.press("Escape")
                page.wait_for_timeout(1000)
                car_type_entries = [(0, "")]
            else:
                print(f" 📌 차종(차체) {len(car_type_entries)}개 (텍스트 기준): {[lbl for _, lbl in car_type_entries]}")
                for sn, (_, car_type_name) in enumerate(car_type_entries, 1):
                    save_to_csv_append(CAR_TYPE_LIST_FILE, ["car_type_sn", "car_type_name"], {"car_type_sn": sn, "car_type_name": car_type_name})
                print(f" 📄 차종 목록 저장: {CAR_TYPE_LIST_FILE}")
                page.keyboard.press("Escape")
                page.wait_for_timeout(1000)
        except Exception as e:
            print(f"   ⚠️ 차체 옵션 읽기 실패: {e}")
            car_type_entries = [(0, "")]

        raw_list, seen = [], set()

        for entry_idx, (car_type_idx, current_car_type) in enumerate(car_type_entries):
            collected_this_type = 0
            prev_count = len(raw_list)
            no_new_rounds = 0
            if len(car_type_entries) > 1:
                select_ok = False
                for _attempt in range(2):
                    try:
                        if _attempt > 0:
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(800)
                        _open_car_body_panel()
                        page.wait_for_timeout(700)
                        overlay = _get_car_body_overlay()
                        if overlay.count() == 0:
                            raise RuntimeError("차체 오버레이를 찾을 수 없음")
                        # 이전 차종 해제 후 현재 차종 선택 (텍스트로 버튼 찾기)
                        if entry_idx > 0:
                            prev_label = car_type_entries[entry_idx - 1][1]
                            prev_btn = overlay.locator("button").filter(has_text=re.compile(re.escape(prev_label)))
                            if prev_btn.count() > 0:
                                prev_btn.first.scroll_into_view_if_needed()
                                prev_btn.first.click(force=True)
                                page.wait_for_timeout(400)
                        btn = overlay.locator("button").filter(has_text=re.compile(re.escape(current_car_type)))
                        if btn.count() == 0:
                            print(f"   ⚠️ [{current_car_type}] 차종 버튼 없음, 건너뜀")
                            break
                        btn.first.scroll_into_view_if_needed()
                        page.wait_for_timeout(200)
                        btn.first.click(force=True)
                        page.wait_for_timeout(600)
                        view_btn = overlay.locator("button").filter(has_text=re.compile(r"[\d,]+대\s*보기"))
                        if view_btn.count() > 0:
                            view_btn.first.click()
                            page.wait_for_timeout(2500)
                        else:
                            page.wait_for_timeout(1500)
                        print(f" 🔘 차종 선택·적용: {current_car_type} → 목록 수집 시작")
                        select_ok = True
                        break
                    except Exception as e:
                        print(f"   ⚠️ 차종 선택/보기 실패 ({current_car_type}), 재시도 예정: {e}")
                if not select_ok:
                    continue

            # 5) 적용된 차종 목록만 무한 스크롤로 수집 (테스트 시 이 차종에서 TARGET_COUNT개만, 전체 시 끝까지)
            while True:
                if TARGET_COUNT is not None and collected_this_type >= TARGET_COUNT:
                    print(f" ✅ [{current_car_type}] 목표 {TARGET_COUNT}개 수집 완료")
                    break

                prev_collected_this_type = collected_this_type
                last_height = page.evaluate("document.body.scrollHeight")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2500)

                cards = page.query_selector_all('a[href^="/market/cars/"]')
                for card in cards:
                    if TARGET_COUNT is not None and collected_this_type >= TARGET_COUNT:
                        break

                    href = (card.get_attribute("href") or "").split("?")[0]
                    if href and href not in seen:
                        seen.add(href)
                        item = _extract_card_heydealer(card, len(raw_list) + 1, brand_map, car_type=current_car_type, brand_by_name=brand_by_name)
                        raw_list.append(item)
                        save_to_csv_append(LIST_FILE, list_fields, item)
                        collected_this_type += 1

                if collected_this_type == prev_collected_this_type:
                    no_new_rounds += 1
                else:
                    no_new_rounds = 0
                prev_count = len(raw_list)

                if TARGET_COUNT is not None:
                    print(f" 🔄 목록 수집 [{current_car_type}]: {collected_this_type}/{TARGET_COUNT}대 (총 {len(raw_list)}대)")
                else:
                    print(f" 🔄 목록 수집 [{current_car_type}]: {collected_this_type}대 (총 {len(raw_list)}대)")

                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    page.wait_for_timeout(2000)
                    if page.evaluate("document.body.scrollHeight") == last_height:
                        print(f"🏁 페이지 끝 도달 (총 {len(raw_list)}대)")
                        break
                else:
                    no_new_rounds = 0
                if no_new_rounds >= 2:
                    print(f"🏁 새 매물 없음, 수집 종료 (총 {len(raw_list)}대)")
                    break

        print(f"\n📄 목록 CSV 생성 완료: {LIST_FILE} ({len(raw_list)}건)")
        img_total = 0
        if len(raw_list) > 0:
            print(f"\n🚀 [2단계] 상세 페이지 이미지 수집")
            for idx, item in enumerate(raw_list, 1):
                model_cd = item.get("model_cd", "")
                detail_url = item.get("detail_url", "")
                if not detail_url:
                    continue
                for retry in range(3):
                    try:
                        print(f"   📷 ({idx}/{len(raw_list)}) {model_cd}")
                        page.goto(detail_url, wait_until="domcontentloaded", timeout=40000)
                        page.wait_for_load_state("load", timeout=15000)
                        page.wait_for_timeout(1500)
                        n_img = _collect_images_from_detail_page(page, model_cd)
                        img_total += n_img
                        break
                    except Exception as e:
                        if retry < 2:
                            time.sleep(2)
                        else:
                            print(f"      ⚠️ 건너뜀: {str(e)[:50]}")
            _img_dir = IMG_BASE / f"{datetime.now().strftime('%Y')}년" / datetime.now().strftime("%Y%m%d")
            print(f"\n📷 이미지 수집 완료: {img_total}장 → {_img_dir}")
        print(f"\n[{datetime.now()}] ✅ 작업 완료 (brand + car_type + list + 이미지)")
        print(f"   - brand.csv:   {BRAND_LIST_FILE}")
        print(f"   - car_type.csv: {CAR_TYPE_LIST_FILE}")
        print(f"   - list.csv:    {LIST_FILE} ({len(raw_list)}건)")
        print(f"   - 이미지:      {img_total}장 → {IMG_BASE}/연도/날짜/")
        print(f"   - 결과 폴더:   {RESULT_DIR}")
        print(f"   - 로그:        {LOG_FILE}")

        browser.close()

if __name__ == "__main__":
    main()