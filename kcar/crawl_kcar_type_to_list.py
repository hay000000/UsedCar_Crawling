# -*- coding: utf-8 -*-
"""
K Car 검색 페이지(https://www.kcar.com/bc/search)에서
차종·브랜드 목록 수집 및 검색 결과 리스트(차량 목록) 수집.
"""
import csv
import logging
import re
from pathlib import Path

from playwright.sync_api import sync_playwright


def _extract_product_id_from_img_src(src):
    """
    이미지 src에서 product_id 추출.
    - 3dcarpicture/.../61310405_1/main/ 또는 61322118_2/main/ → 숫자만 (61310405, 61322118)
    - kcarM_61320099_045.jpg → 61320099
    """
    if not src:
        return ""
    # 숫자_1, 숫자_2 등 /main/ 앞 숫자만
    m = re.search(r"/(\d+)_\d+/main/", src)
    if m:
        return m.group(1)
    m = re.search(r"kcarM_(\d+)_", src)
    if m:
        return m.group(1)
    return ""


def _extract_product_id_from_href(href):
    """상세 링크 href에서 product_id 추출. 예: /bc/detail/61321299 → 61321299"""
    if not href:
        return ""
    m = re.search(r"/detail/(\d+)(?:\?|$|/)", href)
    if m:
        return m.group(1)
    m = re.search(r"detail[/_]?(\d{5,})", href, re.I)
    if m:
        return m.group(1)
    return ""


def setup_logger():
    log_dir = Path(__file__).resolve().parent.parent / "logs" / "kcar"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "kcar_type_to_list.log"
    logger = logging.getLogger("KCarTypeList")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(formatter)
        logger.addHandler(sh)
    return logger


def run_kcar_car_type_list(page, result_dir: Path, logger):
    """
    K Car 검색 페이지에서 차종 목록 수집.
    body #__nuxt #__layout .Container .searchWrap ... .kcarSnb 내
    [aria-label="차종"] 하위 role="tabpanel" > .el-collapse-item__content > .menuItemList >
    .el-checkbox-group > .el-checkbox > .el-checkbox__label 텍스트 수집.
    """
    csv_path = result_dir / "kcar_car_type_list.csv"
    if csv_path.exists():
        csv_path.unlink()
    headers = ["car_type_sn", "car_type_name"]
    url = "https://www.kcar.com/bc/search"

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(3000)

        # 약관/동의 팝업 확인 버튼 처리
        for _ in range(3):
            try:
                confirm_btn = page.locator("button:has-text('확인')").first
                if confirm_btn.is_visible(timeout=1000):
                    confirm_btn.click()
                    page.wait_for_timeout(800)
            except Exception:
                break

        # 사이드 SNB 로딩 대기 (차종이 첫 번째 아코디언인 경우 많음)
        page.wait_for_selector(".kcarSnb, .kcarSnbWrap, .menuItemList", timeout=20000)
        page.wait_for_timeout(1500)

        # 차종 영역 펼치기: aria-label="차종" 헤더 클릭
        try:
            header = page.locator('[aria-label="차종"]').first
            if header.is_visible(timeout=2000):
                header.click()
                page.wait_for_timeout(1000)
        except Exception:
            pass

        labels = None
        n = 0

        # 1) 차종 탭 패널 내 .el-checkbox__label (aria-label 차종 하위)
        try:
            section = page.locator(
                '.kcarSnb .el-collapse-item:has([aria-label="차종"]) .menuItemList .el-checkbox-group .el-checkbox'
            )
            section.first.wait_for(state="visible", timeout=5000)
            labels = section.locator(".el-checkbox__label")
            n = labels.count()
        except Exception:
            pass

        # 2) 첫 번째 .menuItemList 내 차종 체크박스 (차종이 첫 번째 메뉴인 경우)
        if n == 0:
            try:
                first_menu = page.locator(".kcarSnb .menuItemList").first
                first_menu.wait_for(state="visible", timeout=5000)
                labels = first_menu.locator(".el-checkbox .el-checkbox__label")
                n = labels.count()
            except Exception:
                pass

        # 3) .kcarSnb 내 모든 .el-checkbox__label 중 첫 번째 그룹만 (role=group 첫 번째)
        if n == 0:
            try:
                first_group = page.locator(".kcarSnb .el-checkbox-group.chkGroup").first
                first_group.wait_for(state="visible", timeout=5000)
                labels = first_group.locator(".el-checkbox .el-checkbox__label")
                n = labels.count()
            except Exception:
                pass

        if n == 0:
            logger.warning("차종 라벨 요소를 찾지 못했습니다.")
            return

        logger.info("============================================================")
        logger.info("K Car 차종(car_type) 계층 데이터 수집 시작")
        logger.info("============================================================")
        logger.info("총 %d개 차종 데이터 수집 시작", n)

        car_type_sn = 1
        wrote_any = False
        for i in range(n):
            name = labels.nth(i).inner_text().strip()
            if not name:
                continue

            # 한 종 발견될 때마다 바로 CSV append
            first_write = not csv_path.exists()
            with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=headers)
                if first_write:
                    w.writeheader()
                w.writerow({"car_type_sn": car_type_sn, "car_type_name": name})

            logger.info("[%d/%d] 차종 처리 중: %s", car_type_sn, n, name)
            for h in logger.handlers:
                h.flush()
            car_type_sn += 1
            wrote_any = True

        if wrote_any:
            logger.info("============================================================")
            logger.info("✅ 수집 완료! 파일: %s", csv_path)
            logger.info("총 수집 차종 수: %s개", f"{car_type_sn - 1:,}")
        else:
            logger.warning("차종 데이터 없음.")
    except Exception as e:
        logger.error("차종 수집 오류: %s", e, exc_info=True)


def _model_list_format(text):
    """model_list 값: 뒤에서 첫 번째 '(' 기준으로 '앞부분|(괄호내용)' 형태로 변환. 예: '더 뉴 i40 (15~19년)' → '더 뉴 i40|(15~19년)'"""
    if not text or "(" not in text:
        return (text or "").strip()
    last_open = text.rfind("(")
    prefix = text[:last_open].strip()
    suffix = text[last_open:].strip()
    if not prefix:
        return text.strip()
    return f"{prefix}|{suffix}"


def _collect_brand_depth1_block(page, depth1_block, depth_1_value, csv_path, headers, logger, model_sn_ref, start_index=0, total_brands=0):
    """한 개의 depth1 블록(국산 또는 수입) 내부 depth2→depth3→depth4 수집 후 CSV에 append. model_sn_ref는 [1] 형태 리스트로 전달, 행 추가 시 1,2,3... 자동 증가."""
    def append_row(row):
        row["model_sn"] = model_sn_ref[0]
        model_sn_ref[0] += 1
        with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=headers).writerow(row)

    logger.info("  → [%s] depth2 목록 조회 중...", depth_1_value)
    for h in logger.handlers:
        h.flush()
    try:
        depth1_block.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
    except Exception:
        pass
    # depth2는 브랜드(현대, 기아, 제네시스 등)만 대상 → 직계 li만 사용 (하위 depth3/depth4 li 제외)
    depth2_lis = depth1_block.locator(".depth2 > ul > li")
    if depth2_lis.count() == 0:
        depth2_lis = depth1_block.locator(".depth2 > li")
    if depth2_lis.count() == 0:
        depth2_lis = depth1_block.locator(".depth2 li")
    try:
        depth2_lis.first.wait_for(state="visible", timeout=10000)
    except Exception as e:
        logger.warning("  → [%s] depth2 요소 대기 실패: %s", depth_1_value, e)
        for h in logger.handlers:
            h.flush()
        return 0
    depth2_count = depth2_lis.count()
    logger.info("  → [%s] depth2 %d개 발견, 수집 시작...", depth_1_value, depth2_count)
    for h in logger.handlers:
        h.flush()
    row_count = 0

    for i in range(depth2_count):
        logger.info("  → [%s] %d/%d 번째 브랜드 요소 처리 중...", depth_1_value, i + 1, depth2_count)
        for h in logger.handlers:
            h.flush()
        d2_li = depth2_lis.nth(i)
        try:
            d2_li.scroll_into_view_if_needed()
            page.wait_for_timeout(200)
        except Exception:
            pass
        depth_2 = ""
        for sel in (".el-checkbox__label", "label.el-checkbox__label", "label", ".el-checkbox label"):
            try:
                el = d2_li.locator(sel).first
                el.wait_for(state="visible", timeout=2000)
                depth_2 = (el.inner_text(timeout=2000) or el.text_content() or "").strip()
                if depth_2:
                    break
            except Exception:
                continue
        if not depth_2:
            logger.warning("  → [%s] %d번째 브랜드 이름 읽기 실패 (모든 셀렉터 시도)", depth_1_value, i + 1)
            for h in logger.handlers:
                h.flush()
            continue

        current_num = start_index + i + 1
        row_count_this_brand = 0
        if total_brands > 0:
            logger.info("[%d/%d] 브랜드 처리 중 [%s]: %s", current_num, total_brands, depth_1_value, depth_2)
        logger.info("  → [%s] '%s' 펼치는 중...", depth_1_value, depth_2)
        for h in logger.handlers:
            h.flush()

        def _wait_depth3_visible():
            try:
                d2_li.locator(".depth3").first.wait_for(state="visible", timeout=6000)
                return True
            except Exception:
                pass
            try:
                depth1_block.locator(".depth3").first.wait_for(state="visible", timeout=6000)
                return True
            except Exception:
                pass
            return False

        expanded = False
        try:
            d2_li.scroll_into_view_if_needed()
            page.wait_for_timeout(400)
            label_el = d2_li.locator("label").first
            label_el.click()
            page.wait_for_timeout(1200)
            if _wait_depth3_visible():
                expanded = True
        except Exception:
            pass
        if not expanded:
            try:
                d2_li.locator(".el-checkbox").first.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
                d2_li.locator(".el-checkbox").first.click()
                page.wait_for_timeout(1200)
                if _wait_depth3_visible():
                    expanded = True
            except Exception:
                pass
        if not expanded:
            try:
                page.wait_for_timeout(600)
                d2_li.locator("label").first.click(force=True)
                page.wait_for_timeout(1500)
                if _wait_depth3_visible():
                    expanded = True
            except Exception:
                pass
        if not expanded:
            try:
                d2_li.evaluate("el => el.querySelector('label')?.click()")
                page.wait_for_timeout(1500)
                if _wait_depth3_visible():
                    expanded = True
            except Exception:
                pass
        if not expanded:
            logger.warning("  → [%s] '%s' 펼치기 실패, 다음 브랜드로", depth_1_value, depth_2)
            for h in logger.handlers:
                h.flush()
            continue

        # depth_3: 클릭한 depth2 li 내부의 depth3 먼저, 없으면 depth1_block 전체에서
        depth3_container = d2_li.locator("ul.depth3").first
        depth3_lis = depth3_container.locator("> li")
        depth3_count = depth3_lis.count()
        if depth3_count == 0:
            depth3_container = d2_li.locator(".depth3").first
            depth3_lis = depth3_container.locator("> li")
            depth3_count = depth3_lis.count()
        if depth3_count == 0:
            depth3_container = depth1_block.locator("ul.depth3").first
            depth3_lis = depth3_container.locator("> li")
            depth3_count = depth3_lis.count()
        if depth3_count == 0:
            depth3_container = depth1_block.locator(".depth3").first
            depth3_lis = depth3_container.locator("> li")
            depth3_count = depth3_lis.count()
        if depth3_count == 0:
            depth3_lis = depth1_block.locator(".depth3 li")
            depth3_count = depth3_lis.count()
        logger.info("  → [%s] '%s' 하위 %d개 모델 수집 중...", depth_1_value, depth_2, depth3_count)
        for h in logger.handlers:
            h.flush()

        for j in range(depth3_count):
            d3_li = depth3_lis.nth(j)
            try:
                d3_li.scroll_into_view_if_needed()
                page.wait_for_timeout(100)
            except Exception:
                pass
            depth_3 = ""
            for sel in (".el-checkbox__label", "label.el-checkbox__label", "label", ".el-checkbox label"):
                try:
                    el = d3_li.locator(sel).first
                    el.wait_for(state="visible", timeout=1000)
                    depth_3 = (el.inner_text(timeout=1000) or el.text_content() or "").strip()
                    if depth_3:
                        break
                except Exception:
                    continue
            if not depth_3:
                continue

            try:
                d3_li.locator("label").first.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
                d3_li.locator("label").first.click()
                page.wait_for_timeout(1200)
                # 현재 클릭한 depth_3 li 내부의 depth4 대기 (각 모델 li 안에 ul.depth4가 있음)
                d3_li.locator("ul.depth4 > li .el-checkbox__label").first.wait_for(state="visible", timeout=15000)
                page.wait_for_timeout(600)
            except Exception:
                try:
                    d3_li.locator(".el-checkbox").first.scroll_into_view_if_needed()
                    page.wait_for_timeout(300)
                    d3_li.locator(".el-checkbox").first.click()
                    page.wait_for_timeout(1200)
                    d3_li.locator("ul.depth4 > li .el-checkbox__label").first.wait_for(state="visible", timeout=15000)
                    page.wait_for_timeout(600)
                except Exception:
                    try:
                        page.wait_for_timeout(800)
                        d3_li.locator("label").first.click()
                        page.wait_for_timeout(1500)
                        d3_li.locator("ul.depth4 > li .el-checkbox__label").first.wait_for(state="visible", timeout=18000)
                        page.wait_for_timeout(500)
                    except Exception:
                        append_row({"depth_1": depth_1_value, "brand_list": depth_2, "car_list": depth_3, "model_list": "-"})
                        row_count += 1
                        row_count_this_brand += 1
                        logger.info("    → CSV 1건 추가: [%s] %s > %s > -", depth_1_value, depth_2, depth_3)
                        for h in logger.handlers:
                            h.flush()
                        try:
                            d3_li.locator("label").first.click()
                            page.wait_for_timeout(200)
                        except Exception:
                            pass
                        continue

            # depth_4: 현재 클릭한 depth_3 li 내부의 ul.depth4 > li만 수집 (i30 (PD) (16~20년), 더 뉴 i30 (15~16년) 등)
            depth4_container = d3_li.locator("ul.depth4").first
            depth4_lis = depth4_container.locator("> li")
            depth4_count = depth4_lis.count()
            if depth4_count == 0:
                depth4_container = d3_li.locator(".depth4").first
                depth4_lis = depth4_container.locator("> li")
                depth4_count = depth4_lis.count()
            if depth4_count == 0:
                logger.warning("  → [%s] '%s' > '%s' depth4 li 0개", depth_1_value, depth_2, depth_3)
                for h in logger.handlers:
                    h.flush()
                page.wait_for_timeout(500)
                depth4_lis = d3_li.locator("ul.depth4 > li")
                depth4_count = depth4_lis.count()
            depth4_added = 0
            for k in range(depth4_count):
                try:
                    d4_li = depth4_lis.nth(k)
                    d4_li.scroll_into_view_if_needed()
                    page.wait_for_timeout(50)
                except Exception:
                    pass
                depth_4 = ""
                for sel in (".el-checkbox__label", "label.el-checkbox__label", "label", ".el-checkbox label"):
                    try:
                        el = depth4_lis.nth(k).locator(sel).first
                        el.wait_for(state="visible", timeout=800)
                        depth_4 = (el.inner_text(timeout=800) or el.text_content() or "").strip()
                        if depth_4:
                            break
                    except Exception:
                        continue
                if not depth_4:
                    continue
                append_row({
                    "depth_1": depth_1_value,
                    "brand_list": depth_2,
                    "car_list": depth_3,
                    "model_list": _model_list_format(depth_4),
                })
                row_count += 1
                row_count_this_brand += 1
                depth4_added += 1
                logger.info("    → CSV 1건 추가: [%s] %s > %s > %s", depth_1_value, depth_2, depth_3, depth_4)
                for h in logger.handlers:
                    h.flush()

            if depth4_added == 0 and depth_3:
                append_row({"depth_1": depth_1_value, "brand_list": depth_2, "car_list": depth_3, "model_list": "-"})
                row_count += 1
                row_count_this_brand += 1
                logger.info("    → CSV 1건 추가: [%s] %s > %s > (하위 없음)", depth_1_value, depth_2, depth_3)
                for h in logger.handlers:
                    h.flush()

            if depth4_added > 0:
                logger.info("    → [%s] '%s' 하위 %d건 수집됨", depth_1_value, depth_3, depth4_added)
                for h in logger.handlers:
                    h.flush()

            try:
                d3_li.locator("label").first.click()
                page.wait_for_timeout(300)
            except Exception:
                pass

        logger.info("  → [%s] '%s' 수집 완료 (%d건)", depth_1_value, depth_2, row_count_this_brand)
        for h in logger.handlers:
            h.flush()

        try:
            d2_li.locator("label").first.click()
            page.wait_for_timeout(400)
        except Exception:
            pass

    return row_count


def run_kcar_brand_list(page, result_dir: Path, logger):
    """
    제조사/모델 영역(aria-label="제조사/모델")에서
    첫 번째 depth1=국산, 두 번째 depth1=수입 각각에 대해
    depth2 → depth3 → depth4 계층을 클릭하며 수집 (국산 먼저, 수입 후) → brand_list.csv
    """
    csv_path = result_dir / "kcar_brand_list.csv"
    if csv_path.exists():
        csv_path.unlink()
    headers = ["model_sn", "depth_1", "brand_list", "car_list", "model_list"]
    url = "https://www.kcar.com/bc/search"

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(3000)

        for _ in range(3):
            try:
                confirm_btn = page.locator("button:has-text('확인')").first
                if confirm_btn.is_visible(timeout=1000):
                    confirm_btn.click()
                    page.wait_for_timeout(800)
            except Exception:
                break

        page.wait_for_selector(".kcarSnb", timeout=20000)
        page.wait_for_timeout(1500)

        # 제조사/모델 아코디언 헤더 클릭 후 컨텐츠 로딩 대기
        try:
            header = page.locator('[aria-label="제조사/모델"]').first
            header.wait_for(state="visible", timeout=5000)
            header.click()
            page.wait_for_timeout(2500)
        except Exception:
            pass

        # 스크롤하여 제조사/모델 영역이 보이도록
        try:
            snb = page.locator(".kcarSnb").first
            if snb.count() > 0:
                snb.scroll_into_view_if_needed()
                page.wait_for_timeout(800)
        except Exception:
            pass

        section = None
        for selector in (
            '.kcarSnb .el-collapse-item:has([aria-label="제조사/모델"]) .el-collapse-item__content .modelList',
            '.kcarSnb .modelList',
            '.el-collapse-item__content .modelList',
            '.modelList',
        ):
            try:
                loc = page.locator(selector).first
                loc.wait_for(state="visible", timeout=8000)
                section = page.locator(selector)
                if section.locator(".depth1").count() > 0:
                    break
            except Exception:
                continue
        if section is None:
            try:
                section = page.locator(".modelList")
                section.first.wait_for(state="visible", timeout=8000)
            except Exception:
                raise RuntimeError("제조사/모델 .modelList 영역을 찾을 수 없습니다.")

        depth1_blocks = section.locator(".depth1")
        depth1_count = depth1_blocks.count()
        if depth1_count == 0:
            logger.warning("제조사/모델 .depth1을 찾지 못했습니다.")
            return

        depth_1_labels = ("국산", "수입")

        def _count_depth2_direct(block):
            c = block.locator(".depth2 > ul > li").count()
            if c > 0:
                return c
            c = block.locator(".depth2 > li").count()
            if c > 0:
                return c
            return block.locator(".depth2 li").count()

        # 수입(두 번째 depth1) 블록이 접혀 있을 수 있으므로, 먼저 펼치기
        if depth1_count >= 2:
            try:
                depth1_block_수입 = depth1_blocks.nth(1)
                depth1_block_수입.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                for _ in range(3):
                    cnt = _count_depth2_direct(depth1_block_수입)
                    if cnt > 0:
                        break
                    try:
                        depth1_block_수입.locator("label").first.click()
                        page.wait_for_timeout(1500)
                    except Exception:
                        try:
                            page.locator("text=수입").first.click()
                            page.wait_for_timeout(1500)
                        except Exception:
                            pass
                    page.wait_for_timeout(800)
            except Exception as e:
                logger.warning("수입 섹션 펼치기 시도 중 오류(무시하고 진행): %s", e)

        # 총 브랜드(depth2) 개수 미리 계산 - 직계 li만 (국산·수입 동일)
        depth2_counts = []
        for idx in range(min(depth1_count, len(depth_1_labels))):
            depth2_counts.append(_count_depth2_direct(depth1_blocks.nth(idx)))
        total_brands = sum(depth2_counts)

        logger.info("============================================================")
        logger.info("K Car 제조사/모델(brand) 계층 데이터 수집 시작 (국산 → 수입)")
        logger.info("============================================================")
        logger.info("총 %d개 브랜드 데이터 수집 시작", total_brands)
        # CSV 파일 즉시 생성 (헤더만) → 진행 중에도 파일 존재·확인 가능
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=headers).writeheader()
        logger.info("CSV 생성됨: %s (데이터 수집 중 추가됩니다)", csv_path)
        for h in logger.handlers:
            h.flush()

        total_rows = 0
        start_index = 0
        model_sn_ref = [1]  # 1, 2, 3 ... 행마다 증가
        for idx in range(min(depth1_count, len(depth_1_labels))):
            depth_1_value = depth_1_labels[idx]  # 국산 또는 수입
            depth1_block = depth1_blocks.nth(idx)
            if depth2_counts[idx] == 0:
                if idx == 1:
                    try:
                        depth1_block.scroll_into_view_if_needed()
                        page.wait_for_timeout(1500)
                        depth2_counts[idx] = _count_depth2_direct(depth1_block)
                    except Exception:
                        pass
                if depth2_counts[idx] == 0:
                    logger.info("[%s] depth2 항목 없음, 스킵", depth_1_value)
                    continue
            if idx == 1:
                try:
                    depth1_block.scroll_into_view_if_needed()
                    page.wait_for_timeout(600)
                except Exception:
                    pass
            logger.info("------------------------------------------------------------")
            logger.info("[%s] 데이터 수집 시작 (총 %d개 브랜드)", depth_1_value, depth2_counts[idx])
            logger.info("------------------------------------------------------------")
            n = _collect_brand_depth1_block(
                page, depth1_block, depth_1_value, csv_path, headers, logger, model_sn_ref,
                start_index=start_index, total_brands=total_brands,
            )
            total_rows += n
            logger.info("[%s] 데이터 수집 완료: %d건", depth_1_value, n)
            start_index += depth2_counts[idx]

        logger.info("============================================================")
        logger.info("✅ 수집 완료! 파일: %s", csv_path)
        logger.info("총 수집 모델 수: %s개", f"{total_rows:,}")
    except Exception as e:
        logger.error("제조사/모델 수집 오류: %s", e, exc_info=True)


def run_kcar_list(page, result_dir: Path, logger):
    """
    검색 결과 리스트 페이지에서 .carListWrap > .carListBox 별로
    product_id, car_name, car_exp, car_pay_meth, release_dt, car_navi, car_fuel, local_dos, info_tooltip 수집 후
    result/kcar/kcar_list.csv 저장.
    """
    csv_path = result_dir / "kcar_list.csv"
    if csv_path.exists():
        csv_path.unlink()
    headers = [
        "model_sn", "product_id", "car_name", "car_exp", "car_pay_meth",
        "release_dt", "car_navi", "car_fuel", "local_dos", "info_tooltip",
    ]
    url = "https://www.kcar.com/bc/search"

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(3000)

        for _ in range(3):
            try:
                confirm_btn = page.locator("button:has-text('확인')").first
                if confirm_btn.is_visible(timeout=2000):
                    confirm_btn.click()
                    page.wait_for_timeout(1500)
            except Exception:
                break

        # 첫 번째 resultCnt 영역(검색 결과 리스트) 내의 carListBox만 대상
        page.wait_for_selector(".resultCnt .carListWrap .carListBox", timeout=60000)
        page.wait_for_timeout(2000)

        result_cnt = page.locator(".resultCnt").first
        boxes = result_cnt.locator(".carListWrap .carListBox")

        # 동적으로 리스트가 추가 로딩될 수 있으므로, 개수가 더 이상 늘어나지 않을 때까지 잠시 대기
        prev_count = -1
        stable_rounds = 0
        for _ in range(10):  # 최대 약 10초
            cur = boxes.count()
            if cur == prev_count and cur > 0:
                stable_rounds += 1
                if stable_rounds >= 2:
                    break
            else:
                stable_rounds = 0
                prev_count = cur
            page.wait_for_timeout(1000)

        n_boxes = boxes.count()
        logger.info("검색 결과 리스트 수집: carListBox %d개", n_boxes)

        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(headers)

            model_sn = 0
            for i in range(n_boxes):
                box = boxes.nth(i)

                # 화면에 보이게 해서 지연 로딩 이미지 src 채워지도록
                try:
                    box.scroll_into_view_if_needed()
                    page.wait_for_timeout(200)
                except Exception:
                    pass

                # product_id: 1) .carListImg > a.nuxt-link-exact-active.nuxt-link-active > img src/data-src
                #              2) 위가 없으면 .carListImg 내 다른 nuxt-link img / img
                #              3) 그래도 없으면 상세 링크 href에서
                product_id = ""
                try:
                    # 1순위: 요구사항대로 nuxt-link-exact-active.nuxt-link-active 하위 img
                    img = box.locator(".carListImg a.nuxt-link-exact-active.nuxt-link-active img").first
                    if not img.count():
                        # 2순위: nuxt-link 클래스가 있는 다른 a 태그 하위 img
                        img = box.locator(".carListImg a[class*='nuxt-link'] img").first
                    if not img.count():
                        # 3순위: .carListImg 내 첫 번째 img
                        img = box.locator(".carListImg img").first

                    if img.count():
                        try:
                            img.wait_for(state="visible", timeout=1000)
                            page.wait_for_timeout(300)
                        except Exception:
                            pass
                        src = img.get_attribute("src") or img.get_attribute("data-src") or ""
                        product_id = _extract_product_id_from_img_src(src or "")
                except Exception:
                    pass
                if not product_id:
                    try:
                        for link_sel in (".carListImg a[href*='detail']", "a[href*='detail']", "a[href*='/bc/']"):
                            link = box.locator(link_sel).first
                            if link.count():
                                href = link.get_attribute("href") or ""
                                product_id = _extract_product_id_from_href(href)
                                if product_id:
                                    break
                    except Exception:
                        pass

                # car_name: .detailInfo.srchTimedeal .carName .carTit
                car_name = ""
                try:
                    el = box.locator(".detailInfo.srchTimedeal .carName .carTit").first
                    car_name = (el.inner_text().strip() if el.count() else "") or ""
                except Exception:
                    pass

                # 차량 카드가 아닌 요소(광고/빈 박스)는 건너뜀 → 빈 행 방지, 5번 뒤 7번이 6번으로 밀리는 현상 해소
                if not product_id and not car_name:
                    continue

                model_sn += 1
                row = [model_sn]
                row.append(product_id)
                row.append(car_name)

                # car_exp: .carListFlex .carExpIn .carExp
                try:
                    el = box.locator(".carListFlex .carExpIn .carExp").first
                    row.append(el.inner_text().strip() if el.count() else "")
                except Exception:
                    row.append("")

                # car_pay_meth: .carPayMeth li .el-link .el-link--inner 전체 텍스트 (할부 월 9만원 등)
                try:
                    el = box.locator(".carPayMeth li .el-link .el-link--inner").first
                    row.append(el.inner_text().strip() if el.count() else "")
                except Exception:
                    row.append("")

                # release_dt, car_navi, car_fuel, local_dos: .carListFlex .detailCarCon span 순서대로
                for _ in range(4):
                    row.append("")
                try:
                    spans = box.locator(".carListFlex .detailCarCon span")
                    cnt = spans.count()
                    if cnt >= 1:
                        row[-4] = spans.nth(0).inner_text().strip()
                    if cnt >= 2:
                        row[-3] = spans.nth(1).inner_text().strip()
                    if cnt >= 3:
                        row[-2] = spans.nth(2).inner_text().strip()
                    if cnt >= 4:
                        row[-1] = spans.nth(3).inner_text().strip()
                except Exception:
                    pass

                # info_tooltip: .infoTooltip 내 텍스트를 | 구분으로 한 컬럼
                try:
                    tooltip = box.locator(".infoTooltip").first
                    if tooltip.count():
                        text = tooltip.inner_text().strip().replace("\n", "|")
                        row.append(text)
                    else:
                        row.append("")
                except Exception:
                    row.append("")

                w.writerow(row)
                if model_sn % 20 == 0 and model_sn > 0:
                    logger.info("리스트 수집 진행: %d건 (박스 %d/%d)", model_sn, i + 1, n_boxes)

        logger.info("============================================================")
        logger.info("✅ kcar_list 수집 완료! 파일: %s", csv_path)
        logger.info("총 %d건 (박스 %d개 중)", model_sn, n_boxes)
    except Exception as e:
        logger.error("검색 리스트 수집 오류: %s", e, exc_info=True)


def main():
    logger = setup_logger()
    # result/kcar (프로젝트 루트 기준)
    result_dir = Path(__file__).resolve().parent.parent / "result" / "kcar"
    result_dir.mkdir(parents=True, exist_ok=True)

    # 프로그램 시작 시 기존 CSV 삭제 후 새로 수집
    # (리스트만 테스트 시 kcar_list.csv만 삭제)
    for name in ("kcar_car_type_list.csv", "kcar_brand_list.csv", "kcar_list.csv"):
    # for name in ("kcar_list.csv"):
        path = result_dir / name
        if path.exists():
            path.unlink()

    with sync_playwright() as p:
        # headless=False: 크롤링 화면을 보이게 해서 진행 상황·에러 확인 가능
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        try:
            # 차종·브랜드 수집 (테스트 시 주석 처리)
            run_kcar_car_type_list(page, result_dir, logger)
            run_kcar_brand_list(page, result_dir, logger)
            run_kcar_list(page, result_dir, logger)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
