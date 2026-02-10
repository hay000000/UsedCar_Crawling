#!/usr/bin/env python3
import csv
import time
import random
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

# --- 설정 ---
TEST_LIMIT = 10 
BASE_URL = "https://www.heydealer.com"
BASE_DIR = Path(__file__).resolve().parent
RESULT_DIR = BASE_DIR / "result"
LOG_DIR = BASE_DIR / "logs" / "heydealer"

RESULT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

def write_log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(msg)
    log_file = LOG_DIR / f"heydealer_log_{datetime.now().strftime('%Y%m%d')}.csv"
    with open(log_file, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, msg])

def _extract_card_heydealer(elem, base: str) -> dict:
    """목록 페이지 정보 추출 (기본 정보 및 가격)"""
    data = {
        "model_name": "", "model_second_name": "", "grade_name": "", 
        "year": "", "km": "", "before_sale": "", "sale_price": "", "new_car_price": "", "url": ""
    }
    try:
        model_box = elem.query_selector(".css-9j6363")
        if model_box:
            names = model_box.query_selector_all(".css-jk6asd")
            data["model_name"] = names[0].inner_text().strip() if len(names) > 0 else ""
            data["model_second_name"] = names[1].inner_text().strip() if len(names) > 1 else ""
            grade = model_box.query_selector(".css-13wylk3")
            data["grade_name"] = grade.inner_text().strip() if grade else ""
        
        yk_el = elem.query_selector(".css-6bza35")
        if yk_el:
            txt = yk_el.inner_text().strip()
            if "ㆍ" in txt:
                p = txt.split("ㆍ")
                data["year"], data["km"] = p[0].strip(), p[1].strip()
            else: data["year"] = txt

        p_box = elem.query_selector(".css-dbu2tk")
        if p_box:
            before = p_box.query_selector(".css-ja3yiu")
            actual = p_box.query_selector(".css-8sjynn")
            data["before_sale"] = before.inner_text().strip() if before else ""
            data["sale_price"] = actual.inner_text().strip() if actual else p_box.inner_text().strip()

        nc_el = elem.query_selector(".css-o11ltr")
        data["new_car_price"] = nc_el.inner_text().strip() if nc_el else ""

        href = elem.get_attribute("href") or ""
        # URL에서 불필요한 쿼리 스트링 제거 후 저장
        data["url"] = (BASE_URL + href).split("?")[0] if not href.startswith("http") else href.split("?")[0]
    except: pass
    return data

def _extract_detail_smart(page) -> dict:
    """상세 페이지 정밀 추출"""
    res = {k: "" for k in ["model_name", "model_second_name", "grade_name", "images_all", "year", "km", "refund", "guarantee", "accident", "inner_car_wash", "insurance"]}
    match_map = {"연식": "year", "주행거리": "km", "환불": "refund", "보증": "guarantee", "사고": "accident", "세차": "inner_car_wash", "보험": "insurance"}

    try:
        page.wait_for_selector(".css-105xtr1", timeout=15000)
        page.evaluate("window.scrollBy(0, 500)")
        time.sleep(2.5)

        header = page.query_selector(".css-105xtr1")
        if header:
            m_name_el = header.query_selector(".css-1ugrlhy")
            res["model_name"] = m_name_el.inner_text().strip() if m_name_el else ""
            
            spans = header.query_selector_all(".css-pjgjzs span")
            span_texts = [s.inner_text().strip() for s in spans if s.inner_text().strip()]
            
            if len(span_texts) == 1:
                res["grade_name"] = span_texts[0]
            elif len(span_texts) >= 2:
                res["model_second_name"] = span_texts[0]
                res["grade_name"] = span_texts[1]

        spec_units = page.query_selector_all(".css-113wzqa")
        for unit in spec_units:
            label_el = unit.query_selector(".css-1b7o1k1")
            if label_el:
                label_txt = label_el.inner_text().strip()
                for kor, eng in match_map.items():
                    if kor in label_txt:
                        val = label_el.evaluate("n => n.nextElementSibling ? n.nextElementSibling.innerText : ''")
                        res[eng] = val.strip().replace("\n", " ")
                        break
        
        imgs = [i.get_attribute("src") for i in page.query_selector_all("img[src*='heydealer.com']") if i.get_attribute("src")]
        res["images_all"] = "|".join(list(dict.fromkeys(imgs)))
    except: pass
    return res

def main():
    write_log("=== 헤이딜러 통합 수집 시작 (model_cd 추가 버전) ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(ignore_https_errors=True, user_agent="Mozilla/5.0...")
        page = context.new_page()
        
        # 1. 목록 수집
        page.goto(f"{BASE_URL}/market/cars", wait_until="domcontentloaded", timeout=60000)
        raw_cars, seen = [], set()
        while len(raw_cars) < TEST_LIMIT:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2500)
            for link in page.query_selector_all('a[href^="/market/cars/"]'):
                url = (BASE_URL + (link.get_attribute("href") or "")).split("?")[0]
                if url not in seen and "/market/cars/" in url and url != f"{BASE_URL}/market/cars":
                    seen.add(url)
                    raw_cars.append(_extract_card_heydealer(link, BASE_URL))
                    if len(raw_cars) >= TEST_LIMIT: break
            if len(raw_cars) >= TEST_LIMIT: break

        # list.csv 저장 (model_cd 추가)
        list_fields = ["car_sn", "used_car_site", "model_name", "model_cd", "model_second_name", "grade_name", "year", "km", "before_sale", "sale_price", "new_car_price", "detail_url"]
        with open(RESULT_DIR / "heydealer_cars_list.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list_fields)
            writer.writeheader()
            for i, c in enumerate(raw_cars, 1):
                # URL에서 마지막 부분 추출 (예: 7yBJYAyE)
                model_cd = c["url"].split("/")[-1]
                writer.writerow({
                    "car_sn": i, 
                    "used_car_site": "헤이딜러", 
                    "model_name": c["model_name"],
                    "model_cd": model_cd,
                    "model_second_name": c["model_second_name"],
                    "grade_name": c["grade_name"],
                    "year": c["year"],
                    "km": c["km"],
                    "before_sale": c["before_sale"],
                    "sale_price": c["sale_price"],
                    "new_car_price": c["new_car_price"],
                    "detail_url": c["url"]
                })

        # 2. 상세 수집 (model_cd 추가)
        detail_fields = ["sn", "car_sn", "used_car_site", "model_name", "model_cd", "model_second_name", "grade_name", "images_all", "year", "km", "refund", "guarantee", "accident", "inner_car_wash", "insurance", "before_sale", "sale_price", "new_car_price"]
        with open(RESULT_DIR / "heydealer_cars_detail.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=detail_fields)
            writer.writeheader()
            for i, c in enumerate(raw_cars, 1):
                write_log(f"[{i}/{TEST_LIMIT}] 상세 분석: {c['url']}")
                model_cd = c["url"].split("/")[-1]
                try:
                    page.goto(c["url"], wait_until="domcontentloaded", timeout=30000)
                    det = _extract_detail_smart(page)
                    writer.writerow({
                        "sn": i, "car_sn": i, "used_car_site": "헤이딜러",
                        "model_name": det["model_name"] or c["model_name"],
                        "model_cd": model_cd,
                        "model_second_name": det["model_second_name"],
                        "grade_name": det["grade_name"] or c["grade_name"],
                        "before_sale": c["before_sale"],
                        "sale_price": c["sale_price"], 
                        "new_car_price": c["new_car_price"],
                        "images_all": det["images_all"],
                        "year": det["year"],
                        "km": det["km"],
                        "refund": det["refund"],
                        "guarantee": det["guarantee"],
                        "accident": det["accident"],
                        "inner_car_wash": det["inner_car_wash"],
                        "insurance": det["insurance"]
                    })
                    time.sleep(random.uniform(1.5, 2.0))
                except Exception as e:
                    write_log(f"실패: {e}")

        browser.close()
        write_log("=== 전체 수집 완료 ===")

if __name__ == "__main__":
    main()