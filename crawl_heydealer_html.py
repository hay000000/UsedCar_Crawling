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

# --- [1] 목록 카드 추출 (List용) ---
def _extract_card_heydealer(elem, base: str) -> dict:
    data = {}
    # 모델명/등급
    model_box = elem.query_selector(".css-9j6363")
    if model_box:
        names = model_box.query_selector_all(".css-jk6asd")
        data["model_name"] = names[0].inner_text().strip() if len(names) > 0 else ""
        data["model_second_name"] = names[1].inner_text().strip() if len(names) > 1 else ""
        grade = model_box.query_selector(".css-13wylk3")
        data["grade_name"] = grade.inner_text().strip() if grade else ""
    
    # 연식/주행거리
    yk_el = elem.query_selector(".css-6bza35")
    if yk_el:
        txt = yk_el.inner_text().strip()
        if "ㆍ" in txt:
            p = txt.split("ㆍ")
            data["year"], data["km"] = p[0].strip(), p[1].strip()
        else:
            data["year"], data["km"] = txt, ""

    # 가격 및 사고/보험
    p_box = elem.query_selector(".css-dbu2tk")
    if p_box:
        before = p_box.query_selector(".css-ja3yiu")
        data["before_sale"] = before.inner_text().strip() if before else ""
        sale = p_box.query_selector(".css-8sjynn")
        data["sale_price"] = sale.inner_text().strip() if sale else p_box.inner_text().strip()

    nc_el = elem.query_selector(".css-o11ltr")
    data["new_car_price"] = nc_el.inner_text().strip() if nc_el else ""

    l_box = elem.query_selector(".css-14xsjnu")
    if l_box:
        ls = l_box.query_selector_all(".css-nzdaom")
        data["accident"] = ls[0].inner_text().strip() if len(ls) > 0 else ""
        data["insurance"] = ls[1].inner_text().strip() if len(ls) > 1 else ""

    href = elem.get_attribute("href") or ""
    data["url"] = href if href.startswith("http") else (base.rstrip("/") + "/" + href.lstrip("/"))
    return data

# --- [2] 상세 페이지 추출 (Detail용) ---
def _extract_detail_heydealer(page, detail_url: str) -> dict:
    out = {"model_name": "", "grade_name": "", "specs": {}, "images_all": ""}
    try:
        # 1. 상세 페이지의 핵심 컨테이너가 나타날 때까지 대기 (가장 중요)
        # 하단 스펙 영역(css-5pr39e)이 로드될 때까지 기다립니다.
        page.wait_for_selector(".css-5pr39e", timeout=10000)
        time.sleep(1.5) # 레이아웃이 완전히 잡히도록 추가 대기

        # 2. 모델명/등급 추출
        top = page.query_selector(".css-1uus6sd .css-12qft46 .css-ltrevz .css-1m93hu5 .css-105xtr1")
        if top:
            m = top.query_selector(".css-1ugrlhy")
            g = top.query_selector(".css-pjgjzs")
            out["model_name"] = m.inner_text().strip() if m else ""
            out["grade_name"] = g.inner_text().strip() if g else ""

        # 3. 7가지 스펙 추출 (순서 기반)
        spec_cols = ["year", "km", "refund", "guarantee", "accident", "inner_car_wash", "insurance"]
        # 요청하신 정확한 경로로 유닛들 수집
        units = page.query_selector_all(".css-5pr39e .css-154rxsx .css-21wmfe .css-113wzqa")
        
        for i, unit in enumerate(units):
            if i < len(spec_cols):
                label_el = unit.query_selector(".css-1b7o1k1")
                if label_el:
                    # 레이블 옆의 텍스트(값)를 가져오는 JS 실행
                    val = label_el.evaluate("node => { \
                        const next = node.nextElementSibling; \
                        return next ? next.innerText : ''; \
                    }").strip()
                    out["specs"][spec_cols[i]] = val

        # 4. 이미지 추출
        imgs = [img.get_attribute("src") for img in page.query_selector_all("img[src*='heydealer.com']") 
                if img.get_attribute("src") and ("original" in img.get_attribute("src") or "images" in img.get_attribute("src"))]
        out["images_all"] = "|".join(list(dict.fromkeys(imgs)))

    except Exception as e:
        print(f"      [상세 추출 실패] {detail_url}: {e}")
    
    return out

# --- [3] 실행 로직 ---
def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()
        
        print(f"1. 목록 수집 시작 ({TEST_URL})")
        page.goto(TEST_URL, wait_until="domcontentloaded")
        for _ in range(2): # 스크롤
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)
        
        links = page.query_selector_all('a[href^="/market/cars/"]')
        raw_cars, seen, base_url = [], set(), "https://www.heydealer.com"
        
        for elem in links:
            href = elem.get_attribute("href") or ""
            key = href.split("?")[0]
            if key and key not in seen and "/market/cars/" in key and key != "/market/cars":
                seen.add(key)
                raw_cars.append(_extract_card_heydealer(elem, base_url))
            if len(raw_cars) >= TEST_MAX_CARS: break

        # List CSV 저장
        today = datetime.now().strftime("%Y%m%d")
        list_fields = ["car_sn", "used_car_site", "model_name", "model_second_name", "grade_name", "year", "km", "before_sale", "sale_price", "new_car_price", "accident", "insurance", "detail_url", "data_crtr_pnttm"]
        with open(OUTPUT_DIR / "heydealer_cars_list.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list_fields)
            writer.writeheader()
            for i, c in enumerate(raw_cars, 1):
                c.update({"car_sn": i, "used_car_site": "헤이딜러", "data_crtr_pnttm": today, "detail_url": c["url"]})
                writer.writerow({k: c.get(k, "") for k in list_fields})

        print(f"2. 상세 수집 시작 (총 {len(raw_cars)}대)")
        detail_fields = ["sn", "car_sn", "used_car_site", "model_name", "grade_name", "image_video", "images_all", "year", "km", "refund", "guarantee", "accident", "inner_car_wash", "insurance", "price", "new_car_price"]
        with open(OUTPUT_DIR / "heydealer_cars_detail.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=detail_fields)
            writer.writeheader()
            for i, c in enumerate(raw_cars, 1):
                print(f"   [{i}/{len(raw_cars)}] 접속 시도: {c['url']}")
                try:
                    # 상세 페이지 접속 시 타임아웃 20초로 제한 및 domcontentloaded 사용
                    page.goto(c["url"], wait_until="domcontentloaded", timeout=20000)
                    det = _extract_detail_heydealer(page, c["url"])
                    
                    row = {
                        "sn": i, "car_sn": i, "used_car_site": "헤이딜러",
                        "model_name": det["model_name"] or c["model_name"],
                        "grade_name": det["grade_name"] or c["grade_name"],
                        "image_video": "", "images_all": det["images_all"],
                        "price": c["sale_price"], "new_car_price": c["new_car_price"]
                    }
                    for col in ["year", "km", "refund", "guarantee", "accident", "inner_car_wash", "insurance"]:
                        row[col] = det["specs"].get(col, "")
                    writer.writerow(row)
                except Exception as e:
                    print(f"   [!] 상세 페이지 접속 실패(건너뜀): {e}")

        browser.close()
        print(f"수집 완료: {OUTPUT_DIR} 확인")

if __name__ == "__main__":
    main()