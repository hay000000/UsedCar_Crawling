#!/usr/bin/env python3
import csv
import time
import requests
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

# --- 설정 ---
TARGET_COUNT = 100 
BASE_URL = "https://www.heydealer.com"
BASE_DIR = Path(__file__).resolve().parent
RESULT_DIR = BASE_DIR / "result"
IMG_DIR = BASE_DIR / "image" / "heydealer"

# 폴더 생성
RESULT_DIR.mkdir(parents=True, exist_ok=True)
IMG_DIR.mkdir(parents=True, exist_ok=True)
LIST_FILE = RESULT_DIR / "heydealer_list.csv"
DETAIL_FILE = RESULT_DIR / "heydealer_detail.csv"

def load_brand_mapping():
    brand_map = {}
    brand_file = RESULT_DIR / "heydealer_brands_final.csv"
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
    try:
        if not img_url or "svg" in img_url: return
        response = requests.get(img_url, stream=True, timeout=10)
        if response.status_code == 200:
            ext = img_url.split('.')[-1].split('?')[0]
            if len(ext) > 4: ext = "jpg" 
            filename = f"{model_cd}_{idx}.{ext}"
            save_path = IMG_DIR / filename
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
    except: pass

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
    res = {
        "model_sn": list_item.get("model_sn", ""),
        "brand_id": list_item.get("brand_id", ""),
        "brand_name": list_item.get("brand_name", ""),
        "model_cd": list_item.get("model_cd", ""),
        "model_name": list_item.get("model_name", ""),
        "model_second_name": list_item.get("model_second_name", ""),
        "grade_name": list_item.get("grade_name", ""),
        "year": list_item.get("year", ""),
        "km": list_item.get("km", ""),
        "refund": "", "guarantee": "", "accident": "", 
        "inner_car_wash": "", "insurance": "", "exterior_description": "", "interior_description": "", 
        "options": "", "delivery_information": "", "recommendation_comment": "",
        "tire": "", "tinting": "", "car_key": "",
        "detail_url": list_item["detail_url"],
        "date_crtr_pnttm": list_item["date_crtr_pnttm"],
        "create_dt": list_item["create_dt"]
    }

    try:
        # 1. 첫 번째 데이터 유실 방지: 요소 로딩을 넉넉하게 대기 (최대 20초)
        page.wait_for_selector(".css-12qft46", timeout=20000)
        
        # 2. 동적 로딩 대응: 페이지 끝까지 세밀하게 스크롤
        for i in range(1, 15):
            page.evaluate(f"window.scrollTo(0, {i * 600})")
            time.sleep(0.2)

        # 3. 주요 옵션 (options) 추출 - 주신 HTML 구조 반영
        # '주요 옵션' 타이틀 아래의 옵션 태그들(.css-13wylk3, .css-1396o7r) 싹다 긁기
        option_elements = page.query_selector_all(".css-5pr39e .css-13wylk3, .css-5pr39e .css-1396o7r")
        if option_elements:
            res["options"] = ", ".join([opt.inner_text().strip() for opt in option_elements if opt.inner_text().strip()])

        # 4. 출고 정보 (delivery_information) 추출
        # 브랜드명에 관계없이 "출고 정보" 글자가 있는 박스를 찾음
        delivery_containers = page.query_selector_all(".css-1cfq7ri")
        for container in delivery_containers:
            label_text = container.inner_text()
            if "출고 정보" in label_text:
                info_val = container.query_selector(".css-1n3oo4w")
                if info_val:
                    # 줄바꿈을 | 로 바꾸어 엑셀 한 셀에 예쁘게 들어가도록 처리
                    res["delivery_information"] = info_val.inner_text().replace("\n", " | ").strip()
                    break # 찾았으면 루프 종료

        # 5. 추천하는 이유 (recommendation_comment)
        rec_el = page.query_selector(".css-yfldxx")
        if rec_el:
            res["recommendation_comment"] = rec_el.inner_text().replace("\n", " | ").strip()

        # 6. 상세 표 항목 스캔 (연식, 주행거리, 환불, 헤이딜러 보증, 사고, 실내 세차, 자차 보험처리 등)
        items = page.query_selector_all(".css-113wzqa")
        for item in items:
            lbl_el = item.query_selector(".css-1b7o1k1")
            val_el = item.query_selector(".css-1b7o1k1 + div")
            
            if lbl_el and val_el:
                # [필승 매칭] 라벨의 모든 공백을 제거하고 대조 (예: '헤이딜러 보증' -> '헤이딜러보증')
                lbl = lbl_el.inner_text().replace(" ", "").strip()
                val = val_el.inner_text().strip()
                
                if not val: continue

                if "연식" in lbl: res["year"] = val
                elif "주행거리" in lbl: res["km"] = val
                elif "환불" in lbl: res["refund"] = val
                elif "헤이딜러보증" in lbl: res["guarantee"] = val # 공백제거 매칭
                elif "사고" in lbl: res["accident"] = val
                elif "실내세차" in lbl: res["inner_car_wash"] = val
                elif "자차보험처리" in lbl: res["insurance"] = val # 공백제거 매칭
                elif "타이어" in lbl: res["tire"] = val
                elif "틴팅" in lbl: res["tinting"] = val
                elif "차키" in lbl: res["car_key"] = val
                elif "외부" in lbl: res["exterior_description"] = val
                elif "실내" in lbl and "세차" not in lbl: res["interior_description"] = val

        # 7. model_name 누락 방지 (상단 타이틀 긁기)
        if not res["model_name"]:
            title_el = page.query_selector(".css-12qft46")
            if title_el:
                res["model_name"] = title_el.inner_text().split('\n')[0].strip()

    except Exception as e:
        print(f"      ❌ {list_item.get('model_cd')} 수집 실패: {e}")

    return res

def main():
    brand_map = load_brand_mapping()
    list_fields = ["model_sn", "brand_id", "brand_name", "model_cd", "model_name", "model_second_name", "grade_name", "year", "km", "sale_price", "detail_url", "date_crtr_pnttm", "create_dt"]
    detail_fields = ["model_sn", "brand_id", "brand_name", "model_cd", "model_name", "model_second_name", "grade_name", "year", "km", "refund", "guarantee", "accident", "inner_car_wash", "insurance", "exterior_description", "interior_description", "options", "delivery_information", "recommendation_comment", "tire", "tinting", "car_key", "detail_url", "date_crtr_pnttm", "create_dt"]

    for f in [LIST_FILE, DETAIL_FILE]:
        if f.exists(): f.unlink()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        page = context.new_page()
        # 봇 감지 우회 스크립트
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        print(f"🚀 [1단계] 목록 접속 시도...")
        success_list_page = False
        for retry in range(3):
            try:
                page.goto(f"{BASE_URL}/market/cars", wait_until="domcontentloaded", timeout=40000)
                page.wait_for_timeout(3000) # 안정적인 로딩 대기
                success_list_page = True
                break
            except Exception as e:
                print(f"⚠️ 목록 접속 실패 ({retry+1}/3): {e}")
                time.sleep(3)
        
        if not success_list_page:
            print("❌ 목록 페이지 접속에 최종 실패했습니다.")
            return

        raw_list, seen = [], set()
        while len(raw_list) < TARGET_COUNT:
            prev_count = len(raw_list)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            
            cards = page.query_selector_all('a[href^="/market/cars/"]')
            for card in cards:
                href = card.get_attribute("href").split("?")[0]
                if href not in seen:
                    seen.add(href)
                    item = _extract_card_heydealer(card, len(raw_list) + 1, brand_map)
                    raw_list.append(item)
                    save_to_csv_append(LIST_FILE, list_fields, item)
                    if len(raw_list) >= TARGET_COUNT: break
            
            if len(raw_list) == prev_count: break # 더 이상 로드 안됨
            print(f" 🔄 목록 수집 중: {len(raw_list)}/{TARGET_COUNT}")

        print(f"\n🚀 [2단계] 상세 수집 시작 (총 {len(raw_list)}대)")
        for idx, item in enumerate(raw_list, 1):
            success = False
            for retry in range(2): 
                try:
                    print(f" 🔍 ({idx}/{len(raw_list)}) {'상세' if retry==0 else '재시도'}: {item['model_cd']}")
                    page.goto(item["detail_url"], wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(1500)
                    
                    detail = _extract_detail_smart(page, item)
                    save_to_csv_append(DETAIL_FILE, detail_fields, detail)
                    success = True
                    break
                except:
                    time.sleep(2)
            
            if not success:
                save_to_csv_append(DETAIL_FILE, detail_fields, {"model_sn": item["model_sn"], "model_cd": item["model_cd"], "detail_url": item["detail_url"]})

        print(f"✅ 수집 완료!")
        browser.close()

if __name__ == "__main__":
    main()