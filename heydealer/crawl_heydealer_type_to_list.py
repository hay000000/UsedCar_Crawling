#!/usr/bin/env python3
import csv
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests
from playwright.sync_api import sync_playwright

# 이미지 경로는 config에서 로드
try:
    from config import get_list_image_base_dir, get_list_image_rel, get_detail_image_rel
except ImportError:
    get_list_image_base_dir = get_list_image_rel = get_detail_image_rel = None

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
RESULT_DIR = BASE_DIR.parent / "result" / "heydealer"
LOG_DIR = BASE_DIR.parent / "logs" / "heydealer"
# imgs: config.py의 IMG_LIST_REL, IMG_DETAIL_REL 사용. config 없으면 기본값
if get_list_image_base_dir and get_list_image_rel:
    IMG_BASE = get_list_image_base_dir("heydealer")
    IMG_LIST_REL = get_list_image_rel("heydealer")
else:
    IMG_BASE = BASE_DIR.parent / "imgs" / "heydealer"
    IMG_LIST_REL = "imgs/heydealer/list"

if get_detail_image_rel:
    DETAIL_IMG_REL = get_detail_image_rel("heydealer")
else:
    DETAIL_IMG_REL = "imgs/heydealer/detail"

# 폴더 생성
RESULT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
IMG_BASE.mkdir(parents=True, exist_ok=True)
(IMG_BASE / "list").mkdir(parents=True, exist_ok=True)
(IMG_BASE / "detail").mkdir(parents=True, exist_ok=True)

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
    "model_sn",
    # "brand_id",
    "brand_list",  # brand_name
    # "model_group_id",
    "car_list",  # model_group_name
    # "model_id",
    "model_list",  # model_name
    "model_list_1",
    # "model_list_2_id",
    "model_list_2",
    "production_period", "data_crtr_pnttm", "create_dt"
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
                    model_id = model.get("hash_id", "")
                    model_name = model.get("name", "")
                    period = model.get("period", "")
                    # models/{model_id}/ API로 grades·details 수집 (model_list_1, model_list_2_id, model_list_2)
                    model_resp = session.get(f"{API_BASE}/models/{model_id}/", timeout=15)
                    if model_resp.status_code != 200:
                        row = {
                            "model_sn": n_written + 1,
                            # "brand_id": brand_id,
                            "brand_list": brand_name,
                            # "model_group_id": mg_id,
                            "car_list": mg_name,
                            # "model_id": model_id,
                            "model_list": model_name,
                            "model_list_1": "",
                            # "model_list_2_id": "",
                            "model_list_2": "",
                            "production_period": period,
                            "data_crtr_pnttm": d_pnttm,
                            "create_dt": c_dt,
                        }
                        save_to_csv_append(BRAND_LIST_FILE, BRAND_CSV_FIELDS, row)
                        n_written += 1
                        time.sleep(0.1)
                        continue
                    grades = model_resp.json().get("grades") or []
                    if not grades:
                        row = {
                            "model_sn": n_written + 1,
                            # "brand_id": brand_id,
                            "brand_list": brand_name,
                            # "model_group_id": mg_id,
                            "car_list": mg_name,
                            # "model_id": model_id,
                            "model_list": model_name,
                            "model_list_1": "",
                            # "model_list_2_id": "",
                            "model_list_2": "",
                            "production_period": period,
                            "data_crtr_pnttm": d_pnttm,
                            "create_dt": c_dt,
                        }
                        save_to_csv_append(BRAND_LIST_FILE, BRAND_CSV_FIELDS, row)
                        n_written += 1
                    else:
                        for grade in grades:
                            grade_name = grade.get("name", "")
                            details = grade.get("details") or []
                            if not details:
                                row = {
                                    "model_sn": n_written + 1,
                                    # "brand_id": brand_id,
                                    "brand_list": brand_name,
                                    # "model_group_id": mg_id,
                                    "car_list": mg_name,
                                    # "model_id": model_id,
                                    "model_list": model_name,
                                    "model_list_1": grade_name,
                                    # "model_list_2_id": "",
                                    "model_list_2": "",
                                    "production_period": period,
                                    "data_crtr_pnttm": d_pnttm,
                                    "create_dt": c_dt,
                                }
                                save_to_csv_append(BRAND_LIST_FILE, BRAND_CSV_FIELDS, row)
                                n_written += 1
                            else:
                                for detail in details:
                                    row = {
                                        "model_sn": n_written + 1,
                                        # "brand_id": brand_id,
                                        "brand_list": brand_name,
                                        # "model_group_id": mg_id,
                                        "car_list": mg_name,
                                        # "model_id": model_id,
                                        "model_list": model_name,
                                        "model_list_1": grade_name,
                                        # "model_list_2_id": detail.get("hash_id", ""),
                                        "model_list_2": detail.get("name", ""),
                                        "production_period": period,
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
                info = {"brand_id": "", "brand_name": (row.get("brand_list") or "").strip()}
                model_name = (row.get("model_list") or "").strip()
                if model_name:
                    brand_map[model_name] = info
                bn = info["brand_name"]
                if bn and bn not in brand_by_name:
                    brand_by_name[bn] = info
    else:
        print(f"⚠️ 매핑 파일이 없습니다: {BRAND_LIST_FILE}")
    return brand_map, brand_by_name


def _row_key(row, trim_model_list=False, drop_first_word=False):
    """list/brand 행에서 model_list+model_list_1+model_list_2 결합.
    trim_model_list=True: model_list는 띄어쓰기 앞단(첫 단어)만.
    drop_first_word=True: model_list에서 앞에서부터 띄어쓰기 한 부분(첫 단어)을 지우고 나머지 사용."""
    m = (row.get("model_list") or "").strip()
    if trim_model_list and m:
        m = m.split()[0]
    elif drop_first_word and m:
        m = m.split(" ", 1)[1].strip() if " " in m else ""
    m1 = (row.get("model_list_1") or "").strip()
    m2 = (row.get("model_list_2") or "").strip()
    return m + m1 + m2


def _key_match(a, b):
    """포함 관계 매칭: in 2가지(a in b, b in a) + str.find 2가지(a.find(b), b.find(a)) 모두 사용."""
    if not a or not b:
        return False
    if a in b or b in a:           # in 2가지
        return True
    if a.find(b) >= 0 or b.find(a) >= 0:  # find 2가지
        return True
    return False


def _find_matching_brand_row(list_row, brand_rows):
    """list 행과 brand 행 매칭:
    1) 동일: list(model_list+model_list_1+model_list_2) == brand(동일)
    2) list model_list 앞단만(첫 단어) + model_list_1+2 로 in/find 비교
    3) list model_list에서 앞 한 단어 지우고 나머지 + model_list_1+2 로 in/find 비교 (폭스바겐 더 뉴 파사트 → 더 뉴 파사트+... 와 brand 매칭)"""
    list_key = _row_key(list_row)
    list_key_trim = _row_key(list_row, trim_model_list=True)
    list_key_drop = _row_key(list_row, drop_first_word=True)
    for br in brand_rows:
        brand_key = _row_key(br)
        if list_key == brand_key:
            return br
    for br in brand_rows:
        brand_key = _row_key(br)
        if _key_match(list_key_trim, brand_key):
            return br
    for br in brand_rows:
        brand_key = _row_key(br)
        if _key_match(list_key_drop, brand_key):
            return br
    return None


def load_brand_rows():
    """brand_list.csv 전체 행 로드 (brand_list ~ model_list_2 매칭용)."""
    rows = []
    if not BRAND_LIST_FILE.exists():
        return rows
    with open(BRAND_LIST_FILE, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def merge_brand_into_list(raw_list, list_fields):
    """list.csv 행에 대해 brand.csv와 model_list+model_list_1+model_list_2로 매칭 후, 일치하면 brand_list~model_list_2 채움."""
    brand_rows = load_brand_rows()
    if not brand_rows:
        return
    updated = 0
    for item in raw_list:
        br = _find_matching_brand_row(item, brand_rows)
        if br is None:
            continue
        item["brand_list"] = (br.get("brand_list") or "").strip()
        item["car_list"] = (br.get("car_list") or "").strip()
        item["model_list"] = (br.get("model_list") or "").strip()
        item["model_list_1"] = (br.get("model_list_1") or "").strip()
        item["model_list_2"] = (br.get("model_list_2") or "").strip()
        updated += 1
    if updated:
        rewrite_csv_atomic(LIST_FILE, list_fields, raw_list)
        print(f"   [매칭] brand.csv와 일치하여 list.csv에 brand_list~model_list_2 반영: {updated}건")


def get_now_times():
    now = datetime.now()
    return now.strftime("%Y%m%d"), now.strftime("%Y%m%d%H%M")

FILTERS_API = "https://api.heydealer.com/v2/customers/web/market/filters/"
CAR_TYPE_CSV_FIELDS = ["car_type_sn", "car_type_name", "date_crtr_pnttm", "create_dt"]


def fetch_filters_car_type_entries():
    """filters API에서 차종 (value, name) 목록만 가져옴. CSV 저장 없음. list 수집 시 차종 선택용."""
    entries = []
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        })
        resp = session.get(FILTERS_API, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        for item in (data.get("car_shape") or []):
            name = (item.get("name") or "").strip()
            value = (item.get("value") or "").strip()
            if value:
                entries.append((value, name))
        if entries:
            print(f"   [차종] 목록 수집용 차종 {len(entries)}개 로드 (경∙소형, 세단, SUV∙RV 등)")
    except Exception as e:
        print(f"   ⚠️ filters API 실패: {e}")
    return entries


def fetch_filters_and_save_car_type_list():
    """filters API의 car_shape로 차종 목록을 가져와 heydealer_car_type_list.csv 저장. (value, name) 리스트 반환."""
    if CAR_TYPE_LIST_FILE.exists():
        CAR_TYPE_LIST_FILE.unlink()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    })
    d_pnttm, c_dt = get_now_times()
    entries = []
    try:
        resp = session.get(FILTERS_API, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        car_shape = data.get("car_shape") or []
        for sn, item in enumerate(car_shape, 1):
            name = (item.get("name") or "").strip()
            value = (item.get("value") or "").strip()
            if not value:
                continue
            entries.append((value, name))
            save_to_csv_append(CAR_TYPE_LIST_FILE, CAR_TYPE_CSV_FIELDS, {
                "car_type_sn": sn,
                "car_type_name": name,
                "date_crtr_pnttm": d_pnttm,
                "create_dt": c_dt,
            })
        if entries:
            print(f" 📄 차종 목록 API 수집: {CAR_TYPE_LIST_FILE} ({len(entries)}개)")
        else:
            print("   ⚠️ filters API에서 car_shape 없음")
    except Exception as e:
        print(f"   ⚠️ filters API 수집 실패: {e}")
    return entries

def save_to_csv_append(file_path, fieldnames, data_dict):
    file_exists = Path(file_path).exists()
    with open(file_path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        if not file_exists:
            writer.writeheader()
        writer.writerow(data_dict)


def rewrite_csv_atomic(file_path, fieldnames, rows):
    """CSV를 현재 rows 기준으로 원자적으로 재작성 (car_imgs 등 진행 반영)."""
    file_path = Path(file_path)
    tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    tmp_path.replace(file_path)


def get_today_img_rel_dir():
    r"""오늘 날짜 기준 상대 디렉터리 (예: imgs/heydealer/list/2026년/20260312). WSL 경로 예: \wsl.localhost\Ubuntu-22.04\...\imgs\heydealer\list\2026년\20260312"""
    now = datetime.now()
    return f"{IMG_LIST_REL}/{now.strftime('%Y')}년/{now.strftime('%Y%m%d')}"


def get_today_detail_img_rel_dir():
    """상세 이미지 상대 디렉터리: imgs/heydealer/detail/2026년/20260312"""
    now = datetime.now()
    return f"{DETAIL_IMG_REL}/{now.strftime('%Y')}년/{now.strftime('%Y%m%d')}"


def download_list_image(img_url, product_id):
    """상품 대표 이미지 1장만 다운로드 → product_id_list.png. 성공 시 상대 경로 반환, 실패 시 ""."""
    try:
        if not img_url or "svg" in img_url.lower():
            return ""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": BASE_URL,
        }
        response = requests.get(img_url, stream=True, timeout=15, headers=headers)
        if response.status_code != 200:
            return ""
        save_dir = IMG_BASE / "list" / f"{datetime.now().strftime('%Y')}년" / datetime.now().strftime("%Y%m%d")
        save_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{product_id}_list.png"
        save_path = save_dir / filename
        with open(save_path, "wb") as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
        return f"{get_today_img_rel_dir()}/{filename}"
    except Exception:
        return ""


def download_detail_image(img_url, product_id, idx):
    """상세 페이지 이미지 1장 다운로드 → detail/연도/날짜/{product_id}_1.png, _2.png ... (예: Wnqe5KnL_1.png). 성공 시 상대 경로 반환."""
    try:
        if not img_url or "svg" in img_url.lower():
            return ""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": BASE_URL,
        }
        response = requests.get(img_url, stream=True, timeout=15, headers=headers)
        if response.status_code != 200:
            return ""
        save_dir = IMG_BASE / "detail" / f"{datetime.now().strftime('%Y')}년" / datetime.now().strftime("%Y%m%d")
        save_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{product_id}_{idx}.png"
        save_path = save_dir / filename
        with open(save_path, "wb") as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
        return f"{get_today_detail_img_rel_dir()}/{filename}"
    except Exception:
        return ""


def download_image(img_url, product_id, idx):
    """이미지 다운로드. 저장 경로: imgs/heydealer/연도/YYYYMMDD/product_id_idx.ext"""
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
        filename = f"{product_id}_{idx}.{ext}"
        save_path = save_dir / filename
        with open(save_path, "wb") as f:
            for chunk in response.iter_content(1024):
                f.write(chunk)
        return True
    except Exception:
        return False

# 상세 페이지 리스트 이미지 DOM: #root > .css-kuuk2w > ... > .css-1fg02ng > .css-vdxqtk > img
LIST_IMG_DOM_SELECTOR = (
    "#root .css-kuuk2w .css-18e6263 .css-17qdlp1 .css-fhycda .css-1x0imnr "
    ".css-1t74t4t .css-a97e7u .css-a97e7u .css-8n2v9x .css-di7boj .css-1fg02ng .css-vdxqtk img"
)


def _collect_image_urls_from_detail_page(page):
    """상세 페이지에서 차량 이미지 URL 목록을 수집 (중복 제거, 순서 유지). list 폴더용이 아닌 detail 폴더 저장용."""
    seen = set()
    urls = []
    try:
        page.wait_for_timeout(1200)
        imgs = page.query_selector_all(LIST_IMG_DOM_SELECTOR)
        for img in imgs:
            src = (img.get_attribute("src") or img.get_attribute("data-src") or "").strip()
            if src and "svg" not in src.lower() and src not in seen:
                seen.add(src)
                urls.append(src)
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
                    for img in sec2.query_selector_all(sel):
                        src = (img.get_attribute("src") or img.get_attribute("data-src") or "").strip()
                        if src and "svg" not in src.lower() and src not in seen:
                            seen.add(src)
                            urls.append(src)
            if len(ltrevz_sections) >= 4:
                sec4 = ltrevz_sections[3]
                for sel in [".css-5pr39e .css-1i3qy3r .css-hf19cn .css-1a3591h img.css-158t7i4", ".css-5pr39e .css-1i3qy3r .css-w9nhgi img.css-158t7i4", ".css-hf19cn .css-1a3591h img", ".css-hf19cn .css-w9nhgi img", ".css-w9nhgi img.css-158t7i4"]:
                    for img in sec4.query_selector_all(sel):
                        src = (img.get_attribute("src") or img.get_attribute("data-src") or "").strip()
                        if src and "svg" not in src.lower() and src not in seen:
                            seen.add(src)
                            urls.append(src)
        for img in page.query_selector_all("img[src*='heydealer.com'], img[src*='cdn.'], .css-w9nhgi img, .css-1a3591h img, main img"):
            src = (img.get_attribute("src") or img.get_attribute("data-src") or "").strip()
            if not src or "svg" in src.lower() or src in seen:
                continue
            seen.add(src)
            urls.append(src)
        page.wait_for_timeout(2000)
        for i in range(1, 12):
            page.evaluate(f"window.scrollTo(0, {i * 600})")
            time.sleep(0.2)
        for img in page.query_selector_all("img[src], img[data-src]"):
            src = (img.get_attribute("src") or img.get_attribute("data-src") or "").strip()
            if not src or "svg" in src.lower() or src in seen:
                continue
            if "heydealer" in src or "cdn." in src or len(src) > 20:
                seen.add(src)
                urls.append(src)
    except Exception as e:
        print(f"      ❌ 이미지 수집 오류: {str(e)[:60]}")
    return urls


def _collect_images_from_detail_page(page, product_id):
    """상세 페이지에서 이미지 URL 수집 후 detail 폴더에 product_id_1.png, product_id_2.png ... 로 저장. car_imgs에는 첫 번째 상대 경로 반환."""
    car_imgs_path = ""
    urls = _collect_image_urls_from_detail_page(page)
    for idx, src in enumerate(urls, 1):
        path = download_detail_image(src, product_id, idx)
        if path and not car_imgs_path:
            car_imgs_path = path
    return car_imgs_path

def _extract_card_heydealer(elem, idx, brand_map, car_type="", brand_by_name=None) -> dict:
    data = {"model_sn": idx, "brand_id": "", "brand_name": "", "car_type": car_type, "car_list": "", "car_imgs": "", "list_image_url": "", "car_name": ""}
    try:
        href = elem.get_attribute("href") or ""
        full_url = (BASE_URL + href).split("?")[0] if not href.startswith("http") else href.split("?")[0]
        data["product_id"] = full_url.split("/")[-1]
        data["detail_url"] = full_url
        # 목록 카드 썸네일 이미지 URL (image.heydealer.com 등) → 이 URL로 저장해야 상세페이지 이미지가 아닌 리스트 이미지가 저장됨
        for img in elem.query_selector_all("img"):
            src = (img.get_attribute("src") or img.get_attribute("data-src") or "").strip()
            if not src or "svg" in src.lower():
                continue
            if "image.heydealer.com" in src or "heydealer.com" in src:
                data["list_image_url"] = src
                break
        if not data["list_image_url"] and elem.query_selector("img"):
            first_img = elem.query_selector("img")
            src = (first_img.get_attribute("src") or first_img.get_attribute("data-src") or "").strip()
            if src and "svg" not in src.lower():
                data["list_image_url"] = src
        m_box = elem.query_selector(".css-9j6363")
        if m_box:
            # 차량 풀네임 (예: "더 뉴 모닝 (JA) 시그니처") → car_name
            data["car_name"] = m_box.inner_text().strip() if m_box else ""
            names = m_box.query_selector_all(".css-jk6asd")
            raw_model_name = names[0].inner_text().strip() if len(names) > 0 else ""
            data["model_name"] = raw_model_name
            data["model_list"] = raw_model_name
            data["model_second_name"] = names[1].inner_text().strip() if len(names) > 1 else ""
            if len(names) > 1:
                data["model_list_1"] = data["model_second_name"]
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
                data["brand_list"] = matched["brand_name"]
            grade = m_box.query_selector(".css-13wylk3")
            data["grade_name"] = grade.inner_text().strip() if grade else ""
            if data["grade_name"]:
                data["model_list_2"] = data["grade_name"]
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
    # --- brand_list.csv / car_type_list.csv 생성은 주석 처리 (파일 생성 안 함) ---
    # print(f"\n📄 [0단계] 브랜드 API 수집 → heydealer_brand_list.csv 생성")
    # fetch_and_save_brand_csv()
    # brand_map, brand_by_name = load_brand_mapping()
    brand_map, brand_by_name = {}, {}
    # heydealer_list.csv 컬럼 순서: brand_list, car_list, model_list, model_list_1, model_list_2, car_name ...
    list_fields = [
        "model_sn",
        "product_id",
        "car_type",
        "brand_list",
        "car_list",
        "model_list",
        "model_list_1",
        "model_list_2",
        "car_name",
        "year",
        "km",
        "sale_price",
        "detail_url",
        "car_imgs",
        "date_crtr_pnttm",
        "create_dt",
    ]

    if LIST_FILE.exists():
        LIST_FILE.unlink()

    # list.csv는 차체별(경∙소형, 세단, SUV∙RV, 쿠페, 리무진, 컨버터블, 해치백)로 수집. API에서 차종만 조회, car_type_list.csv 파일은 생성 안 함.
    car_type_entries = fetch_filters_car_type_entries()
    if not car_type_entries:
        car_type_entries = [(0, "")]
        print("   [차종] API 실패 → 필터 없이 전체만 수집합니다.")

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
            print(f"\n[1단계] 목록 수집 시작 (테스트: 목표 {TARGET_COUNT}개)")
        else:
            print(f"\n[1단계] 목록 수집 시작 (전체: 무한스크롤 끝까지)")
        list_url = f"{BASE_URL}/market/cars"
        for nav_try in range(3):
            try:
                page.goto(list_url, wait_until="commit", timeout=60000)
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                break
            except Exception as e:
                if nav_try < 2:
                    print(f"목록 페이지 재시도 ({nav_try + 2}/3)...")
                    time.sleep(3)
                else:
                    raise RuntimeError(f"목록 페이지 접속 실패: {list_url}") from e
        page.wait_for_timeout(3000)

        # 차종은 filters API로 이미 수집됨. 목록 수집 시 URL 쿼리 car_shape로 차체 선택.
        raw_list, seen = [], set()
        brand_rows = load_brand_rows()  # 행 추가 시마다 brand_list 등 바로 채우기 위해 미리 로드

        for entry_idx, (car_type_value, car_type_name) in enumerate(car_type_entries):
            display_name = car_type_name or "전체"
            collected_this_type = 0
            prev_count = len(raw_list)
            no_new_rounds = 0
            # 차체 선택: 사이트는 루트 경로 + car-shape 쿼리로 필터 적용 (예: ?car-shape=convertible, ?car-shape=hatchback)
            if car_type_value:
                v = quote(str(car_type_value), safe="")
                list_url_with_filter = f"{BASE_URL}/?car-shape={v}"
                try:
                    page.goto(list_url_with_filter, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_load_state("load", timeout=15000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        pass
                    page.wait_for_timeout(2500)
                    # 필터된 목록만 수집: 카드가 있으면 대기 (0대인 차종은 timeout 후 0건 수집)
                    try:
                        page.wait_for_selector('a[href^="/market/cars/"]', timeout=15000)
                    except Exception:
                        pass
                    page.wait_for_timeout(1000)
                    print(f" 차종 적용: {car_type_name} (car-shape={car_type_value}) → 목록 수집 시작")
                except Exception as e:
                    print(f" [{display_name}] URL 이동 실패, 건너뜀: {e}")
                    continue
            else:
                # 차종 없음(전체): 이미 list_url 로드됨
                print(f"차종 없음(전체) → 목록 수집 시작")
                try:
                    page.wait_for_selector('a[href^="/market/cars/"]', timeout=10000)
                except Exception:
                    pass
                page.wait_for_timeout(1000)

            # 적용된 차종 목록만 무한 스크롤로 수집 (테스트 시 이 차종에서 TARGET_COUNT개만, 전체 시 끝까지)
            while True:
                if TARGET_COUNT is not None and collected_this_type >= TARGET_COUNT:
                    print(f" [{display_name}] 목표 {TARGET_COUNT}개 수집 완료")
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
                        item = _extract_card_heydealer(card, len(raw_list) + 1, brand_map, car_type=car_type_name, brand_by_name=brand_by_name)
                        # brand_list 등 행 단위로 바로 매칭 후 append (끊겨도 확인 가능)
                        br = _find_matching_brand_row(item, brand_rows)
                        if br:
                            item["brand_list"] = (br.get("brand_list") or "").strip()
                            item["car_list"] = (br.get("car_list") or "").strip()
                            item["model_list"] = (br.get("model_list") or "").strip()
                            item["model_list_1"] = (br.get("model_list_1") or "").strip()
                            item["model_list_2"] = (br.get("model_list_2") or "").strip()
                        raw_list.append(item)
                        save_to_csv_append(LIST_FILE, list_fields, item)
                        collected_this_type += 1

                if collected_this_type == prev_collected_this_type:
                    no_new_rounds += 1
                else:
                    no_new_rounds = 0
                prev_count = len(raw_list)

                if TARGET_COUNT is not None:
                    print(f" 목록 수집 [{display_name}]: {collected_this_type}/{TARGET_COUNT}대 (총 {len(raw_list)}대)")
                else:
                    print(f" 목록 수집 [{display_name}]: {collected_this_type}대 (총 {len(raw_list)}대)")

                # 필터 적용된 차종인데 첫 수집에서 0대면 매물 없음. 스크롤하면 다른 차종이 로드돼 잘못 수집될 수 있음.
                if car_type_value and collected_this_type == 0 and prev_collected_this_type == 0:
                    print(f" [{display_name}] 매물 0대 → 수집 종료")
                    break

                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    page.wait_for_timeout(2000)
                    if page.evaluate("document.body.scrollHeight") == last_height:
                        print(f"페이지 끝 도달 (총 {len(raw_list)}대)")
                        break
                else:
                    no_new_rounds = 0
                if no_new_rounds >= 2:
                    print(f"새 매물 없음, 수집 종료 (총 {len(raw_list)}대)")
                    break

        print(f"\n목록 CSV 생성 완료: {LIST_FILE} ({len(raw_list)}건)")
        if len(raw_list) > 0:
            print(f"\n[2단계] 목록 이미지 + 상세 이미지 수집")
            for idx, item in enumerate(raw_list, 1):
                product_id = item.get("product_id", "")  # 예: Wnqe5KnL
                detail_url = item.get("detail_url", "")

                # 1) List 폴더: 목록 카드 URL이 있으면 list에만 저장 (car_imgs용) → 바로 CSV 반영
                list_image_url = item.get("list_image_url", "").strip()
                if list_image_url:
                    car_imgs_path = download_list_image(list_image_url, product_id)
                    if car_imgs_path:
                        item["car_imgs"] = car_imgs_path
                        rewrite_csv_atomic(LIST_FILE, list_fields, raw_list)

                # 2) Detail 폴더: 항상 상세 페이지 접속 → product_id_1.png, product_id_2.png ... 저장
                if not detail_url:
                    continue
                for retry in range(3):
                    try:
                        print(f"({idx}/{len(raw_list)}) {product_id} (list + detail)")
                        page.goto(detail_url, wait_until="domcontentloaded", timeout=40000)
                        page.wait_for_load_state("load", timeout=15000)
                        page.wait_for_timeout(1500)
                        first_detail_path = _collect_images_from_detail_page(page, product_id)
                        if first_detail_path and not item.get("car_imgs"):
                            item["car_imgs"] = first_detail_path
                        rewrite_csv_atomic(LIST_FILE, list_fields, raw_list)  # 건당 바로 반영
                        break
                    except Exception as e:
                        if retry < 2:
                            time.sleep(2)
                        else:
                            print(f" 건너뜀: {str(e)[:50]}")
            _list_dir = IMG_BASE / "list" / f"{datetime.now().strftime('%Y')}년" / datetime.now().strftime("%Y%m%d")
            _detail_dir = IMG_BASE / "detail" / f"{datetime.now().strftime('%Y')}년" / datetime.now().strftime("%Y%m%d")
            print(f"\n📷 이미지 수집 완료")
            print(f"   - list:   {_list_dir} (목록 썸네일, car_imgs)")
            print(f"   - detail: {_detail_dir} (상세 이미지 product_id_1.png, _2.png ...)")
        print(f"\n[{datetime.now()}] 작업 완료 (brand + car_type + list + 이미지)")
        print(f"   - brand.csv:   {BRAND_LIST_FILE}")
        print(f"   - car_type.csv: {CAR_TYPE_LIST_FILE}")
        print(f"   - list.csv:    {LIST_FILE} ({len(raw_list)}건)")
        print(f"   - 이미지 list: {IMG_BASE}/list/연도/날짜/ (목록만)")
        print(f"   - 이미지 detail: {IMG_BASE}/detail/연도/날짜/ (상세 _1, _2.png)")
        print(f"   - 결과 폴더:   {RESULT_DIR}")
        print(f"   - 로그:        {LOG_FILE}")

        browser.close()

if __name__ == "__main__":
    main()