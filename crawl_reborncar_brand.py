import logging
import csv
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

def setup_logger():
    log_dir = Path("./logs/reborncar")
    log_path = log_dir / "reborncar_brand_hierachy.log"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    logger = logging.getLogger("RebornCarLogger")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh = logging.FileHandler(log_path, encoding='utf-8'); fh.setFormatter(formatter)
        sh = logging.StreamHandler(); sh.setFormatter(formatter)
        logger.addHandler(fh); logger.addHandler(sh)
    return logger

def split_boname_by_last_paren(text):
    """뒤에서부터 첫 번째 ()를 기준으로 나누어 '앞부분|(괄호내용)' 형태로 반환"""
    if not text or "(" not in text:
        return text
    last_open = text.rfind("(")
    prefix = text[:last_open].strip()
    suffix = text[last_open:].strip()  # (23년~현재) 형태
    if not prefix:
        return text
    return f"{prefix}|{suffix}"

def run_reborn_brand_crawler():
    logger = setup_logger()
    result_data = []
    
    # 시간 정보 생성
    now = datetime.now()
    pnttm = now.strftime("%Y%m%d")          # 20260219
    create_dt = now.strftime("%Y%m%d%H%M") # 202602191042

    # WSL 경로 설정
    target_dir = Path("/home/limhayoung/used_car_crawler/result/reborncar")
    target_dir.mkdir(parents=True, exist_ok=True)
    csv_path = target_dir / "reborncar_brand.csv"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        page = browser.new_page()

        try:
            logger.info("리본카 최종 형식 데이터 수집 시작...")
            page.goto("https://www.reborncar.co.kr/smartbuy/SB1001.rb", wait_until="networkidle")

            brand_selectors = page.locator(".filter-brand .brand-list")
            brand_count = brand_selectors.count()
            
            model_sn = 1 # 순번 초기화

            for i in range(brand_count):
                brand_box = brand_selectors.nth(i)
                bmname = brand_box.locator(".brand-name label span").inner_text().strip()
                
                logger.info(f"[{bmname}] 처리 중...")
                brand_box.locator(".brand-name label").click()
                page.wait_for_timeout(400)

                car_items = brand_box.locator(".car-list .check-box[class*='car-']")
                car_count = car_items.count()

                for j in range(car_count):
                    car_box = car_items.nth(j)
                    boiname = car_box.locator("label span").first.inner_text().strip()
                    
                    # 차종 클릭하여 상세 모델 활성화
                    car_box.locator("label").first.click()
                    page.wait_for_timeout(300)

                    detail_boxes = car_box.locator(".model-list .check-box")
                    detail_count = detail_boxes.count()

                    if detail_count > 0:
                        for k in range(detail_count):
                            full_boname = detail_boxes.nth(k).locator("label span").inner_text().strip()
                            
                            result_data.append({
                                "model_sn": model_sn,
                                "bmname": bmname,
                                "boiname": boiname,
                                "boname": split_boname_by_last_paren(full_boname),
                                "date_crtr_pnttm": pnttm,
                                "create_dt": create_dt
                            })
                            model_sn += 1
                    else:
                        # 상세 모델이 없는 경우
                        result_data.append({
                            "model_sn": model_sn,
                            "bmname": bmname,
                            "boiname": boiname,
                            "boname": split_boname_by_last_paren(boiname),
                            "date_crtr_pnttm": pnttm,
                            "create_dt": create_dt
                        })
                        model_sn += 1

            # CSV 저장 (요청하신 순서대로 헤더 설정)
            if result_data:
                headers = ["model_sn", "bmname", "boiname", "boname", "date_crtr_pnttm", "create_dt"]
                with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.DictWriter(f, fieldnames=headers)
                    writer.writeheader()
                    writer.writerows(result_data)
                logger.info(f"최종 성공: {len(result_data)}행 저장 완료 -> {csv_path}")

        except Exception as e:
            logger.error(f"오류 발생: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    run_reborn_brand_crawler()