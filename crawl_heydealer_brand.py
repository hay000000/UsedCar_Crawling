import time
import pandas as pd
import logging
import requests
from datetime import datetime
from pathlib import Path

# --- 로깅 및 경로 설정 ---
BASE_DIR = Path(__file__).resolve().parent

# RESULT_DIR = Path("./result/heydealer")
RESULT_DIR = BASE_DIR / "result" / "heydealer"
LOG_DIR = BASE_DIR / "logs" / "heydealer"
RESULT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'heydealer_brand_hierarchy.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class HeyDealerBrandCrawler:
    def __init__(self):
        self.api_base = "https://api.heydealer.com/v2/customers/web/market/car_meta"
        self.brand_file = RESULT_DIR / "heydealer_brands_final.csv"
        
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json",
        })

    def get_now_times(self):
        """요청하신 형식의 날짜 데이터 생성"""
        now = datetime.now()
        # 20260211 형식 (8자리)
        data_crtr_pnttm = now.strftime("%Y%m%d")
        # 202602111328 형식 (12자리)
        creat_de = now.strftime("%Y%m%d%H%M")
        return data_crtr_pnttm, creat_de

    def fetch_hierarchy(self):
        """3단계 API 구조 탐색 및 날짜 정보 포함 수집"""
        logger.info("=" * 60)
        logger.info("헤이딜러 브랜드-모델 계층 데이터 수집 시작 (날짜 정보 포함)")
        logger.info("=" * 60)
        
        all_data = []
        # 수집 시점의 날짜 생성
        d_pnttm, c_dt = self.get_now_times()
        
        try:
            # [Step 1] 전체 브랜드 목록 호출
            brands_resp = self.session.get(f"{self.api_base}/brands/", timeout=10)
            brands_resp.raise_for_status()
            brands = brands_resp.json()
            
            logger.info(f"총 {len(brands)}개 브랜드 데이터 수집 시작")

            for b_idx, brand in enumerate(brands, 1):
                brand_id = brand.get('hash_id')
                brand_name = brand.get('name')
                
                logger.info(f"[{b_idx}/{len(brands)}] 브랜드 처리 중: {brand_name}")

                # [Step 2] 브랜드별 모델 그룹 호출
                mg_resp = self.session.get(f"{self.api_base}/brands/{brand_id}/", timeout=10)
                if mg_resp.status_code != 200: continue
                
                model_groups = mg_resp.json().get('model_groups', [])

                for mg in model_groups:
                    mg_id = mg.get('hash_id')
                    mg_name = mg.get('name')

                    # [Step 3] 모델 그룹별 세부 모델 호출
                    sub_resp = self.session.get(f"{self.api_base}/model_groups/{mg_id}/", timeout=10)
                    if sub_resp.status_code != 200: continue
                    
                    models = sub_resp.json().get('models', [])

                    for model in models:
                        # 최종 데이터 적재 (날짜 정보 추가)
                        all_data.append({
                            "brand_id": brand_id,
                            "brand_name": brand_name,
                            "model_group_id": mg_id,
                            "model_group_name": mg_name,
                            "model_id": model.get('hash_id'),
                            "model_name": model.get('name'),
                            "model_count": model.get('count', 0),
                            "production_period": model.get('period', ''),
                            "data_crtr_pnttm": d_pnttm, # 8자리 날짜
                            "create_dt": c_dt            # 12자리 날짜 (creat_de 매칭)
                        })
                
                # API 서버 부하 방지
                time.sleep(0.1)

            # --- 결과 저장 ---
            if all_data:
                df = pd.DataFrame(all_data)
                # 컬럼 순서 지정 (날짜 정보를 끝에 배치)
                column_order = [
                    "brand_id", "brand_name", 
                    "model_group_id", "model_group_name", 
                    "model_id", "model_name", 
                    "model_count", "production_period",
                    "data_crtr_pnttm", "create_dt"
                ]
                df = df[column_order]
                df.to_csv(self.brand_file, index=False, encoding="utf-8-sig")
                
                logger.info("=" * 60)
                logger.info(f"✅ 수집 완료! 파일: {self.brand_file}")
                logger.info(f"총 수집 모델 수: {len(df):,}개")
                logger.info("=" * 60)
            else:
                logger.warning("⚠️ 수집된 데이터가 없습니다.")

        except Exception as e:
            logger.error(f"❌ 크롤링 중 치명적 오류: {e}")

if __name__ == "__main__":
    crawler = HeyDealerBrandCrawler()
    crawler.fetch_hierarchy()