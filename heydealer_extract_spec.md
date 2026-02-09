# 헤이딜러 상세 페이지 추출 스펙

| 추출 항목 | 선택자 |
|-----------|--------|
| 차량 이름 (car_name) | class="css-1ugrlhy" |
| 차량 이름 디테일 (car_detail_name) | class="css-pjgjzs" |
| 이미지(영상) (image_video) | preload="metadata" |
| 이미지 전체 (images_all) | class="css-khiabn" |
| 연식 / 주행거리 / 환불 / 헤이딜러 보증 / 사고 / 실내세차 / 자차 보험 처리 | class="css-21wmfe" 안에서 class="css-113wzqa" 단위, 라벨 class="css-1b7o1k1" + 다음 형제 값 |
| 중고차 가격 (price) | class="css-1qoks2m" |
| 신차 가격 (new_car_price) | class="css-6bgw5b" |

## css-21wmfe 구조

- 컨테이너: css-21wmfe
- 단위: css-113wzqa (각각 연식, 주행거리, 환불, 헤이딜러 보증, 사고, 실내세차, 자차 보험 처리 등)
- 라벨: css-1b7o1k1, 값: 그 다음 형제 div

라벨마다 CSV 별도 컬럼으로 저장.
