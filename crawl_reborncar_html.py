import csv
import logging
import re
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

def setup_logger():
    log_dir = Path("./logs/reborncar")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "reborncar_full_list.log"
    logger = logging.getLogger("RebornCar")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh = logging.FileHandler(log_path, encoding='utf-8'); logger.addHandler(fh)
        sh = logging.StreamHandler(); logger.addHandler(sh)
    return logger

def run_full_crawler():
    logger = setup_logger()
    now = datetime.now()
    pnttm, create_dt_full = now.strftime("%Y%m%d"), now.strftime("%Y%m%d%H%M")
    
    csv_path = Path("/home/limhayoung/used_car_crawler/result/reborncar/reborncar_all_cars.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists():
        csv_path.unlink()

    # 1. productid 컬럼을 model_sn 다음으로 추가
    headers = [
        "model_sn", "productid", "boname", "gradename", "year", "carnavi", "seaterinfo", 
        "finamtsel", "amtsel", "amthal", "amthalmonth", "copytext", 
        "endtimedeal", "status", "date_crtr_pnttm", "create_dt"
    ]

    car_counter = 1

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...", 
            viewport={'width': 1900, 'height': 1000}
        )
        page = context.new_page()

        try:
            logger.info("리본카 페이지 접속 중...")
            page.goto("https://www.reborncar.co.kr/smartbuy/SB1001.rb")
            page.wait_for_selector("ul.lp-box.smartbuy-lp", timeout=60000)

            while True:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(3000)

                # 실제 페이지 번호는 DOM의 active 셀에서 읽기 (1~109)
                active_el = page.locator("li.pagination-con.page-num.active")
                try:
                    current_page = int(active_el.get_attribute("data-lp") or active_el.inner_text() or "1")
                except Exception:
                    current_page = 1

                item_locator = page.locator("ul.lp-box.smartbuy-lp > li.lp-con.swiper-slide:not(.lp-banner):not(.swiper-slide-duplicate)")
                items = item_locator.all()
                logger.info(f"현재 {current_page}번째 페이지 (실제) - 수집 매물: {len(items)}개")

                with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
                    writer = csv.DictWriter(f, fieldnames=headers)
                    if car_counter == 1: writer.writeheader()

                    for item in items:
                        try:
                            # --- [신규 추가] productid 추출 ---
                            # href="javascript:fnDetailMove('C25120300012',...)" 에서 값만 추출
                            v_product_id = ""
                            thumbnail_link = item.locator("a.lp-thumnail")
                            if thumbnail_link.count() > 0:
                                href_value = thumbnail_link.get_attribute("href")
                                if href_value and "fnDetailMove" in href_value:
                                    # 정규식을 사용하여 첫 번째 따옴표 안의 값을 가져옴
                                    match = re.search(r"fnDetailMove\('([^']+)'", href_value)
                                    if match:
                                        v_product_id = match.group(1)

                            # 1. 상태값 추출
                            v_status = item.locator(".lp-status").inner_text().strip()
                            if not v_status: v_status = "판매중"

                            # 2. 정보 초기화
                            v_finamt, v_amtsel, v_amthal, v_month = "-", "-", "-", "-"

                            # 3. 상태별 가격 추출
                            if v_status in ["판매중", "계약중", "상담중"]:
                                pay_b = item.locator(".car-pay .pay b")
                                if pay_b.count() > 0:
                                    v_finamt = pay_b.inner_text().strip() + "만원"
                                
                                discount_el = item.locator(".car-pay .discount")
                                v_amtsel = discount_el.inner_text().strip() if discount_el.count() > 0 else "0"
                                
                                plan_txt = item.locator(".plan-txt")
                                plan_date = item.locator(".plan-date")
                                v_amthal = plan_txt.inner_text().strip() if plan_txt.count() > 0 else "-"
                                v_month = plan_date.inner_text().strip() if plan_date.count() > 0 else ""
                                v_month = v_month.lstrip("/ ").strip() if v_month else v_month
                            
                            elif v_status == "준비중":
                                v_finamt = "0만원"
                                v_amtsel = "-"
                                
                            elif v_status == "판매완료":
                                v_finamt = "판매완료"
                                v_amtsel = "-"

                            # 4. 공통 정보 추출
                            v_boname = item.locator(".lp-car-name").inner_text().strip()
                            v_grade = item.locator(".lp-car-trim").inner_text().strip()
                            
                            summary_lis = item.locator(".lp-summery li").all()
                            v_year = summary_lis[0].inner_text().strip() if len(summary_lis) > 0 else ""
                            v_navi = summary_lis[1].inner_text().strip() if len(summary_lis) > 1 else ""
                            v_seat = summary_lis[2].inner_text().strip() if len(summary_lis) > 2 else ""

                            is_td = item.locator(".lp-timedeal").count() > 0
                            v_copy = "타임딜" if is_td else ""
                            v_endtd = item.locator(".lp-timedeal-count").inner_text().strip() if is_td else ""

                            writer.writerow({
                                "model_sn": car_counter,
                                "productid": v_product_id, # 수집된 키값 입력
                                "boname": v_boname, "gradename": v_grade,
                                "year": v_year, "carnavi": v_navi, "seaterinfo": v_seat,
                                "finamtsel": v_finamt, "amtsel": v_amtsel, "amthal": v_amthal,
                                "amthalmonth": v_month, "copytext": v_copy, "endtimedeal": v_endtd,
                                "status": v_status, "date_crtr_pnttm": pnttm, "create_dt": create_dt_full
                            })
                            car_counter += 1
                        except Exception as e:
                            logger.error(f"데이터 추출 에러 (번호 {car_counter}): {e}")
                            continue

                # 페이지네이션: 다음 숫자(12,13..) 클릭, 없으면 다음 그룹(>) 클릭. 109페이지에서 종료.
                if current_page >= 109:
                    break
                next_page_link = page.locator("li.pagination-con.page-num.active + li.pagination-con.page-num:not(.next):not(.prev) a").first
                if next_page_link.count() > 0:
                    next_page_link.evaluate("el => el.click()")
                    page.wait_for_timeout(3000)
                else:
                    next_group = page.locator("li.pagination-con.next:not(.disabled) a").first
                    if next_group.count() > 0:
                        next_group.evaluate("el => el.click()")
                        page.wait_for_timeout(4000)
                    else:
                        break
            logger.info(f"최종 완료: 총 {current_page}페이지, {car_counter - 1}개")
        finally:
            browser.close()

if __name__ == "__main__":
    run_full_crawler()