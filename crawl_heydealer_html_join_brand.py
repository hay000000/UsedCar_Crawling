#!/usr/bin/env python3
import csv
import time
import requests
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

# --- 설정 ---
TEST_LIMIT = 10 
BASE_URL = "https://www.heydealer.com"
BASE_DIR = Path(__file__).resolve().parent
RESULT_DIR = BASE_DIR / "result"
IMG_DIR = BASE_DIR / "image" / "heydealer"

RESULT_DIR.mkdir(parents=True, exist_ok=True)
IMG_DIR.mkdir(parents=True, exist_ok=True)

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
        print(f"⚠️ 매핑 파일 없음: {brand_file}")
    return brand_map

def get_now_times():
    now = datetime.now()
    return now.strftime("%Y%m%d"), now.strftime("%Y%m%d%H%M")

def _extract_card_heydealer(elem, idx, brand_map) -> dict:
    """목록 정보 수집 및 지능형 브랜드 매핑"""
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
            
            # --- [지능형 브랜드 매핑 시작] ---
            # 1단계: 전체 일치 확인 (예: "폭스바겐 파사트GT(B8)" 가 통째로 있는지)
            matched_brand = brand_map.get(raw_model_name)
            
            # 2단계: 일치하는 게 없으면 첫 단어(브랜드명) 떼고 비교
            if not matched_brand and " " in raw_model_name:
                # "폭스바겐 파사트GT(B8)" -> ["폭스바겐", "파사트GT(B8)"] -> "파사트GT(B8)"
                split_name = raw_model_name.split(" ", 1)[1].strip() 
                matched_brand = brand_map.get(split_name)
            
            if matched_brand:
                data["brand_id"] = matched_brand["brand_id"]
                data["brand_name"] = matched_brand["brand_name"]
            # --- [지능형 브랜드 매핑 종료] ---

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
    """상세 정보 수집 (외부/실내 매칭 보강)"""
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
                elif "보험" in lbl: res["insurance"] = val
                elif "타이어" in lbl: res["tire"] = val
                elif "틴팅" in lbl: res["tinting"] = val
                elif "차키" in lbl: res["car_key"] = val

        opt_els = page.query_selector_all(".css-5pr39e .css-13wylk3")
        res["main_option"] = ", ".join([o.inner_text().strip() for o in opt_els])
        ship_el = page.query_selector(".css-1cfq7ri .css-1n3oo4w")
        if ship_el: res["delivery_information"] = " | ".join([l.strip() for l in ship_el.inner_text().split('\n') if l.strip()])
        rec_el = page.query_selector(".css-isc2b5 .css-yfldxx")
        if rec_el: res["rec_reason"] = " | ".join([l.strip() for l in rec_el.inner_text().split('\n') if l.strip()])
    except: pass
    return res

def main():
    brand_map = load_brand_mapping()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(user_agent="Mozilla/5.0...")
        page = context.new_page()
        
        print(f"🚀 {TEST_LIMIT}개 테스트 수집 시작...")
        page.goto(f"{BASE_URL}/market/cars", wait_until="networkidle")
        
        raw_list, seen = [], set()
        while len(raw_list) < TEST_LIMIT:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            cards = page.query_selector_all('a[href^="/market/cars/"]')
            for card in cards:
                href = card.get_attribute("href").split("?")[0]
                if href not in seen:
                    seen.add(href)
                    raw_list.append(_extract_card_heydealer(card, len(raw_list) + 1, brand_map))
                    if len(raw_list) >= TEST_LIMIT: break
            print(f" 현재 {len(raw_list)}개 확보 중...")

        # 목록 저장
        list_fields = ["model_sn", "brand_id", "brand_name", "model_cd", "model_name", "model_second_name", "grade_name", "year", "km", "sale_price", "detail_url", "date_crtr_pnttm", "create_dt"]
        with open(RESULT_DIR / "heydealer_list.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list_fields, extrasaction='ignore')
            writer.writeheader(); writer.writerows(raw_list)

        # 상세 수집
        detail_results = []
        for item in raw_list:
            print(f"🔍 상세: {item['model_cd']}")
            try:
                page.goto(item["detail_url"], wait_until="networkidle", timeout=40000)
                detail = _extract_detail_smart(page, item)
                detail.update({"detail_url": item["detail_url"], "date_crtr_pnttm": item["date_crtr_pnttm"], "create_dt": item["create_dt"]})
                detail_results.append(detail)
            except: pass

        detail_fields = ["model_sn", "brand_id", "brand_name", "model_cd", "model_name", "model_second_name", "grade_name", "year", "km", "refund", "guarantee", "accident", "inner_car_wash", "insurance", "color_ext", "color_int", "main_option", "delivery_information", "rec_reason", "tire", "tinting", "car_key", "detail_url", "date_crtr_pnttm", "create_dt"]
        with open(RESULT_DIR / "heydealer_detail.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=detail_fields, extrasaction='ignore')
            writer.writeheader(); writer.writerows(detail_results)
        
        print("✅ 10개 테스트 완료.")
        browser.close()

if __name__ == "__main__":
    main()