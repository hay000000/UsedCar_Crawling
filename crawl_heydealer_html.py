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

def get_now_times():
    """요청하신 형식의 날짜 데이터 생성"""
    now = datetime.now()
    # 202602111328 형식 (YYYYMMDDHHMI) - 12자리
    creat_de = now.strftime("%Y%m%d%H%M")
    # 20260211 형식 (YYYYMMDD) - 8자리
    data_crtr_pnttm = now.strftime("%Y%m%d")
    return data_crtr_pnttm, creat_de

def download_image(img_url, model_cd, idx):
    """이미지를 로컬 ./image/heydealer 폴더에 저장"""
    try:
        if not img_url: return
        response = requests.get(img_url, stream=True, timeout=10)
        if response.status_code == 200:
            ext = img_url.split('.')[-1].split('?')[0]
            filename = f"{model_cd}_{idx}.{ext}"
            save_path = IMG_DIR / filename
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
    except:
        pass

def _extract_card_heydealer(elem, idx) -> dict:
    """목록 정보 수집"""
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

        # 날짜 정보 추가
        d_pnttm, c_dt = get_now_times()
        data["date_crtr_pnttm"] = d_pnttm
        data["create_dt"] = c_dt
    except: pass
    return data

def clean_text_to_pipe(raw_text):
    """오직 줄바꿈만 파이프로 변경하여 원본 데이터 보존"""
    if not raw_text: return ""
    # 줄바꿈을 기준으로 나누고, 각 줄의 앞뒤 공백만 제거한 뒤 파이프로 연결
    lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
    return " | ".join(lines)

def _extract_detail_smart(page, idx, model_cd) -> dict:
    """상세 정보 수집 - 요청하신 2개 컬럼만 파이프 적용"""
    res = {"model_sn": idx, "model_cd": model_cd}
    try:
        page.wait_for_selector(".css-12qft46", timeout=15000)
        container = page.query_selector(".css-1uus6sd .css-12qft46")
        if not container: return res
            
        sections = container.query_selector_all(".css-ltrevz")
        
        # --- [섹션 1] 차량명 및 기본 스펙 ---
        # --- [섹션 1] 이름 및 year ~ insurance 영역 ---
        if len(sections) >= 1:
            sec1 = sections[0]
            m_name_el = sec1.query_selector(".css-1ugrlhy")
            res["model_name"] = m_name_el.inner_text().strip() if m_name_el else ""
            spans = sec1.query_selector_all(".css-pjgjzs span")
            v_spans = [s.inner_text().strip() for s in spans if s.inner_text().strip()]
            if len(v_spans) == 1: res["grade_name"] = v_spans[0]
            elif len(v_spans) >= 2: res["model_second_name"], res["grade_name"] = v_spans[0], v_spans[1]

            keys = ["year", "km", "refund", "guarantee", "accident", "inner_car_wash", "insurance"]


            # [핵심] 텍스트 매칭 로직: 인덱스가 아니라 '연식', '주행거리'라는 글자를 보고 저장함
            # 데이터가 없으면 해당 if문에 안 걸리므로 그냥 빈값("")으로 남음 (밀림 방지)
            items = sec1.query_selector_all(".css-113wzqa")
            for item in items:
                label_el = item.query_selector(".css-1b7o1k1") # '연식', '주행거리' 등이 적힌 곳
                val_el = item.query_selector(".css-1b7o1k1 + div") # 실제 데이터가 적힌 곳
                
                if label_el and val_el:
                    label = label_el.inner_text().strip()
                    value = val_el.inner_text().strip()
                    
                    if "연식" in label: res["year"] = value
                    elif "주행거리" in label: res["km"] = value
                    elif "환불" in label: res["refund"] = value
                    elif "보증" in label: res["guarantee"] = value
                    elif "사고" in label: res["accident"] = value
                    elif "실내세차" in label: res["inner_car_wash"] = value
                    elif "보험" in label: res["insurance"] = value

        # --- [섹션 2] 색상 ---
        if len(sections) >= 2:
            color_items = sections[1].query_selector_all(".css-113wzqa")
            if len(color_items) >= 1: res["color_ext"] = color_items[0].query_selector(".css-1b7o1k1 + div").inner_text().strip()
            if len(color_items) >= 2: res["color_int"] = color_items[1].query_selector(".css-1b7o1k1 + div").inner_text().strip()

        # --- [섹션 3] 옵션 및 출고 정보 ---
        if len(sections) >= 3:
            sec3 = sections[2]
            # 주요 옵션 (쉼표 유지)
            option_elements = sec3.query_selector_all(".css-5pr39e .css-1i3qy3r .css-vsdo2k .css-g5wwb2 .css-13wylk3")
            res["main_option"] = ", ".join([opt.inner_text().strip() for opt in option_elements if opt.inner_text().strip()])

            # 1) delivery_information (파이프 적용 대상)
            ship_el = sec3.query_selector(".css-1cfq7ri .css-1n3oo4w")
            res["delivery_information"] = clean_text_to_pipe(ship_el.inner_text()) if ship_el else ""

        # --- [섹션 4] 관리상태 (원본 데이터 유지) ---
        if len(sections) >= 4:
            sec4 = sections[3]
            mgmt_items = sec4.query_selector_all(".css-113wzqa")
            keys_mgmt = ["tire", "tinting", "car_key"]
            for i, item in enumerate(mgmt_items):
                if i < len(keys_mgmt):
                    val = item.query_selector(".css-1b7o1k1 + div")
                    res[keys_mgmt[i]] = val.inner_text().strip() if val else ""

        # 이미지 수집
        target_images = []
        if len(sections) >= 2: target_images.extend(sections[1].query_selector_all("img"))
        if len(sections) >= 4: target_images.extend(sections[3].query_selector_all("img"))
        target_images.extend(page.query_selector_all(".css-w9nhgi img, .css-q47uzu img, .css-1a3591h img"))

        downloaded_urls = set()
        img_idx = 1
        for img in target_images:
            src = img.get_attribute("src")
            if src and "svg" not in src and src not in downloaded_urls:
                download_image(src, model_cd, img_idx)
                downloaded_urls.add(src)
                img_idx += 1

        # 2) rec_reason (파이프 적용 대상)
        rec_el = page.query_selector(".css-isc2b5 .css-yfldxx")
        res["rec_reason"] = clean_text_to_pipe(rec_el.inner_text()) if rec_el else ""

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
        list_fields = ["model_sn", "model_cd", "model_name", "model_second_name", "grade_name", "year", "km", "before_sale", "sale_price", "new_car_price", "accident", "insurance", "detail_url", "date_crtr_pnttm", "create_dt"]
        with open(RESULT_DIR / "heydealer_list.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list_fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(raw_list)
        print(f"✅ 목록 수집 완료 → 경로: {RESULT_DIR / 'heydealer_list.csv'} | 파일명: heydealer_list.csv")

        # 상세 수집
        detail_results = []
        detail_fields = ["model_sn", "model_cd", "model_name", "model_second_name", "grade_name", "year", "km", "refund", "guarantee", "accident", "inner_car_wash", "insurance", "color_ext", "color_int", "main_option", "delivery_information", "rec_reason", "tire", "tinting", "car_key", "detail_url", "date_crtr_pnttm", "create_dt"]

        max_retries = 5
        for item in raw_list:
            success = False
            for retry in range(max_retries):
                if retry == 0:
                    print(f"🔍 상세 수집 중: {item['model_cd']}")
                else:
                    remaining = max_retries - retry - 1
                    print(f"🚨 상세 재수집 중: {item['model_cd']} (남은 횟수 {remaining})")
                try:
                    page.goto(item["detail_url"], wait_until="domcontentloaded", timeout=40000)
                    time.sleep(3)
                    detail = _extract_detail_smart(page, item["model_sn"], item["model_cd"])
                    if detail.get("model_name"):
                        # 날짜 정보 동기화
                        detail.update({
                            "detail_url": item["detail_url"], 
                            "date_crtr_pnttm": item["date_crtr_pnttm"], 
                            "create_dt": item["create_dt"]
                        })
                        detail_results.append(detail)
                        success = True
                        if retry > 0:
                            print(f"   ✅ 재수집 성공: {item['model_cd']}")
                        break
                except:
                    time.sleep(2)
            
            if not success:
                print(f"   ❌ 상세 수집 실패: {item['model_cd']} (재시도 후에도 미수집)")
                detail_results.append({
                    "model_sn": item["model_sn"], "model_cd": item["model_cd"], 
                    "detail_url": item["detail_url"], "date_crtr_pnttm": item["date_crtr_pnttm"], "create_dt": item["create_dt"]
                })

        with open(RESULT_DIR / "heydealer_detail.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=detail_fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(detail_results)
        print(f"✅ 상세 수집 완료 → 경로: {RESULT_DIR / 'heydealer_cars_detail.csv'} | 파일명: heydealer_cars_detail.csv")
        
        print("✅ 모든 수집 완료")
        browser.close()

if __name__ == "__main__":
    main()