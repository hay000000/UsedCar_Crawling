import csv
import logging
import re
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

def setup_logger():
    log_dir = Path("./logs/reborncar")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "reborncar_list_detail.log"
    logger = logging.getLogger("RebornCar")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh = logging.FileHandler(log_path, encoding='utf-8'); logger.addHandler(fh)
        sh = logging.StreamHandler(); logger.addHandler(sh)
    return logger

def get_detail_info(page, product_id, logger):
    """상세 페이지에서 추가 데이터를 추출하는 함수"""
    detail_url = f"https://www.reborncar.co.kr/smartbuy/SB1002.rb?productId={product_id}"
    detail_data = {
        "car_new_price": "-", "accident": "-", "flood": "-", "change_use": "-",
        "comp_new_car": "-", "smell_level": "-", "refund": "-", "options": "-", "additional_options": "-",
        "car_number": "-", "gear_box": "-", "car_color": "-", "car_fuel": "-", "plan_pay": "-",
        "figure_panel": "-", "figure_frame": "-",
        "aqi_list": "-", "aqi_notice_list": "-",
        "tire_summery_front_left": "-", "tire_summery_back_left": "-",
        "tire_summery_back_right": "-", "tire_summery_front_right": "-"
    }

    try:
        page.goto(detail_url, wait_until="domcontentloaded")
        page.wait_for_selector("#info", timeout=10000)

        # 0. vip-section: 차량번호, 변속기, 색상, 연료, 플랜결제
        vip = page.locator(".vip-section .vip-head .vip-head-info")
        if vip.count() > 0:
            # car_number: 첫 번째 .car-info > .car-main-info > .car-number
            car_infos = vip.locator(".car-info")
            if car_infos.count() > 0:
                first_car = car_infos.nth(0)
                cn_el = first_car.locator(".car-main-info .car-number")
                if cn_el.count() > 0:
                    detail_data["car_number"] = cn_el.inner_text().strip()
            # gear_box, car_color, car_fuel: 두 번째 .car-info > .car-sub-info > .car-infos
            if car_infos.count() >= 2:
                sub_info = car_infos.nth(1).locator(".car-sub-info .car-infos")
                if sub_info.count() > 0:
                    gb = sub_info.locator(".gear-box")
                    cc = sub_info.locator(".car-color")
                    cf = sub_info.locator(".car-fuel")
                    if gb.count() > 0: detail_data["gear_box"] = gb.inner_text().strip()
                    if cc.count() > 0: detail_data["car_color"] = cc.inner_text().strip()
                    if cf.count() > 0: detail_data["car_fuel"] = cf.inner_text().strip()
            # plan_pay: 두 번째 .car-info > .car-sub-pay > .plan-pay
            if car_infos.count() >= 2:
                plan_ul = car_infos.nth(1).locator(".car-sub-pay .plan-pay")
                if plan_ul.count() > 0:
                    lis = plan_ul.locator("li").all()
                    parts = []
                    for li in lis:
                        txt = li.inner_text().strip()
                        # 줄바꿈 제거 후 "리스 : 45만원(48개월)" 형태로
                        if txt:
                            txt_flat = re.sub(r"\s+", "", txt)
                            parts.append(re.sub(r"(\d)(만원)", r"\1\2", re.sub(r"^([^\d]+)(\d)", r"\1 : \2", txt_flat)) if re.search(r"\d", txt_flat) else txt_flat)
                    detail_data["plan_pay"] = " | ".join(parts) if parts else "-"

        # 1. 신차 출고가 추출
        price_el = page.locator("li:has-text('신차 출고가') .car-new-price")
        if price_el.count() > 0:
            detail_data["car_new_price"] = price_el.inner_text().strip()

        # 2. 사고/침수/용도/가격대비/냄새/환불 추출 (요소 없으면 5초 후 스킵)
        t_detail = 5000
        info_list = page.locator(".vip-car-info-body .info-list-con")
        for i in range(info_list.count()):
            try:
                con = info_list.nth(i)
                title = con.locator(".info-txt").inner_text(timeout=t_detail).replace(">", "").strip()
                value = con.locator(".info-tit").inner_text(timeout=t_detail).strip()
                if "사고여부" in title: detail_data["accident"] = value
                elif "침수여부" in title: detail_data["flood"] = value
                elif "용도변경" in title: detail_data["change_use"] = value
                elif "신차가격대비" in title: detail_data["comp_new_car"] = re.sub(r"\s+", "", value)
                elif "냄새등급" in title: detail_data["smell_level"] = value
                elif "안심환불" in title: detail_data["refund"] = value
            except Exception:
                continue

        # 3. 차량 옵션 추출 (기본) - 구분자 |
        options = page.locator(".vip-option-list .vip-option-txt").all_inner_texts()
        detail_data["options"] = " | ".join([o.strip() for o in options if o.strip()])

        # 4. 추가 선택 옵션 추출 - 구분자 |
        add_opt_list = page.locator(".add-option-list .add-option-con")
        add_opts = []
        for i in range(add_opt_list.count()):
            opt_title = add_opt_list.nth(i).locator(".add-option-title").inner_text().strip()
            opt_pay = add_opt_list.nth(i).locator(".add-option-pay").inner_text().strip()
            add_opts.append(f"{opt_title}({opt_pay})")
        detail_data["additional_options"] = " | ".join(add_opts)

        # 5. vip-body: figure_panel(.cont.sheeting-status), figure_frame(.cont.change-status)
        body = page.locator(".vip-body .vip-con .con-section.aqi .vip-cont .car-figure-form .car-figure-info .car-figure-info-list")
        if body.count() > 0:
            # figure_panel: .figure-panel .cont.sheeting-status → "판금 : 1건 | 교환 : 1건" 또는 .success면 "정상"
            panel_el = body.locator(".figure-panel .cont.sheeting-status")
            if panel_el.count() > 0:
                parts = []
                sheeting = panel_el.locator(".sheeting-count")
                change = panel_el.locator(".change-count")
                if sheeting.count() > 0:
                    t = sheeting.inner_text().strip().replace(" ", " : ", 1)
                    parts.append(t)
                if change.count() > 0:
                    t = change.inner_text().strip().replace(" ", " : ", 1)
                    parts.append(t)
                if parts:
                    detail_data["figure_panel"] = " | ".join(parts)
                else:
                    success_el = panel_el.locator(".success")
                    detail_data["figure_panel"] = success_el.inner_text().strip() if success_el.count() > 0 else "-"
            # figure_frame: .figure-frame .cont.change-status 텍스트
            frame_el = body.locator(".figure-frame .cont.change-status")
            if frame_el.count() > 0:
                detail_data["figure_frame"] = frame_el.inner_text().strip() or "-"

        # 6. 두 번째 .vip-cont: aqi_list, aqi_notice_list, tire_summery
        second_cont = page.locator(".vip-body .vip-con .con-section.aqi .vip-cont").nth(1)
        if second_cont.count() > 0:
            # aqi_list: .vip-aqi-list .aqi-list → "title : status | ..."
            aqi_items = second_cont.locator(".vip-aqi-form .vip-aqi-box .vip-aqi-cont .vip-aqi-list.vip-aqi-group .aqi-list")
            if aqi_items.count() > 0:
                parts = []
                for i in range(aqi_items.count()):
                    try:
                        li = aqi_items.nth(i)
                        title = li.locator(".title").inner_text(timeout=t_detail).strip()
                        status = li.locator(".status").inner_text(timeout=t_detail).strip()
                        parts.append(f"{title} : {status}")
                    except Exception:
                        continue
                detail_data["aqi_list"] = " | ".join(parts) if parts else "-"
            # aqi_notice_list: .aqi-notice-list-txt → "title : txt | ..."
            notice_items = second_cont.locator(".vip-aqi-notice-form .vip-aqi-notice-box .vip-aqi-notice-cont .vip-aqi-notice-list .aqi-notice-list .aqi-notice-list-txt")
            if notice_items.count() > 0:
                parts = []
                for i in range(notice_items.count()):
                    try:
                        div = notice_items.nth(i)
                        title = div.locator(".title").inner_text(timeout=t_detail).strip()
                        txt = div.locator(".txt").inner_text(timeout=t_detail).strip()
                        parts.append(f"{title} : {txt}")
                    except Exception:
                        continue
                detail_data["aqi_notice_list"] = " | ".join(parts) if parts else "-"
            # tire_summery: .aqi-tire .cont.aqi-tire-tread 내 front left, back left, back right, front right
            tire_cont = second_cont.locator(".aqi-another-form .aqi-another-box .aqi-tire .cont.aqi-tire-tread")
            if tire_cont.count() > 0:
                def _tire_parts(block):
                    parts = []
                    try:
                        tread = block.locator(".tire-tread .trad-txt")
                        date = block.locator(".tire-date .date-txt")
                        if tread.count() > 0:
                            parts.append("트레드 깊이 : " + tread.inner_text(timeout=t_detail).strip())
                        if date.count() > 0:
                            parts.append("제조일 : " + date.inner_text(timeout=t_detail).strip())
                    except Exception:
                        pass
                    return " | ".join(parts) if parts else "-"
                fl = tire_cont.locator(".tire-summery.front.left")
                bl = tire_cont.locator(".tire-summery.back.left")
                br = tire_cont.locator(".tire-summery.back.right")
                fr = tire_cont.locator(".tire-summery.front.right")
                if fl.count() > 0: detail_data["tire_summery_front_left"] = _tire_parts(fl)
                if bl.count() > 0: detail_data["tire_summery_back_left"] = _tire_parts(bl)
                if br.count() > 0: detail_data["tire_summery_back_right"] = _tire_parts(br)
                if fr.count() > 0: detail_data["tire_summery_front_right"] = _tire_parts(fr)

    except Exception as e:
        logger.error(f"상세 페이지 추출 에러 ({product_id}): {e}")
    
    return detail_data

def run_full_crawler():
    logger = setup_logger()
    now = datetime.now()
    pnttm, create_dt_full = now.strftime("%Y%m%d"), now.strftime("%Y%m%d%H%M")
    
    # [테스트] 목록·상세 모두 N페이지까지만 수집 (전체 수집 시 None 유지)
    TEST_PAGE_LIMIT = 1   # ← 테스트 시 이 줄 주석 해제하고 아래 줄 주석 처리
    # TEST_PAGE_LIMIT = None  # ← 전체 수집 시 유지, 테스트 시 위 줄 사용

    result_dir = Path("/home/limhayoung/used_car_crawler/result/reborncar")
    result_dir.mkdir(parents=True, exist_ok=True)
    list_path = result_dir / "reborncar_list.csv"
    detail_path = result_dir / "reborncar_detail.csv"
    if list_path.exists(): list_path.unlink()
    if detail_path.exists(): detail_path.unlink()

    list_headers = [
        "model_sn", "productId", "car_type", "boname", "gradename", "year", "carnavi", "car_seat",
        "car_main_pay", "amtsel", "status", "copytext", "endtimedeal", "date_crtr_pnttm", "create_dt"
    ]
    detail_headers = [
        "model_sn", "productId", "car_number", "gear_box", "car_color", "car_fuel", "plan_pay",
        "car_new_price", "accident", "flood", "change_use", "comp_new_car",
        "smell_level", "refund", "options", "additional_options",
        "figure_panel", "figure_frame",
        "aqi_list", "aqi_notice_list",
        "tire_summery_front_left", "tire_summery_back_left", "tire_summery_back_right", "tire_summery_front_right",
        "date_crtr_pnttm", "create_dt"
    ]

    car_counter = 1

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(user_agent="Mozilla/5.0...", viewport={'width': 1900, 'height': 1000})
        page = context.new_page()
        detail_page = context.new_page() # 상세페이지용 별도 탭

        try:
            logger.info("리본카 목록 페이지 접속...")
            page.goto("https://www.reborncar.co.kr/smartbuy/SB1001.rb")
            page.wait_for_selector("ul.lp-box.smartbuy-lp", timeout=60000)

            # 차종 필터: .check-btn-box.car-type-filter 내 checkbox 버튼들
            car_type_filter_box = page.locator("#wrap .lp-section .lp-filter .lp-filter-form .lp-filter-box .lp-filter-con .check-btn-box.car-type-filter")
            car_type_buttons = car_type_filter_box.locator(".check-btn.check-btn-s.filter-chk") if car_type_filter_box.count() > 0 else page.locator(".check-btn-box.car-type-filter .check-btn.check-btn-s.filter-chk")
            n_car_types = car_type_buttons.count()
            if n_car_types == 0:
                n_car_types = 1  # 필터 없으면 전체 1번만 수집
                car_type_labels = [""]
            else:
                car_type_labels = []
                for i in range(n_car_types):
                    try:
                        lbl = car_type_buttons.nth(i).inner_text().strip()
                        car_type_labels.append(lbl or f"타입{i+1}")
                    except Exception:
                        car_type_labels.append(f"타입{i+1}")

            for car_type_idx in range(n_car_types):
                current_car_type = car_type_labels[car_type_idx]
                if n_car_types > 1:
                    try:
                        car_type_buttons.nth(car_type_idx).click()
                        page.wait_for_timeout(2500)
                        logger.info(f"차종 필터 선택: {current_car_type}")
                    except Exception as e:
                        logger.warning(f"차종 필터 클릭 실패 ({current_car_type}): {e}")
                        continue

                while True:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(3000)

                    active_el = page.locator("li.pagination-con.page-num.active")
                    try: current_page = int(active_el.inner_text() or "1")
                    except: current_page = 1

                    items = page.locator("ul.lp-box.smartbuy-lp > li.lp-con.swiper-slide:not(.lp-banner):not(.swiper-slide-duplicate)").all()
                    logger.info(f"[{current_car_type}] 현재 {current_page}페이지 수집 중... (매물 {len(items)}개)")
                    detail_count_this_page = 0

                    for item in items:
                        try:
                            # 목록 데이터 추출
                            v_product_id = ""
                            href_value = item.locator("a.lp-thumnail").get_attribute("href")
                            if href_value:
                                match = re.search(r"fnDetailMove\('([^']+)'", href_value)
                                if match: v_product_id = match.group(1)

                            v_status = item.locator(".lp-status").inner_text().strip() or "판매중"

                            # 목록에서 가격 (상태별)
                            v_finamt, v_amtsel = "-", "-"
                            if v_status in ["판매중", "계약중", "상담중"]:
                                pay_b = item.locator(".car-pay .pay b")
                                if pay_b.count() > 0:
                                    v_finamt = pay_b.inner_text().strip() + "만원"
                                discount_el = item.locator(".car-pay .discount")
                                v_amtsel = discount_el.inner_text().strip() if discount_el.count() > 0 else "0"
                            elif v_status == "준비중":
                                v_finamt, v_amtsel = "0만원", "-"
                            elif v_status == "판매완료":
                                v_finamt, v_amtsel = "판매완료", "-"

                            # 연식/내비/좌석
                            summary_lis = item.locator(".lp-summery li").all()
                            v_year = summary_lis[0].inner_text().strip() if len(summary_lis) > 0 else ""
                            v_navi = summary_lis[1].inner_text().strip() if len(summary_lis) > 1 else ""
                            v_seat = summary_lis[2].inner_text().strip() if len(summary_lis) > 2 else ""

                            # 타임딜
                            is_td = item.locator(".lp-timedeal").count() > 0
                            v_copy = "타임딜" if is_td else ""
                            v_endtd = item.locator(".lp-timedeal-count").inner_text().strip() if is_td else ""

                            # list.csv 행 (목록 데이터만, car_type=현재 차종 필터)
                            list_row = {
                                "model_sn": car_counter, "productId": v_product_id, "car_type": current_car_type,
                                "boname": item.locator(".lp-car-name").inner_text().strip(),
                                "gradename": item.locator(".lp-car-trim").inner_text().strip(),
                                "year": v_year, "carnavi": v_navi, "car_seat": v_seat,
                                "car_main_pay": v_finamt, "amtsel": v_amtsel, "status": v_status,
                                "copytext": v_copy, "endtimedeal": v_endtd,
                                "date_crtr_pnttm": pnttm, "create_dt": create_dt_full
                            }
                            with open(list_path, "a", newline="", encoding="utf-8-sig") as fl:
                                wl = csv.DictWriter(fl, fieldnames=list_headers)
                                if car_counter == 1:
                                    wl.writeheader()
                                wl.writerow(list_row)

                            # detail.csv 행 (상세 데이터, 준비중/판매완료 제외 시에만 수집)
                            if v_product_id and v_status not in ["준비중", "판매완료"]:
                                v_details = get_detail_info(detail_page, v_product_id, logger)
                                detail_row = {"model_sn": car_counter, "productId": v_product_id}
                                detail_row.update({k: v_details.get(k, "-") for k in detail_headers if k not in ("model_sn", "productId")})
                                detail_row["date_crtr_pnttm"] = pnttm
                                detail_row["create_dt"] = create_dt_full
                                with open(detail_path, "a", newline="", encoding="utf-8-sig") as fd:
                                    wd = csv.DictWriter(fd, fieldnames=detail_headers)
                                    if car_counter == 1:
                                        wd.writeheader()
                                    wd.writerow(detail_row)
                                detail_count_this_page += 1
                            else:
                                # 상세 미수집 시에도 productId/model_sn만 있는 행 추가 (조인용)
                                detail_row = {k: "-" for k in detail_headers}
                                detail_row["model_sn"] = car_counter
                                detail_row["productId"] = v_product_id
                                detail_row["date_crtr_pnttm"] = pnttm
                                detail_row["create_dt"] = create_dt_full
                                with open(detail_path, "a", newline="", encoding="utf-8-sig") as fd:
                                    wd = csv.DictWriter(fd, fieldnames=detail_headers)
                                    if car_counter == 1:
                                        wd.writeheader()
                                    wd.writerow(detail_row)

                            car_counter += 1
                        except Exception as e:
                            logger.error(f"항목 수집 실패: {e}")

                    logger.info(f"목록 {current_page}페이지 수집 완료 → list.csv 저장 (이번 페이지 {len(items)}건)")
                    logger.info(f"상세 {current_page}페이지 수집 완료 → detail.csv 저장 (이번 페이지 {detail_count_this_page}건)")

                    # 페이지네이션: 다음 번호 있으면 클릭, 없으면 다음 블록(>) → 둘 다 없으면 수집 종료
                    # (테스트용: TEST_PAGE_LIMIT 설정 시 N페이지 도달하면 여기서 break)
                    if TEST_PAGE_LIMIT is not None and current_page >= TEST_PAGE_LIMIT:
                        break
                    prev_page = current_page
                    next_page_link = page.locator("li.pagination-con.page-num.active + li.pagination-con.page-num:not(.next):not(.prev) a").first
                    if next_page_link.count() > 0:
                        next_page_link.evaluate("el => el.click()")
                        page.wait_for_timeout(3000)
                    else:
                        next_grp = page.locator("li.pagination-con.next:not(.disabled) a").first
                        if next_grp.count() > 0:
                            next_grp.evaluate("el => el.click()")
                            page.wait_for_timeout(4000)
                            page.wait_for_selector("li.pagination-con.page-num.active", timeout=8000)
                        else:
                            break
                    page.wait_for_timeout(1500)
                    try:
                        new_active = page.locator("li.pagination-con.page-num.active")
                        new_page = int(new_active.inner_text() or "0")
                        if new_page == prev_page:
                            page.wait_for_timeout(3000)
                    except Exception:
                        pass

        finally:
            browser.close()

if __name__ == "__main__":
    run_full_crawler()