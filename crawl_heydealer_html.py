#!/usr/bin/env python3
import csv
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, Error

# --- 설정 ---
TEST_URL = "https://www.heydealer.com/market/cars"
TEST_MAX_CARS = 10 
OUTPUT_DIR = Path(r"/home/limhayoung/used_car_crawler/result")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True) 

# --- 상세 스펙 레이블 (detail용) ---
HEYDEALER_SPEC_LABEL_TO_COLUMN = {
    "연식": "year",
    "주행거리": "km",
    "환불": "refund",
    "헤이딜러 보증": "guarantee",
    "사고": "accident",
    "실내 세차": "inner_car_wash",
    "자차 보험처리": "insurance"
}

def _extract_card_heydealer(elem, base: str) -> dict:
    """[요청사항 반영] 목록 카드에서 세부 클래스별 데이터 추출"""
    data = {}

    # 1. 모델명/등급 (css-9j6363)
    model_box = elem.query_selector(".css-9j6363")
    if model_box:
        names = model_box.query_selector_all(".css-jk6asd")
        data["model_name"] = names[0].inner_text().strip() if len(names) > 0 else ""
        data["model_second_name"] = names[1].inner_text().strip() if len(names) > 1 else ""
        
        grade = model_box.query_selector(".css-13wylk3")
        data["grade_name"] = grade.inner_text().strip() if grade else ""
    else:
        data["model_name"] = data["model_second_name"] = data["grade_name"] = ""

    # 2. 연식/주행거리 (css-6bza35)
    year_km_el = elem.query_selector(".css-6bza35")
    if year_km_el:
        txt = year_km_el.inner_text().strip()
        if "ㆍ" in txt:
            parts = txt.split("ㆍ")
            data["year"] = parts[0].strip()
            data["km"] = parts[1].strip()
        else:
            data["year"], data["km"] = txt, ""
    else:
        data["year"] = data["km"] = ""

    # 3. 가격 (css-105xtr1 > css-1066lcq > css-dbu2tk)
    price_box = elem.query_selector(".css-dbu2tk")
    if price_box:
        before = price_box.query_selector(".css-ja3yiu")
        data["before_sale"] = before.inner_text().strip() if before else ""
        
        sale = price_box.query_selector(".css-8sjynn")
        if sale:
            data["sale_price"] = sale.inner_text().strip()
        else:
            data["sale_price"] = price_box.inner_text().strip()
    else:
        data["before_sale"] = data["sale_price"] = ""

    # 4. 신차 가격 (css-o11ltr)
    new_car = elem.query_selector(".css-o11ltr")
    data["new_car_price"] = new_car.inner_text().strip() if new_car else ""

    # 5. 사고/보험 (css-14xsjnu > css-nzdaom)
    label_box = elem.query_selector(".css-14xsjnu")
    if label_box:
        labels = label_box.query_selector_all(".css-nzdaom")
        data["accident"] = labels[0].inner_text().strip() if len(labels) > 0 else ""
        data["insurance"] = labels[1].inner_text().strip() if len(labels) > 1 else ""
    else:
        data["accident"] = data["insurance"] = ""

    # URL
    href = elem.get_attribute("href") or ""
    data["url"] = href if href.startswith("http") else (base.rstrip("/") + "/" + href.lstrip("/"))
    return data

def scroll_page(page, max_cars):
    """안전한 스크롤 및 카운팅 로직"""
    last_count = 0
    for _ in range(10): # 최대 10번 스크롤 시도
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000) # 로딩 대기
            
            # 현재 수집된 링크 수 확인
            links = page.query_selector_all('a[href^="/market/cars/"]')
            current_count = len(links)
            if current_count >= max_cars: break
            if current_count == last_count: break
            last_count = current_count
        except Error:
            # 컨텍스트 파괴 시 대기 후 재시도
            page.wait_for_timeout(2000)
            continue

def crawl_all_pages(target_url, max_cars):
    all_cars = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()
        
        # 페이지 접속 및 안정화 대기
        page.goto(target_url, wait_until="networkidle")
        scroll_page(page, max_cars)
        
        parsed = urlparse(target_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        
        links = page.query_selector_all('a[href^="/market/cars/"]')
        seen = set()
        for elem in links:
            href = elem.get_attribute("href") or ""
            key = href.split("?")[0]
            if key and key not in seen and "/market/cars/" in key:
                if key == "/market/cars": continue
                seen.add(key)
                all_cars.append(_extract_card_heydealer(elem, base))
            if len(all_cars) >= max_cars: break
            
        browser.close()
    return all_cars

def save_list_to_csv(cars, path):
    """최종 규격 반영 CSV 저장"""
    fields = [
        "car_sn", "used_car_site", "model_name", "model_second_name", "grade_name", 
        "year", "km", "before_sale", "sale_price", "new_car_price", 
        "accident", "insurance", "detail_url", "data_crtr_pnttm"
    ]
    base_date = datetime.now().strftime("%Y%m%d")
    
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for i, car in enumerate(cars, 1):
            row = {f: car.get(f, "") for f in fields}
            row.update({
                "car_sn": i,
                "used_car_site": "헤이딜러",
                "detail_url": car.get("url"),
                "data_crtr_pnttm": base_date
            })
            writer.writerow(row)

def main():
    print("목록 수집을 시작합니다...")
    try:
        cars = crawl_all_pages(TEST_URL, TEST_MAX_CARS)
        if cars:
            list_path = OUTPUT_DIR / "heydealer_cars_list.csv"
            save_list_to_csv(cars, list_path)
            print(f"성공: {len(cars)}대의 차량을 수집하여 {list_path}에 저장했습니다.")
        else:
            print("수집된 데이터가 없습니다.")
    except Exception as e:
        print(f"실행 중 오류 발생: {e}")

if __name__ == "__main__":
    main()