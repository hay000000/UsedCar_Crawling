import logging
import csv
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

def setup_logger():
    log_dir = Path("/home/limhayoung/used_car_crawler/logs/reborncar")
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


def split_model_list_and_period(combined):
    """'앞부분|(괄호내용)' 형태에서 (model_list, production_period) 반환"""
    if not combined or "|" not in combined:
        return combined.strip(), ""
    parts = combined.split("|", 1)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")


def normalize_production_period(text):
    """'(21~24년)' → '21~24', '(23년~현재)' → '23~현재' 형태로 변환."""
    if not text:
        return ""
    s = text.strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    s = s.replace("년", "")
    return s

def run_reborn_brand_crawler():
    logger = setup_logger()

    # 시간 정보 생성
    now = datetime.now()
    pnttm = now.strftime("%Y%m%d")          # 20260219
    create_dt = now.strftime("%Y%m%d%H%M") # 202602191042

    # WSL 경로 설정
    target_dir = Path("/home/limhayoung/used_car_crawler/result/reborncar")
    target_dir.mkdir(parents=True, exist_ok=True)
    csv_path = target_dir / "reborncar_brand_list.csv"

    headers = ["model_sn", "brand_list", "car_list", "model_list", "model_list_1", "model_list_2", "production_period", "date_crtr_pnttm", "create_dt"]
    # 이전 결과가 있으면 삭제 후 새로 생성
    if csv_path.exists():
        csv_path.unlink()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            logger.info("리본카 최종 형식 데이터 수집 시작...")
            page.goto("https://www.reborncar.co.kr/smartbuy/SB1001.rb", wait_until="networkidle")

            brand_selectors = page.locator(".filter-brand .brand-list")
            brand_count = brand_selectors.count()

            model_sn = 1
            row_count = 0

            for i in range(brand_count):
                brand_box = brand_selectors.nth(i)
                brand_list = brand_box.locator(".brand-name label span").inner_text().strip()

                logger.info(f"[{brand_list}] 처리 중...")
                brand_box.locator(".brand-name label").click()
                page.wait_for_timeout(400)

                car_items = brand_box.locator(".car-list .check-box[class*='car-']")
                car_count = car_items.count()

                for j in range(car_count):
                    car_box = car_items.nth(j)
                    car_list = car_box.locator("label span").first.inner_text().strip()

                    # 차종 클릭하여 상세 모델 활성화
                    car_box.locator("label").first.click()
                    page.wait_for_timeout(300)

                    # 모델만 선택 (트림/옵션 check-box 제외: class에 model- 포함된 것만)
                    detail_boxes = car_box.locator(".model-list .check-box[class*='model-']")
                    detail_count = detail_boxes.count()

                    if detail_count > 0:
                        for k in range(detail_count):
                            model_box = detail_boxes.nth(k)
                            full_boname = model_box.locator("> label span").inner_text().strip()
                            model_list_val, production_period_val = split_model_list_and_period(
                                split_boname_by_last_paren(full_boname)
                            )
                            production_period_val = normalize_production_period(production_period_val)

                            # 모델 클릭하여 trim-list(depth04) 펼치기
                            model_box.locator("label").first.click()
                            page.wait_for_timeout(200)

                            trim_boxes = model_box.locator(".trim-list.depth04 .check-box[class*='trim-']")
                            trim_count = trim_boxes.count()

                            # 트림이 전혀 없는 모델(예: 더 뉴레이, 레이(11~17년))도 1행으로 수집
                            if trim_count == 0:
                                row = {
                                    "model_sn": model_sn,
                                    "brand_list": brand_list,
                                    "car_list": car_list,
                                    "model_list": model_list_val,
                                    "model_list_1": "",
                                    "model_list_2": "",
                                    "production_period": production_period_val,
                                    "date_crtr_pnttm": pnttm,
                                    "create_dt": create_dt
                                }
                                with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
                                    writer = csv.DictWriter(f, fieldnames=headers)
                                    if model_sn == 1:
                                        writer.writeheader()
                                    writer.writerow(row)
                                row_count += 1
                                model_sn += 1
                                continue

                            # 트림·옵션 조합별로 한 행씩 출력 (model_list_1=트림명, model_list_2=옵션명)
                            for t in range(trim_count):
                                trim_el = trim_boxes.nth(t)
                                try:
                                    trim_name = trim_el.locator("label span").inner_text().strip()
                                except Exception:
                                    trim_name = ""
                                trim_el.locator("label").click()
                                page.wait_for_timeout(250)
                                # 현재 트림 요소 안에서만 옵션 조회 (트렌디/프레스티지/노블레스 등 해당 트림 옵션만 수집)
                                option_boxes = trim_el.locator(".option-list.depth05 .check-box[class*='option-']")
                                opt_count = option_boxes.count()
                                if opt_count > 0:
                                    for o in range(opt_count):
                                        try:
                                            option_name = option_boxes.nth(o).locator("label span").inner_text().strip()
                                        except Exception:
                                            option_name = ""
                                        row = {
                                            "model_sn": model_sn,
                                            "brand_list": brand_list,
                                            "car_list": car_list,
                                            "model_list": model_list_val,
                                            "model_list_1": trim_name,
                                            "model_list_2": option_name,
                                            "production_period": production_period_val,
                                            "date_crtr_pnttm": pnttm,
                                            "create_dt": create_dt
                                        }
                                        with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
                                            writer = csv.DictWriter(f, fieldnames=headers)
                                            if model_sn == 1:
                                                writer.writeheader()
                                            writer.writerow(row)
                                        row_count += 1
                                        model_sn += 1
                                else:
                                    # 옵션이 없는 트림은 한 행만 (model_list_2 빈값)
                                    row = {
                                        "model_sn": model_sn,
                                        "brand_list": brand_list,
                                        "car_list": car_list,
                                        "model_list": model_list_val,
                                        "model_list_1": trim_name,
                                        "model_list_2": "",
                                        "production_period": production_period_val,
                                        "date_crtr_pnttm": pnttm,
                                        "create_dt": create_dt
                                    }
                                    with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
                                        writer = csv.DictWriter(f, fieldnames=headers)
                                        if model_sn == 1:
                                            writer.writeheader()
                                        writer.writerow(row)
                                    row_count += 1
                                    model_sn += 1
                    else:
                        # 상세 모델이 없는 경우
                        car_model_list, car_production_period = split_model_list_and_period(
                            split_boname_by_last_paren(car_list)
                        )
                        car_production_period = normalize_production_period(car_production_period)
                        row = {
                            "model_sn": model_sn,
                            "brand_list": brand_list,
                            "car_list": car_list,
                            "model_list": car_model_list,
                            "model_list_1": "",
                            "model_list_2": "",
                            "production_period": car_production_period,
                            "date_crtr_pnttm": pnttm,
                            "create_dt": create_dt
                        }
                        with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
                            writer = csv.DictWriter(f, fieldnames=headers)
                            if model_sn == 1:
                                writer.writeheader()
                            writer.writerow(row)
                        row_count += 1
                        model_sn += 1

            logger.info(f"최종 성공: {row_count}행 저장 완료 -> {csv_path}")

        except Exception as e:
            logger.error(f"오류 발생: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    run_reborn_brand_crawler()