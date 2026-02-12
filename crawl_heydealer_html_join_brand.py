#!/usr/bin/env python3
import csv
import time
import requests
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

# --- 설정 ---
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
    """result/heydealer_brands_final.csv에서 브랜드 매핑 데이터 로드"""
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
    """날짜 형식: 8자리, 12자리"""
    now = datetime.now()
    return now.strftime("%Y%m%d"), now.strftime("%Y%m%d%H%M")

def save_to_csv_append(file_path, fieldnames, data_dict):
    """데이터를 한 줄씩 파일 끝에 즉시 추가"""
    file_exists = Path(file_path).exists()
    with open(file_path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        if not file_exists:
            writer.writeheader()
        writer.writerow(data_dict)

def _extract_card_heydealer(elem, idx, brand_map) -> dict:
    """목록 정보 수집 및 지능형 브랜드 매핑 (1차:전체, 2차:띄어쓰기 뒷부분)"""
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
            
            # --- 지능형 브랜드 매핑 ---
            # 1단계: 전체 일치 확인
            matched = brand_map.get(raw_model_name)
            # 2단계: 실패 시 첫 단어(브랜드명) 떼고 비교 (예: '폭스바겐 파사트' -> '파사트')
            if not matched and " " in raw_model_name:
                sub_name = raw_model_name.split(" ", 1)[1].strip()
                matched = brand_map.get(sub_name)
            
            if matched:
                data["brand_id"] = matched["brand_id"]
                data["brand_name"] = matched["brand_name"]

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
    """상세 정보 수집 (라벨 텍스트 매칭: 외부, 실내 등)"""
    res = {
        "model_sn": list_item["model_sn"], "brand_id": list_item["brand_id"], "brand_name": list_item["brand_name"],
        "model_cd": list_item["model_cd"], "model_name": list_item["model_name"],
        "model_second_name": list_item.get("model_second_name", ""), "grade_name": list_item.get("grade_name", ""),
        "year": "", "km": "", "refund": "", "guarantee": "", "accident": "", "inner_car_wash": "", "insurance": "",
        "color_ext": "", "color_int": "", "main_option": "", "delivery_information": "", "rec_reason": "",
        "tire": "", "tinting": "", "car_key": ""
    }
    try:
        page.wait_for_selector(".css-12qft46", timeout=15000)
        # 페이지 내 모든 정보 항목 탐색
        items = page.query_selector_all(".css-113wzqa")
        for item in items:
            lbl_el = item.query_selector(".css-1b7o1k1")
            val_el = item.query_selector(".css-1b7o1k1 + div")
            if lbl_el and val_el:
                lbl, val = lbl_el.inner_text().strip(), val_el.inner_text().strip()
                if "외부" in lbl: res["color_ext"] = val
                elif "실내" in lbl: res["color_int"] = val
                elif "연식" in lbl: res["year"] = val
                elif "주행거리" in lbl: res["km"] = val
                elif "환불" in lbl: res["refund"] = val
                elif "보증" in lbl: res["guarantee"] = val
                elif "사고" in lbl: res["accident"] = val
                elif "세차" in lbl: res["inner_car_wash"] = val
                elif "보험" in lbl: res["insurance"] = val
                elif "타이어" in lbl: res["tire"] = val
                elif "틴팅" in lbl: res["tinting"] = val
                elif "차키" in lbl: res["car_key"] = val

        # 옵션 및 텍스트 데이터 (파이프 처리)
        opt_els = page.query_selector_all(".css-5pr39e .css-13wylk3")
        res["main_option"] = ", ".join([o.inner_text().strip() for o in opt_els])
        
        ship_el = page.query_selector(".css-1cfq7ri .css-1n3oo4w")
        if ship_el: res["delivery_information"] = " | ".join([l.strip() for l in ship_el.inner_text().split('\n') if l.strip()])
        
        rec_el = page.query_selector(".css-isc2b5 .css-yfldxx")
        if rec_el: res["rec_reason"] = " | ".join([l.strip() for l in rec_el.inner_text().split('\n') if l.strip()])
    except: pass
    return res

def main():
    # brand_map = load_brand_mapping()
    
    # with sync_playwright() as p:
    #     browser = p.chromium.launch(headless=False)
    #     context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    #     page = context.new_page()
    brand_map = load_brand_mapping()
    list_fields = ["model_sn", "brand_id", "brand_name", "model_cd", "model_name", "model_second_name", "grade_name", "year", "km", "sale_price", "detail_url", "date_crtr_pnttm", "create_dt"]
    detail_fields = ["model_sn", "brand_id", "brand_name", "model_cd", "model_name", "model_second_name", "grade_name", "year", "km", "refund", "guarantee", "accident", "inner_car_wash", "insurance", "color_ext", "color_int", "main_option", "delivery_information", "rec_reason", "tire", "tinting", "car_key", "detail_url", "date_crtr_pnttm", "create_dt"]

    # 기존 파일이 있다면 삭제 (새로 시작할 때 중복 방지)
    for f in [LIST_FILE, DETAIL_FILE]:
        if f.exists(): f.unlink()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(user_agent="Mozilla/5.0...")
        page = context.new_page()
        
        print("🚀 헤이딜러 전체 목록 수집 시작 (무제한 스크롤)...")
        page.goto(f"{BASE_URL}/market/cars", wait_until="networkidle")
        
        raw_list, seen = [], set()
        
        while True:
            prev_count = len(raw_list)
            
            # 끝까지 스크롤
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2500) # 로딩 대기
            
            # 현재 로드된 카드 수집
            cards = page.query_selector_all('a[href^="/market/cars/"]')
            for card in cards:
                href = card.get_attribute("href").split("?")[0]
                if href not in seen:
                    seen.add(href)
                    item = _extract_card_heydealer(card, len(raw_list) + 1, brand_map)
                    raw_list.append(item)
                    # 목록 즉시 저장
                    save_to_csv_append(LIST_FILE, list_fields, item)

            added = len(raw_list) - prev_count
            print(f" 🔄 수집: {len(raw_list)}대 (신규: {added})")
            
            if added == 0:
                no_new_data_count += 1
                print(f" ⏳ 추가 없음 ({no_new_data_count}/3)")
            else:
                no_new_data_count = 0
            
            if no_new_data_count >= 3: break

        # 2. 상세 수집 및 실시간 저장
        print(f"\n🚀 [상세 수집 시작] 총 {len(raw_list)}대 대상")
        for idx, item in enumerate(raw_list, 1):
            print(f" 🔍 ({idx}/{len(raw_list)}) 상세: {item['model_cd']}")
            try:
                page.goto(item["detail_url"], wait_until="networkidle", timeout=40000)
                time.sleep(1.2)
                detail = _extract_detail_smart(page, item)
                detail.update({"detail_url": item["detail_url"], "date_crtr_pnttm": item["date_crtr_pnttm"], "create_dt": item["create_dt"]})
                # 상세 즉시 저장
                save_to_csv_append(DETAIL_FILE, detail_fields, detail)
            except: pass

        print(f"✅ 완료! 파일 위치: {RESULT_DIR}")
        browser.close()

if __name__ == "__main__":
    main()
            
#             current_count = len(raw_list)
#             print(f" 🔄 수집 현황: {current_count}대 (추가됨: {current_count - prev_count})")
            
#             # 종료 조건: 스크롤 후에도 개수가 늘지 않으면 종료
#             if current_count == prev_count:
#                 print(" ⏳ 마지막 확인 중...")
#                 page.wait_for_timeout(4000)
#                 final_cards = page.query_selector_all('a[href^="/market/cars/"]')
#                 if len(final_cards) <= current_count:
#                     print("✅ 모든 차량 목록 로드 완료.")
#                     break
        
#         # [1] 목록 저장
#         list_fields = ["model_sn", "brand_id", "brand_name", "model_cd", "model_name", "model_second_name", "grade_name", "year", "km", "sale_price", "detail_url", "date_crtr_pnttm", "create_dt"]
#         with open(RESULT_DIR / "heydealer_list.csv", "w", newline="", encoding="utf-8-sig") as f:
#             writer = csv.DictWriter(f, fieldnames=list_fields, extrasaction='ignore')
#             writer.writeheader()
#             writer.writerows(raw_list)
#         print(f"📂 목록 저장 완료: {len(raw_list)}대")

#         # [2] 상세 페이지 수집
#         detail_results = []
#         detail_fields = ["model_sn", "brand_id", "brand_name", "model_cd", "model_name", "model_second_name", "grade_name", "year", "km", "refund", "guarantee", "accident", "inner_car_wash", "insurance", "color_ext", "color_int", "main_option", "delivery_information", "rec_reason", "tire", "tinting", "car_key", "detail_url", "date_crtr_pnttm", "create_dt"]

#         for idx, item in enumerate(raw_list, 1):
#             print(f"🔍 상세 수집 중 ({idx}/{len(raw_list)}): {item['model_cd']}")
#             try:
#                 page.goto(item["detail_url"], wait_until="networkidle", timeout=40000)
#                 time.sleep(1.5) # 과부하 방지
#                 detail = _extract_detail_smart(page, item)
#                 detail.update({"detail_url": item["detail_url"], "date_crtr_pnttm": item["date_crtr_pnttm"], "create_dt": item["create_dt"]})
#                 detail_results.append(detail)
#             except Exception as e:
#                 print(f" ⚠️ {item['model_cd']} 수집 실패: {e}")

#         with open(RESULT_DIR / "heydealer_detail.csv", "w", newline="", encoding="utf-8-sig") as f:
#             writer = csv.DictWriter(f, fieldnames=detail_fields, extrasaction='ignore')
#             writer.writeheader()
#             writer.writerows(detail_results)
        
#         print("✅ 모든 데이터 수집 및 매핑 완료")
#         browser.close()

# if __name__ == "__main__":
#     main()