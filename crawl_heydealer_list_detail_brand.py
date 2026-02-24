#!/usr/bin/env python3
import csv
import time
import requests
import sys
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

# --- 설정 및 경로 ---
# [특정 개수만 수집할 때] 아래 주석 해제 후 사용
TARGET_COUNT = 10

BASE_URL = "https://www.heydealer.com"
BASE_DIR = Path(__file__).resolve().parent

# 폴더 경로 설정
RESULT_DIR = BASE_DIR / "result" / "heydealer"
LOG_DIR = BASE_DIR / "logs" / "heydealer"
IMG_DIR = BASE_DIR / "imgs" / "heydealer"

# 폴더 생성
RESULT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
IMG_DIR.mkdir(parents=True, exist_ok=True)

# 파일 경로
LIST_FILE = RESULT_DIR / "heydealer_list.csv"
DETAIL_FILE = RESULT_DIR / "heydealer_detail.csv"

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

print(f"[{datetime.now()}] 🏁 헤이딜러 수집 프로그램 시작")
print(f"📁 이미지 저장 경로: {IMG_DIR}")

def load_brand_mapping():
    brand_map = {}
    brand_file = BASE_DIR / "result" / "heydealer_brands_final.csv"
    if brand_file.exists():
        with open(brand_file, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                brand_map[row['model_name'].strip()] = {
                    "brand_id": row.get('brand_id', ''),
                    "brand_name": row.get('brand_name', '')
                }
    else:
        print(f"⚠️ 매핑 파일이 없습니다: {brand_file}")
    return brand_map

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
    """이미지 다운로드 함수"""
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
            
            filename = f"{model_cd}_{idx}.{ext}"
            save_path = IMG_DIR / filename
            
            with open(save_path, "wb") as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            return True
        else:
            return False
            
    except Exception as e:
        return False

def _extract_card_heydealer(elem, idx, brand_map) -> dict:
    data = {"model_sn": idx, "brand_id": "", "brand_name": ""}
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
        
        print(f"      📸 이미지 수집 시작: {res['model_cd']}")
        
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
        print(f"      📷 상세 이미지 다운로드 성공: {res['model_cd']} {img_idx - 1}장")
        
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
    brand_map = load_brand_mapping()
    list_fields = ["model_sn", "brand_id", "brand_name", "model_cd", "model_name", "model_second_name", "grade_name", "year", "km", "sale_price", "detail_url", "date_crtr_pnttm", "create_dt"]
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
        
        # [TARGET_COUNT 사용 시] 
        print(f"\n🚀 [1단계] 목록 수집 시작 (목표: {TARGET_COUNT}개)")
        # print(f"\n🚀 [1단계] 목록 수집 시작 (끝까지 스크롤)")
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

        raw_list, seen = [], set()
        prev_count = 0
        no_new_rounds = 0

        # 무한 스크롤: 더 이상 새 매물이 안 나올 때까지
        while True:
            # [TARGET_COUNT 사용 시] 아래 주석 해제
            if len(raw_list) >= TARGET_COUNT: # TARGET_COUNT 달성 시 종료
                print(f" ✅ 목표 달성: {TARGET_COUNT}개 수집 완료")
                break   # TARGET_COUNT 종료 조건 추가

            last_height = page.evaluate("document.body.scrollHeight")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2500)

            cards = page.query_selector_all('a[href^="/market/cars/"]')
            for card in cards:
                # [TARGET_COUNT 사용 시] 아래 주석 해제
                if len(raw_list) >= TARGET_COUNT: # TARGET_COUNT 달성 시 종료
                    break   # TARGET_COUNT 종료 조건 추가

                href = (card.get_attribute("href") or "").split("?")[0]
                if href and href not in seen:
                    seen.add(href)
                    item = _extract_card_heydealer(card, len(raw_list) + 1, brand_map)
                    raw_list.append(item)
                    save_to_csv_append(LIST_FILE, list_fields, item)

            # 새로 추가된 매물 없으면 카운트
            if len(raw_list) == prev_count:
                no_new_rounds += 1
            else:
                no_new_rounds = 0
            prev_count = len(raw_list)

            # [TARGET_COUNT 사용 시] 아래를 len(raw_list)/TARGET_COUNT 대 로 변경
            print(f" 🔄 목록 수집: {len(raw_list)}/{TARGET_COUNT}대")   # TARGET_COUNT 추가
            # print(f" 🔄 목록 수집: {len(raw_list)}대")
# 

            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                page.wait_for_timeout(2000)
                if page.evaluate("document.body.scrollHeight") == last_height:
                    print(f"🏁 페이지 끝 도달 (총 {len(raw_list)}대)")
                    break
            else:
                no_new_rounds = 0
            # 더 이상 새 매물이 안 나와도 종료 (스크롤은 되지만 새 카드 없음)
            if no_new_rounds >= 2:
                print(f"🏁 새 매물 없음, 수집 종료 (총 {len(raw_list)}대)")
                break

        print(f"\n📄 목록 CSV 생성 완료: {LIST_FILE} ({len(raw_list)}건)")
        print(f"\n🚀 [2단계] 상세 수집 시작 (총 {len(raw_list)}대)")
        success_count = 0
        
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
        print(f"   - 상세 성공: {success_count}/{len(raw_list)}개 ({success_count/len(raw_list)*100:.1f}%)")
        print(f"   - 결과: {RESULT_DIR}")
        print(f"   - 이미지: {IMG_DIR}")
        print(f"   - 로그: {LOG_FILE}")
        
        browser.close()

if __name__ == "__main__":
    main()