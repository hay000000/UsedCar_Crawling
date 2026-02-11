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
IMG_DIR = BASE_DIR / "image" / "heydealer"  # 이미지 저장 경로

RESULT_DIR.mkdir(parents=True, exist_ok=True)
IMG_DIR.mkdir(parents=True, exist_ok=True)

def download_image(img_url, model_cd, idx):
    """이미지를 로컬 폴더에 저장"""
    try:
        if not img_url: return
        response = requests.get(img_url, stream=True, timeout=10)
        if response.status_code == 200:
            ext = img_url.split('.')[-1].split('?')[0] # 확장자 추출
            filename = f"{model_cd}_{idx}.{ext}"
            save_path = IMG_DIR / filename
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
    except Exception as e:
        print(f"   ⚠️ 이미지 다운로드 실패 ({model_cd}): {e}")

def _extract_card_heydealer(elem, idx) -> dict:
    data = {"model_sn": idx}
    try:
        href = elem.get_attribute("href") or ""
        full_url = (BASE_URL + href).split("?")[0] if not href.startswith("http") else href.split("?")[0]
        data["model_cd"] = full_url.split("/")[-1]
        data["detail_url"] = full_url

        m_box = elem.query_selector(".css-9j6363")
        if m_box:
            names = m_box.query_selector_all(".css-jk6asd")
            data["model_name"] = names[0].inner_text().strip() if len(names) > 0 else ""
            data["model_second_name"] = names[1].inner_text().strip() if len(names) > 1 else ""
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
            before = price_area.query_selector(".css-ja3yiu")
            sale = price_area.query_selector(".css-8sjynn")
            data["before_sale"] = before.inner_text().strip() if before else ""
            data["sale_price"] = sale.inner_text().strip() if sale else price_area.inner_text().strip()

        nc_el = elem.query_selector(".css-o11ltr")
        data["new_car_price"] = nc_el.inner_text().strip() if nc_el else ""

        info_tags = elem.query_selector_all(".css-14xsjnu .css-nzdaom")
        data["accident"] = info_tags[0].inner_text().strip() if len(info_tags) > 0 else ""
        data["insurance"] = info_tags[1].inner_text().strip() if len(info_tags) > 1 else ""

        data["create_dt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except: pass
    return data

def _extract_detail_smart(page, idx, model_cd) -> dict:
    res = {"model_sn": idx, "model_cd": model_cd}
    try:
        page.wait_for_selector(".css-1ugrlhy", timeout=15000)
        container = page.query_selector(".css-12qft46")
        if not container: return res
        
        sections = container.query_selector_all(".css-ltrevz")
        
        # [섹션 1] 기본 정보
        if len(sections) >= 1:
            sec1 = sections[0]
            m_name_el = sec1.query_selector(".css-1ugrlhy")
            res["model_name"] = m_name_el.inner_text().strip() if m_name_el else ""
            spans = sec1.query_selector_all(".css-pjgjzs span")
            v_spans = [s.inner_text().strip() for s in spans if s.inner_text().strip()]
            if len(v_spans) == 1: res["grade_name"] = v_spans[0]
            elif len(v_spans) >= 2: res["model_second_name"], res["grade_name"] = v_spans[0], v_spans[1]

            keys = ["year", "km", "refund", "guarantee", "accident", "inner_car_wash", "insurance"]
            items = sec1.query_selector_all(".css-113wzqa")
            for i, item in enumerate(items):
                if i < len(keys):
                    val = item.query_selector("div:not(.css-1b7o1k1)")
                    res[keys[i]] = val.inner_text().strip() if val else ""

        # [섹션 2] 색상
        if len(sections) >= 2:
            color_items = sections[1].query_selector_all(".css-113wzqa")
            if len(color_items) >= 1:
                res["color_ext"] = color_items[0].query_selector("div:not(.css-1b7o1k1)").inner_text().strip()
            if len(color_items) >= 2:
                res["color_int"] = color_items[1].query_selector("div:not(.css-1b7o1k1)").inner_text().strip()

        # [섹션 4] 관리상태 데이터값 및 이미지
        if len(sections) >= 4:
            sec4 = sections[3]
            # 관리 정보 아이템들 (.css-113wzqa)
            mgmt_items = sec4.query_selector_all(".css-113wzqa")
            
            # 1. 타이어 (첫 번째 항목)
            if len(mgmt_items) >= 1:
                # css-1b7o1k1(라벨)과 같은 선상에 있는 뒷순서 div 추출
                res["tire"] = mgmt_items[0].query_selector(".css-1b7o1k1 + div").inner_text().strip()
            
            # 2. 틴팅 (두 번째 항목 - "앞 31%..." 데이터 추출)
            if len(mgmt_items) >= 2:
                # .css-1b7o1k1 클래스 바로 옆에 붙어 있는 div만 콕 집어서 가져옵니다.
                # 이 방식은 내부의 svg나 css-97t8oi에 전혀 간섭받지 않습니다.
                target_div = mgmt_items[1].query_selector(".css-1b7o1k1 + div")
                res["tinting"] = target_div.inner_text().strip() if target_div else ""
            
            # 3. 차 키 (세 번째 항목)
            if len(mgmt_items) >= 3:
                res["car_key"] = mgmt_items[2].query_selector(".css-1b7o1k1 + div").inner_text().strip()

            # 이미지 저장 로직 (이미지 url이 포함된 class="css-w9nhgi"는 위 div들과 같은 선상(sibling)에 있음)
            images = sec4.query_selector_all(".css-w9nhgi img")
            for i, img in enumerate(images):
                src = img.get_attribute("src")
                if src: download_image(src, model_cd, i+1)

        # 기타 공통 데이터
        res["main_option"] = ", ".join([o.inner_text().strip() for o in page.query_selector_all(".css-vsdo2k")])
        ship = page.query_selector(".css-1n3oo4w")
        res["Shipping_information"] = ship.inner_text().strip() if ship else ""
        rec = page.query_selector(".css-yfldxx")
        res["rec_reason"] = rec.inner_text().strip() if rec else ""

    except Exception as e:
        print(f"   ⚠️ 파싱 에러: {e}")
    return res

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        print("🚀 헤이딜러 목록 수집 시작...")
        page.goto(f"{BASE_URL}/market/cars", wait_until="domcontentloaded")
        raw_list, seen = [], set()
        
        while len(raw_list) < TEST_LIMIT:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            cards = page.query_selector_all('a[href^="/market/cars/"]')
            for card in cards:
                href = card.get_attribute("href").split("?")[0]
                if href not in seen:
                    seen.add(href)
                    raw_list.append(_extract_card_heydealer(card, len(raw_list) + 1))
                    if len(raw_list) >= TEST_LIMIT: break

        # 목록 저장
        list_fields = ["model_sn", "model_cd", "model_name", "model_second_name", "grade_name", "year", "km", "before_sale", "sale_price", "new_car_price", "accident", "insurance", "detail_url", "create_dt"]
        with open(RESULT_DIR / "heydealer_list.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list_fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(raw_list)

        # 상세 수집
        detail_results = []
        detail_fields = ["model_sn", "model_cd", "model_name", "model_second_name", "grade_name", "year", "km", "refund", "guarantee", "accident", "inner_car_wash", "insurance", "color_ext", "color_int", "main_option", "Shipping_information", "rec_reason", "tire", "tinting", "car_key", "detail_url", "create_dt"]

        for item in raw_list:
            success = False
            for retry in range(2):
                print(f"🔍 상세 수집 중: {item['model_cd']} (시도 {retry+1}/2)")
                try:
                    page.goto(item["detail_url"], wait_until="domcontentloaded", timeout=30000)
                    time.sleep(3)
                    detail = _extract_detail_smart(page, item["model_sn"], item["model_cd"])
                    if detail.get("model_name"):
                        detail.update({"detail_url": item["detail_url"], "create_dt": item["create_dt"]})
                        detail_results.append(detail)
                        success = True
                        break
                except Exception as e:
                    print(f"   ❌ 로딩 실패 ({e})")
                    time.sleep(2)
            
            if not success:
                detail_results.append({"model_sn": item["model_sn"], "model_cd": item["model_cd"], "detail_url": item["detail_url"], "create_dt": item["create_dt"]})

        with open(RESULT_DIR / "heydealer_detail.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=detail_fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(detail_results)
        
        print("✅ 모든 수집 및 이미지 저장 완료")
        browser.close()

if __name__ == "__main__":
    main()