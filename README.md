# Used Car Crawler

헤이딜러(heydealer.com) 시장 차량 목록을 크롤링해 로컬 CSV 파일로 저장하는 프로젝트입니다.

## 대상 사이트

- **헤이딜러 시장**: https://www.heydealer.com/market/cars  
  크롤링할 URL은 **localhost DB**의 `bsc_info`(또는 `tn_data_bsc_info`) 테이블에서 **헤이딜러만 쿼리**해 `target_url`을 가져와 사용합니다. DB 미연결 시 위 기본 URL을 사용합니다.

## 요구 사항

- Python 3.10+
- Playwright (Chromium)
- (선택) MySQL — DB에서 헤이딜러 URL을 가져올 경우 PyMySQL 사용

## 설치

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## DB 설정 (헤이딜러 URL 조회용)

`tn_data_bsc_info`(또는 `bsc_info`) 테이블에 `site_name`, `target_url`, `link_yn` 컬럼이 있고, **헤이딜러** 행의 `target_url`을 사용합니다. 아래 환경 변수로 DB 연결을 설정하세요.

| 환경 변수     | 설명           | 기본값              |
|---------------|----------------|---------------------|
| `DB_HOST`     | DB 호스트      | localhost           |
| `DB_PORT`     | 포트           | 3306                |
| `DB_USER`     | 사용자         | root                |
| `DB_PASSWORD` | 비밀번호       | (빈 문자열)        |
| `DB_NAME`     | DB 이름        | (필수, 비우면 DB 미사용) |
| `BSC_TABLE`   | 테이블명       | tn_data_bsc_info   |

예 (Linux/macOS):

```bash
export DB_NAME=your_database
export DB_USER=your_user
export DB_PASSWORD=your_password
python crawl_heydealer.py
```

## 실행

```bash
python crawl_heydealer.py
```

1. DB에 `DB_NAME`이 설정되어 있으면 **헤이딜러만** 쿼리한 `target_url`로 크롤링합니다.  
2. DB 미연결 또는 헤이딜러 미등록 시 기본 URL(`https://www.heydealer.com/market/cars`)로 크롤링합니다.  
3. 실행이 끝나면 프로젝트 루트에 `heydealer_cars.csv` 파일이 생성됩니다.

## CSV 컬럼

| 컬럼     | 설명                    |
|----------|-------------------------|
| title    | 차량 모델명             |
| year_km  | 연식·주행거리 (예: 2024년 (23/11)ㆍ3.3만km) |
| price_raw| 가격 문자열 (예: 3,990만원) |
| price    | 가격 숫자 (원 단위)     |
| url      | 차량 상세 페이지 URL    |

## 옵션

`crawl_heydealer.py`의 `main()`에서 다음을 변경할 수 있습니다.

- `crawl_all_pages(max_scrolls=5)`: `max_scrolls`를 늘리면 더 많은 차량이 로드됩니다 (무한 스크롤).

## 참고

- 동적 로딩 페이지이므로 Playwright로 브라우저를 띄워 렌더링 후 수집합니다.
- 사이트 구조 변경 시 선택자 수정이 필요할 수 있습니다.
