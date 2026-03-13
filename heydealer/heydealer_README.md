# 헤이딜러 추출 스펙 (crawl_heydealer_type_to_list.py 기준)

대상 스크립트: `heydealer/crawl_heydealer_type_to_list.py`  
출력: `result/heydealer/heydealer_list.csv`, `imgs/heydealer/list/`, `imgs/heydealer/detail/` (config 기준)

---

## 1. 목록 페이지 (목록 카드) 추출

목록에서 카드 단위로 수집. 카드 선택자: `a[href^="/market/cars/"]`.

### 1.1 카드 내 선택자 → CSV 필드

| CSV 컬럼 | 선택자 / 출처 | 비고 |
|----------|----------------|------|
| model_sn | (순번) | 1부터 부여 |
| product_id | URL 경로 마지막 세그먼트 | 예: `/market/cars/Wnqe5KnL` → `Wnqe5KnL` |
| car_type | (차종 필터명) | filters API 차종별 수집 시 해당 차종명 |
| brand_list | brand_list.csv 매칭 | 목록 카드에서는 미설정, 매칭 시 채움 |
| car_list | brand_list.csv 매칭 | 목록 카드에서는 미설정, 매칭 시 채움 |
| model_list | `.css-9j6363` 내 `.css-jk6asd` 첫 번째 span 텍스트 | 예: "더 뉴 모닝 (JA)" |
| model_list_1 | `.css-9j6363` 내 `.css-jk6asd` 두 번째 span 텍스트 | 있으면 설정 |
| model_list_2 | `.css-9j6363` 내 `.css-13wylk3` 텍스트 (등급) | 예: "시그니처" |
| car_name | `.css-9j6363` 전체 `inner_text()` | 차량 풀네임, 예: "더 뉴 모닝 (JA) 시그니처" |
| year | `.css-6bza35` 텍스트, `ㆍ` 앞부분 | 연식 |
| km | `.css-6bza35` 텍스트, `ㆍ` 뒷부분 | 주행거리 |
| sale_price | `.css-105xtr1 .css-1066lcq .css-dbu2tk` 내 `.css-8sjynn` 또는 영역 텍스트 | 판매가 |
| detail_url | 카드 `href` 절대 URL | 상세 페이지 URL |
| list_image_url | 카드 내 `img`의 `src` / `data-src` (image.heydealer.com 등 우선) | 목록 썸네일 URL (CSV에는 미저장, 수집용) |
| car_imgs | (1단계에서는 빈값) | 2단계에서 list 또는 detail 이미지 상대 경로로 채움 |
| date_crtr_pnttm | 실행일 `%Y%m%d` | |
| create_dt | 실행 시각 `%Y%m%d%H%M` | |

### 1.2 목록 카드 DOM 구조 (요약)

- 컨테이너: `a[href^="/market/cars/"]`
- 차량명/등급 박스: `.css-9j6363`
  - 모델명: `.css-jk6asd` (첫 번째 → model_list, 두 번째 → model_list_1)
  - 등급: `.css-13wylk3` → model_list_2
  - 풀네임: 위 컨테이너 전체 텍스트 → car_name
- 연식·주행: `.css-6bza35` (예: `2020년 ㆍ 5만km`)
- 가격: `.css-105xtr1 .css-1066lcq .css-dbu2tk`, 판매가 강조: `.css-8sjynn`

---

## 2. brand_list.csv 매칭

- 파일: `result/heydealer/heydealer_brand_list.csv`
- 목록 행 추가 시마다 `_find_matching_brand_row(item, brand_rows)`로 매칭 후 **brand_list, car_list, model_list, model_list_1, model_list_2** 를 채워서 CSV에 append.

매칭 순서:

1. **동일 키**: list의 (model_list + model_list_1 + model_list_2) == brand의 동일 필드 결합.
2. **앞단만**: list의 model_list를 첫 단어만 사용한 키로 brand와 **포함 관계** 비교 (in 2가지 + str.find 2가지, `_key_match`).
3. **앞 한 단어 제거**: list의 model_list에서 첫 단어를 뺀 나머지 + model_list_1 + model_list_2로 brand와 포함 관계 비교.

포함 관계: `a in b or b in a` 및 `a.find(b) >= 0 or b.find(a) >= 0`.

---

## 3. list.csv 컬럼 순서

```
model_sn, product_id, car_type, brand_list, car_list, model_list, model_list_1, model_list_2, car_name, year, km, sale_price, detail_url, car_imgs, date_crtr_pnttm, create_dt
```

---

## 4. 이미지 저장

경로는 `config.py`의 `IMG_LIST_REL`, `IMG_DETAIL_REL` 사용 (기본값: `imgs/heydealer/list`, `imgs/heydealer/detail`).  
하위 디렉터리: `{연도}년/{YYYYMMDD}` (실행일 기준).

| 구분 | 저장 위치 | 파일명 | 채우는 시점 |
|------|-----------|--------|-------------|
| 목록 썸네일 | list | `{product_id}_list.png` | 목록 카드의 list_image_url로 다운로드 (2단계에서 1건당 1회) |
| 상세 이미지 | detail | `{product_id}_1.png`, `{product_id}_2.png`, ... | 상세 페이지 접속 후 이미지 URL 수집해 순서대로 저장 (2단계) |

- **car_imgs** 컬럼: 목록 URL로 저장한 list 이미지 경로가 있으면 그 경로, 없으면 detail의 첫 번째 이미지 상대 경로.
- list 폴더에는 목록 썸네일만, detail 폴더에는 상세 페이지 이미지만 저장.

---

## 5. 상세 페이지 (이미지 수집용 선택자)

상세 페이지는 **이미지 URL 수집**에만 사용됨. 차량명·가격 등 필드 추출은 하지 않음.

이미지 수집 순서:

1. `LIST_IMG_DOM_SELECTOR`:  
   `#root .css-kuuk2w .css-18e6263 .css-17qdlp1 .css-fhycda .css-1x0imnr .css-1t74t4t .css-a97e7u .css-a97e7u .css-8n2v9x .css-di7boj .css-1fg02ng .css-vdxqtk img`
2. `.css-12qft46` 또는 `.css-113wzqa` 대기 후, `.css-1uus6sd .css-12qft46` / `.css-12qft46` 컨테이너 내 `.css-ltrevz` 섹션의 이미지 (버튼/썸네일 등).
3. `img[src*='heydealer.com']`, `img[src*='cdn.']`, `.css-w9nhgi img`, `.css-1a3591h img`, `main img`.
4. 그 외 `img[src]`, `img[data-src]` 중 heydealer/cdn 등 조건 만족하는 URL.

수집한 URL을 중복 제거·순서 유지한 뒤 `detail/{연도}년/{YYYYMMDD}/{product_id}_1.png`, `_2.png`, ... 로 저장.

---

## 6. 참고: 상세 페이지 필드 (미사용)

아래는 **현재 스크립트에서 사용하지 않는** 상세 페이지 선택자 참고용.

| 추출 항목 | 선택자 |
|-----------|--------|
| 차량 이름 (car_name) | class="css-1ugrlhy" |
| 차량 이름 디테일 (car_detail_name) | class="css-pjgjzs" |
| 이미지(영상) (image_video) | preload="metadata" |
| 이미지 전체 (images_all) | class="css-khiabn" |
| 연식 / 주행거리 / 환불 / 헤이딜러 보증 / 사고 / 실내세차 / 자차 보험 처리 | class="css-21wmfe" 안에서 class="css-113wzqa" 단위, 라벨 class="css-1b7o1k1" + 다음 형제 값 |
| 중고차 가격 (price) | class="css-1qoks2m" |
| 신차 가격 (new_car_price) | class="css-6bgw5b" |

### css-21wmfe 구조

- 컨테이너: css-21wmfe  
- 단위: css-113wzqa (연식, 주행거리, 환불, 헤이딜러 보증, 사고, 실내세차, 자차 보험 처리 등)  
- 라벨: css-1b7o1k1, 값: 그 다음 형제 div  

라벨마다 CSV 별도 컬럼으로 저장 가능 (현재 스크립트에서는 미구현).
