#!/usr/bin/env python3
import csv
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
DETAIL_FILE = RESULT_DIR / "heydealer_detail.csv"
CAR_TYPE_LIST_FILE = RESULT_DIR / "heydealer_car_type_list.csv"

# --- 로그 설정 ---
# now_date = datetime.now().strftime("%Y%m%d")
# LOG_FILE = LOG_DIR / f"heydealer_list_detail_log_{now_date}.log"
LOG_FILE = LOG_DIR / f"heydealer_list_detail.log"

class Logger(object):
    def __init__(self):
        self.terminal = sys.stdout
        self.log = open(LOG_FILE, "a", encoding="utf-8")
    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
    def flush(self):
        pass

sys.stdout = Logger()

_today_img_dir = IMG_BASE / f"{datetime.now().strftime('%Y')}년" / datetime.now().strftime("%Y%m%d")
print(f"[{datetime.now()}] 🏁 헤이딜러 수집 프로그램 시작")
print(f"📁 이미지 저장 경로: {_today_img_dir}")

def load_brand_mapping():
    """model_name(정확) -> {brand_id, brand_name}, brand_name(브랜드명) -> {brand_id, brand_name} 둘 다 반환."""
    brand_map = {}
    brand_by_name = {}
    brand_file = RESULT_DIR / "heydealer_brand_list.csv"
    if brand_file.exists():
        with open(brand_file, "r", encoding="utf-8-sig") as f:
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
        print(f"⚠️ 매핑 파일이 없습니다: {brand_file}")
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
    """이미지 다운로드 함수. 저장 경로: imgs/heydealer/연도/YYYYMMDD/model_cd_idx.ext"""
    try:
        if not img_url or "svg" in img_url.lower():
            return False
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": BASE_URL
        }
        
        response = requests.get(img_url, stream=True, timeout=15, headers=headers)
        
        if response.status_code == 200:
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
        else:
            return False
            
    except Exception as e:
        return False

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

def _extract_detail_smart(page, list_item) -> dict:
    """
    상세 페이지 데이터 추출 + 구조화된 이미지 수집
    
    구조:
    .css-1uus6sd > .css-12qft46
      ├─ 두번째 .css-ltrevz > .css-5pr39e > .css-1i3qy3r > .css-1dpi6xl > button.css-q47uzu > img.css-q38rgl
      └─ 네번째 .css-ltrevz > .css-5pr39e > .css-1i3qy3r > .css-hf19cn > .css-1a3591h > img.css-158t7i4
          └─  .css-ltrevz > .css-5pr39e > .css-1i3qy3r > .css-hf19cn > .css-w9nhgi > img.css-158t7i4
    
    """
    res = {
        "model_sn": str(list_item.get("model_sn", "")),
        "brand_id": str(list_item.get("brand_id", "")),
        "brand_name": str(list_item.get("brand_name", "")),
        "model_cd": str(list_item.get("model_cd", "")),
        "model_name": str(list_item.get("model_name", "")),
        "model_second_name": str(list_item.get("model_second_name", "")),
        "grade_name": str(list_item.get("grade_name", "")),
        "year": str(list_item.get("year", "")),
        "km": str(list_item.get("km", "")),
        "refund": "", "guarantee": "", "accident": "", 
        "inner_car_wash": "", "insurance": "", "exterior_description": "", "interior_description": "", 
        "options": "", "delivery_information": "", "recommendation_comment": "",
        "tire": "", "tinting": "", "car_key": "",
        "detail_url": list_item["detail_url"],
        "date_crtr_pnttm": list_item["date_crtr_pnttm"],
        "create_dt": list_item["create_dt"]
    }
    
    try:
        try:
            page.wait_for_selector(".css-12qft46", timeout=20000)
        except Exception:
            try:
                page.wait_for_selector(".css-113wzqa", timeout=10000)
            except Exception:
                pass
        page.wait_for_timeout(2000)
        # 레이지 로딩/SPA 대비: 먼저 스크롤해서 섹션·이미지 로드
        for i in range(1, 14):
            page.evaluate(f"window.scrollTo(0, {i * 500})")
            time.sleep(0.15)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(800)
        
        # print(f"      📸 이미지 수집 시작: {res['model_cd']}")
        
        # === 이미지 수집 (저장 대상 구조 준수) ===
        # 구조: .css-1uus6sd > .css-12qft46
        #   ├─ 두번째 .css-ltrevz > .css-5pr39e > .css-1i3qy3r > .css-1dpi6xl > button.css-q47uzu > img.css-q38rgl
        #   └─ 네번째 .css-ltrevz > .css-5pr39e > .css-1i3qy3r > .css-hf19cn > .css-1a3591h > img.css-158t7i4
        #       └─ .css-w9nhgi > img.css-158t7i4
        downloaded_urls = set()
        img_idx = 1

        detail_container = page.query_selector(".css-1uus6sd .css-12qft46")
        if not detail_container:
            detail_container = page.query_selector(".css-12qft46")
        if detail_container:
            ltrevz_sections = detail_container.query_selector_all(".css-ltrevz")
            # print(f"      🔍 발견된 섹션 수: {len(ltrevz_sections)}")

            # (1) 두번째 .css-ltrevz > ... > button.css-q47uzu > img.css-q38rgl
            if len(ltrevz_sections) >= 2:
                sec2 = ltrevz_sections[1]
                imgs_btn = sec2.query_selector_all(".css-5pr39e .css-1i3qy3r .css-1dpi6xl button.css-q47uzu img.css-q38rgl")
                if not imgs_btn:
                    imgs_btn = sec2.query_selector_all("button.css-q47uzu img.css-q38rgl")
                if not imgs_btn:
                    imgs_btn = sec2.query_selector_all("button img, .css-q47uzu img")
                # print(f"      📷 색상 파트 이미지: {len(imgs_btn)}개")
                for img in imgs_btn:
                    src = img.get_attribute("src") or img.get_attribute("data-src")
                    if src and src not in downloaded_urls and "svg" not in src.lower():
                        if download_image(src, res["model_cd"], img_idx):
                            downloaded_urls.add(src)
                            img_idx += 1

            # (2) 네번째 .css-ltrevz > ... > .css-hf19cn > .css-1a3591h > img.css-158t7i4
            # (3) 네번째 .css-ltrevz > ... > .css-hf19cn > .css-w9nhgi > img.css-158t7i4
            if len(ltrevz_sections) >= 4:
                sec4 = ltrevz_sections[3]
                for sel in [
                    ".css-5pr39e .css-1i3qy3r .css-hf19cn .css-1a3591h img.css-158t7i4",
                    ".css-5pr39e .css-1i3qy3r .css-w9nhgi img.css-158t7i4",
                    ".css-hf19cn .css-1a3591h img",
                    ".css-hf19cn .css-w9nhgi img",
                    ".css-w9nhgi img.css-158t7i4",
                ]:
                    for img in sec4.query_selector_all(sel):
                        src = img.get_attribute("src") or img.get_attribute("data-src")
                        if src and src not in downloaded_urls and "svg" not in src.lower():
                            if download_image(src, res["model_cd"], img_idx):
                                downloaded_urls.add(src)
                                img_idx += 1
                # print(f"      📷 총 이미지 누적: {img_idx - 1}개")

        if img_idx == 1:
            fallback_imgs = page.query_selector_all(
                "img[src*='heydealer.com'], img[src*='cdn.'], .css-w9nhgi img, .css-1a3591h img, main img"
            )
            for img in fallback_imgs:
                src = img.get_attribute("src") or img.get_attribute("data-src")
                if not src or "svg" in src.lower() or src in downloaded_urls:
                    continue
                if download_image(src, res["model_cd"], img_idx):
                    downloaded_urls.add(src)
                    img_idx += 1
            if img_idx > 1:
                print(f"      📷 폴백으로 {img_idx - 1}개 이미지 수집")
        # 섹션 적거나 0개일 때 한 번 더 스크롤 후 재시도 (vlgoq6l0 등 지연 로딩 페이지)
        if img_idx == 1:
            page.wait_for_timeout(2000)
            for i in range(1, 12):
                page.evaluate(f"window.scrollTo(0, {i * 600})")
                time.sleep(0.2)
            retry_imgs = page.query_selector_all("img[src], img[data-src]")
            for img in retry_imgs:
                src = img.get_attribute("src") or img.get_attribute("data-src")
                if not src or "svg" in src.lower() or src in downloaded_urls:
                    continue
                if "heydealer" in src or "cdn." in src or len(src) > 20:
                    if download_image(src, res["model_cd"], img_idx):
                        downloaded_urls.add(src)
                        img_idx += 1
            if img_idx > 1:
                print(f"      📷 재시도로 {img_idx - 1}개 이미지 수집")
        # print(f"      📷 상세 이미지 다운로드 성공: {res['model_cd']} {img_idx - 1}장")
        
        # === 페이지 스크롤 (동적 콘텐츠 로딩) ===
        for i in range(1, 15):
            page.evaluate(f"window.scrollTo(0, {i * 600})")
            time.sleep(0.15)
        
        # === 스펙 영역 로드 대기 (부분 수집 방지) ===
        for _ in range(2):
            try:
                page.wait_for_selector(".css-113wzqa", timeout=12000)
                break
            except Exception:
                page.wait_for_timeout(2000)
        page.wait_for_timeout(500)

        # === 데이터 수집 로직 ===
        option_elements = page.query_selector_all(".css-5pr39e .css-13wylk3, .css-5pr39e .css-1396o7r")
        if option_elements:
            res["options"] = ", ".join([str(opt.inner_text() or "").strip() for opt in option_elements if str(opt.inner_text() or "").strip()])

        containers = page.query_selector_all(".css-1cfq7ri")
        for container in containers:
            if "출고 정보" in container.inner_text():
                info_val = container.query_selector(".css-1n3oo4w")
                if info_val:
                    res["delivery_information"] = info_val.inner_text().replace("\n", " | ").strip()
                    break

        rec_el = page.query_selector(".css-yfldxx")
        if rec_el:
            res["recommendation_comment"] = rec_el.inner_text().replace("\n", " | ").strip()

        def _fill_spec_from_items(items_selector):
            filled = 0
            for item in page.query_selector_all(items_selector):
                lbl_el = item.query_selector(".css-1b7o1k1")
                if not lbl_el:
                    continue
                lbl = lbl_el.inner_text().replace(" ", "").strip()
                val_el = item.query_selector(".css-1b7o1k1 + div")
                if not val_el:
                    try:
                        raw = item.evaluate("""node => {
                            const l = node.querySelector('.css-1b7o1k1');
                            if (!l) return '';
                            const n = l.nextElementSibling;
                            return n ? (n.innerText || n.textContent || '').trim() : '';
                        }""")
                        val = str(raw).strip() if raw is not None else ""
                    except Exception:
                        val = ""
                else:
                    val = str(val_el.inner_text() or "").strip()
                if not val:
                    continue
                if "연식" in lbl and not res["year"]: res["year"] = val; filled += 1
                elif "주행거리" in lbl and not res["km"]: res["km"] = val; filled += 1
                elif "환불" in lbl and not res["refund"]: res["refund"] = val; filled += 1
                elif "헤이딜러보증" in lbl and not res["guarantee"]: res["guarantee"] = val; filled += 1
                elif "사고" in lbl and not res["accident"]: res["accident"] = val; filled += 1
                elif "실내세차" in lbl and not res["inner_car_wash"]: res["inner_car_wash"] = val; filled += 1
                elif "자차보험처리" in lbl and not res["insurance"]: res["insurance"] = val; filled += 1
                elif "외부" in lbl and not res["exterior_description"]: res["exterior_description"] = val; filled += 1
                elif "실내" in lbl and "세차" not in lbl and not res["interior_description"]: res["interior_description"] = val; filled += 1
                elif "타이어" in lbl and not res["tire"]: res["tire"] = val; filled += 1
                elif "틴팅" in lbl and not res["tinting"]: res["tinting"] = val; filled += 1
                elif "차키" in lbl and not res["car_key"]: res["car_key"] = val; filled += 1
            return filled

        _fill_spec_from_items(".css-113wzqa")
        # 스펙이 비었으면 로딩 지연으로 재대기 후 재추출 (최대 2회)
        for _ in range(2):
            if res.get("year") or res.get("km"):
                break
            page.wait_for_timeout(3000 if _ == 0 else 5000)
            for i in range(1, 10):
                page.evaluate(f"window.scrollTo(0, {i * 400})")
                time.sleep(0.2)
            page.wait_for_timeout(1500)
            _fill_spec_from_items(".css-113wzqa")
        
        # 수집 결과
        filled_fields = sum(1 for k, v in res.items() if v and k not in ["model_sn", "model_cd", "detail_url", "date_crtr_pnttm", "create_dt"])
        total_fields = len([k for k in res.keys() if k not in ["model_sn", "model_cd", "detail_url", "date_crtr_pnttm", "create_dt"]])
        # print(f"      📊 데이터 필드: {filled_fields}/{total_fields}개 수집")
        
    except Exception as e:
        print(f"      ❌ 상세 추출 오류: {str(e)[:100]}")
    
    return res

def main():
    brand_map, brand_by_name = load_brand_mapping()
    list_fields = ["model_sn", "brand_id", "brand_name", "model_cd", "model_name", "model_second_name", "grade_name", "car_type", "year", "km", "sale_price", "detail_url", "date_crtr_pnttm", "create_dt"]
    detail_fields = ["model_sn", "brand_id", "brand_name", "model_cd", "model_name", "model_second_name", "grade_name", "year", "km", "refund", "guarantee", "accident", "inner_car_wash", "insurance", "exterior_description", "interior_description", "options", "delivery_information", "recommendation_comment", "tire", "tinting", "car_key", "detail_url", "date_crtr_pnttm", "create_dt"]

    if LIST_FILE.exists(): LIST_FILE.unlink()
    if DETAIL_FILE.exists(): DETAIL_FILE.unlink()

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
        page.wait_for_timeout(700)
        overlay = _get_car_body_overlay()
        car_type_entries = []  # [(인덱스, 차종명), ...]
        try:
            if overlay.count() > 0:
                car_type_labels = _get_car_type_labels_from_overlay(overlay)
                car_type_entries = list(enumerate(car_type_labels))
            if not car_type_entries:
                page.keyboard.press("Escape")
                page.wait_for_timeout(1000)
                car_type_entries = [(0, "")]
            else:
                print(f" 📌 차종(차체) {len(car_type_entries)}개 (텍스트 기준): {[lbl for _, lbl in car_type_entries]}")
                # 차종 목록만 따로 CSV 저장 (car_type_sn, car_type_name)
                with open(CAR_TYPE_LIST_FILE, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.DictWriter(f, fieldnames=["car_type_sn", "car_type_name"])
                    writer.writeheader()
                    for sn, (_, car_type_name) in enumerate(car_type_entries, 1):
                        writer.writerow({"car_type_sn": sn, "car_type_name": car_type_name})
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
        print(f"\n🚀 [2단계] 상세 수집 시작 (총 {len(raw_list)}대)")
        success_count = 0

        # 목록이 비어 있으면 상세 파일은 헤더만 생성 (파일 미생성·0나누기 방지)
        if len(raw_list) == 0:
            with open(DETAIL_FILE, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=detail_fields, extrasaction='ignore')
                writer.writeheader()
            print("   ⚠️ 수집된 목록이 없어 상세 수집을 건너뜁니다.")
        else:
            for idx, item in enumerate(raw_list, 1):
                success = False
                for retry in range(3):
                    try:
                        retry_text = f'재시도({retry})' if retry > 0 else '수집'
                        print(f"\n 🔍 ({idx}/{len(raw_list)}) {retry_text}: {item['model_cd']}")
                        
                        page.goto(item["detail_url"], wait_until="domcontentloaded", timeout=40000)
                        page.wait_for_load_state("load", timeout=15000)
                        page.wait_for_timeout(1500)
                        detail = _extract_detail_smart(page, item)
                        # 스펙이 거의 비었으면 한 번 더 로드 후 재추출 (빈값 행 감소)
                        spec_keys = ("year", "km", "refund", "guarantee", "accident")
                        filled_spec = sum(1 for k in spec_keys if str(detail.get(k) or "").strip())
                        if filled_spec < 2 and retry < 2:
                            page.wait_for_timeout(3000)
                            page.goto(item["detail_url"], wait_until="load", timeout=40000)
                            page.wait_for_timeout(2500)
                            detail = _extract_detail_smart(page, item)
                        # 상세 비어 있으면 목록 값으로 채움 (값은 항상 str로)
                        for k in detail_fields:
                            if k in item and not str(detail.get(k) or "").strip():
                                detail[k] = str(item.get(k) or "").strip()
                        save_to_csv_append(DETAIL_FILE, detail_fields, detail)
                        success = True
                        success_count += 1
                        break
                    except Exception as e:
                        print(f"      ⚠️ 오류: {str(e)[:50]}")
                        if retry < 2:
                            time.sleep(2)
                
                if not success:
                    print(f"      ❌ 최종 실패 (목록 데이터만 저장)")
                    fail_row = {k: str(item.get(k) or "") for k in detail_fields if k in item}
                    for k in detail_fields:
                        if k not in fail_row:
                            fail_row[k] = ""
                    save_to_csv_append(DETAIL_FILE, detail_fields, fail_row)

        print(f"\n📄 상세 CSV 생성 완료: {DETAIL_FILE} ({success_count}건)")
        print(f"\n[{datetime.now()}] ✅ 모든 작업 완료!")
        print(f"   - 목록: {len(raw_list)}개")
        pct = (success_count / len(raw_list) * 100) if raw_list else 0.0
        print(f"   - 상세 성공: {success_count}/{len(raw_list)}개 ({pct:.1f}%)")
        print(f"   - 결과: {RESULT_DIR}")
        _img_today = IMG_BASE / f"{datetime.now().strftime('%Y')}년" / datetime.now().strftime("%Y%m%d")
        print(f"   - 이미지: {_img_today}")
        print(f"   - 로그: {LOG_FILE}")
        
        browser.close()

if __name__ == "__main__":
    main()