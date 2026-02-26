import logging
import csv
from pathlib import Path
from playwright.sync_api import sync_playwright

def setup_logger():
    # 로그 디렉토리 및 파일 설정
    log_dir = Path("./logs/reborncar")
    log_path = log_dir / "reborncar_car_type.log"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    logger = logging.getLogger("RebornCarLogger")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh = logging.FileHandler(log_path, encoding='utf-8')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(formatter)
        logger.addHandler(sh)
    return logger

def save_to_csv(data):
    # 결과 디렉토리 설정 (기존 경로 유지)
    result_dir = Path("./result/reborncar")
    result_path = result_dir / "reborncar_car_type_list.csv"
    result_dir.mkdir(parents=True, exist_ok=True)
    
    # 변경된 컬럼명 설정 (순번, cate_cb, car_type_name)
    keys = ["car_type_sn", "cate_cb", "car_type_name"]
    with open(result_path, "w", newline="", encoding="utf-8-sig") as f:
        dict_writer = csv.DictWriter(f, fieldnames=keys)
        dict_writer.writeheader()
        dict_writer.writerows(data)
    
    return result_path

def run_crawler():
    logger = setup_logger()
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            logger.info("리본카 페이지 접속 중...")
            page.goto("https://www.reborncar.co.kr/smartbuy/SB1001.rb", wait_until="networkidle")

            logger.info("HTML 태그 기반 차종 데이터 추출 시작...")
            
            # class="cate-cb" 이면서 id가 car_type으로 시작하는 input 요소 추출
            car_type_elements = page.locator("input.cate-cb[id^='car_type']").all()

            results = []
            car_type_sn = 1  # 순번 초기화

            for el in car_type_elements:
                el_id = el.get_attribute("id")
                # value 값을 cate_cb 사용
                cate_cb = el.get_attribute("value")
                
                # input의 id와 연결된 label 안의 span 텍스트를 car_type_name 사용
                label_span = page.locator(f"label[for='{el_id}'] span")
                
                if label_span.count() > 0:
                    car_type_name = label_span.inner_text().strip()
                    
                    item = {
                        "car_type_sn": car_type_sn,
                        "cate_cb": cate_cb,
                        "car_type_name": car_type_name
                    }
                    results.append(item)
                    logger.info(f"[수집 성공] {car_type_name} (SN: {car_type_sn}, cate_cb: {cate_cb})")
                    
                    car_type_sn += 1  # 순번 증가

            if results:
                csv_path = save_to_csv(results)
                logger.info(f"CSV 저장 완료: {csv_path}")
                logger.info(f"총 {len(results)}개의 차종 데이터가 저장되었습니다.")
            else:
                logger.error("데이터를 찾지 못했습니다. 태그 구조를 다시 점검해 주세요.")

        except Exception as e:
            logger.error(f"크롤링 중 예외 발생: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    run_crawler()