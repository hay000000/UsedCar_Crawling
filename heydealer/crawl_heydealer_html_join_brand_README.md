# crawl_heydealer_html_join_brand.py 소스 설명

헤이딜러(heydealer.com) 중고차 매물을 **목록 → 상세** 순으로 수집하고, 브랜드 매핑을 붙여 CSV·이미지로 저장하는 크롤러입니다.

---

## 1. 목적·개요

- **대상**: https://www.heydealer.com/market/cars
- **출력**  
  - `result/heydealer/heydealer_list.csv` : 목록 데이터 (차량 요약)  
  - `result/heydealer/heydealer_detail.csv` : 상세 데이터 (스펙·옵션·이미지 등)  
  - `imgs/heydealer/` : 상세 페이지에서 받은 이미지 (`{model_cd}_{번호}.jpg` 등)
- **브랜드**: `result/heydealer_brands_final.csv`의 `model_name` → `brand_id`, `brand_name` 매핑을 읽어 목록/상세에 붙입니다.

---

## 2. 설정·경로 (상단)

| 항목 | 의미 |
|------|------|
| `TARGET_COUNT` | 목록 수집 개수 상한 (예: 702). 이 개수만큼 모으면 스크롤 종료. |
| `BASE_URL` | 헤이딜러 도메인 |
| `RESULT_DIR` | `result/heydealer` (CSV 저장) |
| `LOG_DIR` | `logs/heydealer` (로그 파일) |
| `IMG_DIR` | `imgs/heydealer` (이미지 저장) |
| `LIST_FILE` | `heydealer_list.csv` |
| `DETAIL_FILE` | `heydealer_detail.csv` |

- `Logger`: `print`를 터미널과 `logs/heydealer/heydealer_list_detail_log_YYYYMMDD.log`에 동시에 남깁니다.

---

## 3. 주요 함수

### 3.1 `load_brand_mapping()`

- `result/heydealer_brands_final.csv`에서 `model_name` → `brand_id`, `brand_name` 딕셔너리 생성.
- 목록/상세 수집 시 차량명으로 브랜드를 찾아 `brand_id`, `brand_name`을 채우는 데 사용.

### 3.2 `save_to_csv_append(file_path, fieldnames, data_dict)`

- CSV를 **추가 모드**로 열고, `fieldnames` 순서대로 한 행 씩 저장.
- 파일이 없으면 헤더를 먼저 씀. `extrasaction='ignore'`로 `data_dict`에 있는 여분 키는 무시.

### 3.3 `download_image(img_url, model_cd, idx)`

- `img_url`을 GET으로 받아 `IMG_DIR/model_cd_{idx}.{확장자}`로 저장.
- User-Agent·Referer 설정, SVG 제외, 확장자 추론(기본 jpg). 실패 시 `False` 반환.

### 3.4 `_extract_card_heydealer(elem, idx, brand_map)`

**역할**: 목록 페이지의 카드 DOM 한 개(`elem`)에서 데이터를 뽑습니다.

- **입력**: Playwright 요소 `elem`, 순번 `idx`, `load_brand_mapping()` 결과 `brand_map`.
- **추출 내용**  
  - `href` → `model_cd`(URL 마지막 경로), `detail_url`(전체 URL)  
  - `.css-9j6363` 안: `.css-jk6asd` → `model_name`, `model_second_name`, `.css-13wylk3` → `grade_name`  
  - `model_name`(또는 공백 뒤 부분)으로 `brand_map` 조회 → `brand_id`, `brand_name`  
  - `.css-6bza35` → `ㆍ` 기준으로 `year`, `km`  
  - 가격 영역 → `sale_price`  
  - 수집 시각 `date_crtr_pnttm`, `create_dt`
- **반환**: 위 필드가 담긴 딕셔너리. 예외 시에도 빈 값으로 채워진 딕셔너리를 반환.

### 3.5 `_extract_detail_smart(page, list_item)`

**역할**: 이미 열린 상세 페이지(`page`)에서 스펙·옵션·출고정보·추천 코멘트·이미지 URL을 수집하고, 이미지는 `download_image`로 저장합니다.

- **입력**: Playwright `page`, 목록에서 넘어온 `list_item` (차량 기본 정보).
- **초기 `res`**: `list_item`의 `model_sn`, `brand_id`, `brand_name`, `model_cd`, `model_name`, `model_second_name`, `grade_name`, `year`, `km`, `detail_url`, `date_crtr_pnttm`, `create_dt`를 그대로 채우고, 상세 전용 필드(refund, guarantee, accident 등)는 빈 문자열로 둠. (int 방지를 위해 `str()` 처리.)

**진행 순서**:

1. **페이지 대기**  
   - `.css-12qft46` 또는 `.css-113wzqa`가 나올 때까지 대기 후, 스크롤로 레이지 로딩 유도.

2. **이미지 수집**  
   - `.css-12qft46`(또는 `.css-1uus6sd .css-12qft46`) 아래  
     - 두 번째 `.css-ltrevz`: 버튼/썸네일 이미지  
     - 네 번째 `.css-ltrevz`: 상세 이미지  
   - `src` / `data-src`에서 URL 추출 → `download_image` 호출.  
   - 하나도 없으면 `heydealer.com`/`cdn.`/`main img` 등 폴백 선택자로 재시도.

3. **스크롤**  
   - 세로로 여러 번 스크롤해 동적 콘텐츠·스펙 영역이 로드되도록 함.

4. **스펙 영역 대기**  
   - `.css-113wzqa`가 보일 때까지 대기(타임아웃·재시도 있음).

5. **텍스트 데이터 수집**  
   - **옵션**: `.css-5pr39e .css-13wylk3` 등 → `options`  
   - **출고 정보**: `.css-1cfq7ri` 안 "출고 정보" + `.css-1n3oo4w` → `delivery_information`  
   - **추천 코멘트**: `.css-yfldxx` → `recommendation_comment`  
   - **스펙**: `.css-113wzqa` 각 단위에서 `.css-1b7o1k1`(라벨) + 다음 형제(값).  
     - 라벨 한글(공백 제거)에 따라 연식·주행거리·환불·헤이딜러보증·사고·실내세차·자차보험처리·외부/실내·타이어·틴팅·차키 등에 매핑.

6. **스펙 비었을 때 재시도**  
   - `year`/`km`가 둘 다 비어 있으면, 추가 대기(3초/5초) + 스크롤 후 `.css-113wzqa` 스펙 수집을 최대 2번 더 시도.

- **반환**: 위에서 채운 `res` 딕셔너리. 예외 시에도 초기 `res`(목록 기반 + 상세 필드 빈 값)를 그대로 반환.

---

## 4. main() 흐름

### 4.1 브랜드 매핑·파일 초기화

- `load_brand_mapping()` 호출.
- `LIST_FILE`, `DETAIL_FILE`이 있으면 삭제 후 새로 씀.

### 4.2 Playwright 브라우저

- Chromium 실행 (`headless=False`), 1920x1080 뷰포트, User-Agent·webdriver 은닉.
- 한 개의 `page`로 목록·상세 모두 방문.

### 4.3 [1단계] 목록 수집

- `BASE_URL/market/cars` 접속 (최대 3회 재시도).
- **무한 스크롤**  
  - 맨 아래로 스크롤 → 2.5초 대기 → `a[href^="/market/cars/"]` 카드 수집.  
  - `href` 기준으로 중복 제거, 새로 보인 카드만 `_extract_card_heydealer`로 파싱.  
  - `raw_list`에 추가하고 `save_to_csv_append(LIST_FILE, list_fields, item)`로 목록 CSV에 바로 적음.
- **종료 조건**  
  - `len(raw_list) >= TARGET_COUNT` 이면 목표 개수 달성으로 종료.  
  - 스크롤해도 높이 안 늘어나거나, 2라운드 연속 새 매물이 없으면 끝.

### 4.4 [2단계] 상세 수집

- `raw_list`를 순회하며 각 `item["detail_url"]`로 이동.
- **재시도**: 최대 3번.  
  - `page.goto` → load 대기 → 1.5초 대기 → `_extract_detail_smart(page, item)` → `detail` 획득.
  - **스펙 부족 시**: 연식·주행·환불·보증·사고 중 채워진 개수가 2개 미만이고 재시도 횟수가 남아 있으면, 3초 대기 후 같은 URL로 다시 `goto` → 2.5초 대기 → `_extract_detail_smart` 한 번 더 호출해 `detail` 갱신.
  - **저장 전 병합**: `detail_fields` 기준으로, 상세 값이 비어 있는 컬럼은 `item`(목록) 값으로 채움. (모든 값은 `str`로 통일.)
  - `save_to_csv_append(DETAIL_FILE, detail_fields, detail)`로 상세 CSV에 한 행 추가.
- **예외 시**: 3번 다 실패하면 "최종 실패" 로그 후, `item`으로만 채운 `fail_row`를 동일한 `detail_fields`로 CSV에 추가 (빈 컬럼은 `""`).

### 4.5 종료

- 상세 수집 성공 건수·경로·로그 파일 위치 출력 후 브라우저 종료.

---

## 5. 안정화·예외 처리 요약

| 구간 | 내용 |
|------|------|
| 목록 | 목록 페이지 접속 3회 재시도. 카드 추출 예외 시 해당 카드만 스킵하고 `data`는 빈 값 유지. |
| 상세 goto | 상세 URL 접속 실패 시 최대 3회 재시도. |
| 상세 스펙 | 스펙이 거의 없으면 같은 URL로 한 번 더 로드 후 재추출. |
| 상세 내부 | `.css-113wzqa` 대기, 스펙 비었을 때 2회 추가 대기+스크롤+재수집. 값은 `str()` 처리해 int 등으로 인한 `.strip()` 오류 방지. |
| 저장 | 상세 필드가 비어 있으면 목록(`item`) 값으로 채운 뒤 저장. 실패 건은 목록 데이터만으로 한 행 저장. |

---

## 6. CSV 컬럼

- **목록 (`list_fields`)**: model_sn, brand_id, brand_name, model_cd, model_name, model_second_name, grade_name, year, km, sale_price, detail_url, date_crtr_pnttm, create_dt  
- **상세 (`detail_fields`)**: 위와 동일한 기본 식별·차량명·연식·주행 + refund, guarantee, accident, inner_car_wash, insurance, exterior_description, interior_description, options, delivery_information, recommendation_comment, tire, tinting, car_key, detail_url, date_crtr_pnttm, create_dt  

이 문서는 `crawl_heydealer_html_join_brand.py`의 동작과 구조를 설명합니다. 실제 선택자·경로는 헤이딜러 사이트 구조 변경 시 수정이 필요할 수 있습니다.
