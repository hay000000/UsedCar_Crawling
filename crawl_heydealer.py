import requests
import pandas as pd
import time
import logging
from pathlib import Path

# 1. 경로 설정
BASE_DIR = Path(__file__).resolve().parent
RESULT_DIR = BASE_DIR / "result"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

class HeyDealerGradeMapper:
    def __init__(self):
        self.api_base = "https://api.heydealer.com/v2/customers/web/market/car_meta"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'application/json'
        })
        self.final_file_path = RESULT_DIR / "heydealeer_brand.csv"
        
        # 윈도우 경로 변환 (f-string 외부에서 처리)
        linux_path_str = str(self.final_file_path)
        win_path_suffix = linux_path_str.replace('/', '\\')
        self.win_path = f"\\\\wsl.localhost\\Ubuntu-22.04{win_path_suffix}"

    def get_json(self, url):
        try:
            time.sleep(0.1) # 차단 방지 및 속도 확보
            resp = self.session.get(url, timeout=10)
            return resp.json() if resp.status_code == 200 else None
        except:
            return None

    def run(self):
        logger.info("🚀 [브랜드 > 모델 > 소분류 > 등급] 수집 시작")
        
        brands = self.get_json(f"{self.api_base}/brands/")
        if not brands: return

        all_mapping = []
        for b in brands:
            b_name, b_hash = b.get('name'), b.get('hash_id')
            logger.info(f"▶️ 브랜드: {b_name}")

            models_data = self.get_json(f"{self.api_base}/brands/{b_hash}/")
            if not models_data: continue

            for m in models_data.get('model_groups', []):
                m_name, m_hash = m.get('name'), m.get('hash_id')
                
                sub_data = self.get_json(f"{self.api_base}/model_groups/{m_hash}/")
                if not sub_data or not sub_data.get('models'): continue

                for s in sub_data['models']:
                    s_name, s_hash = s.get('name'), s.get('hash_id')
                    s_period = s.get('period', '-')

                    # ✨ 등급(grades) 정보 호출
                    detail_data = self.get_json(f"{self.api_base}/models/{s_hash}/")
                    
                    # grades 정보가 없으면 소분류 정보를 기본으로 입력
                    if not detail_data or 'grades' not in detail_data or not detail_data['grades']:
                        # all_mapping.append({
                        #     "대분류(브랜드)": b_name, "중분류(모델)": m_name,
                        #     "소분류(상세)": s_name, "세부트림(등급)": "-",
                        #     "생산시기": s_period, "매물수": s.get('count', 0)
                        # })
                        all_mapping.append({
                            "brand_name": b_name,
                            "brand_id": b_hash,
                            "model_group_name": m_name,
                            "model_group_id": m_hash,
                            "model_name": s_name,
                            "model_id": s_hash,
                            "grade_name": "-",
                            "grade_id": "-",
                            "production_period": s_period,
                            "listing_count": s.get('count', 0)
                        })
                        continue

                    # grades(등급) 단계까지만 수집
                    for g in detail_data['grades']:
                        # all_mapping.append({
                        #     "대분류(브랜드)": b_name,
                        #     "중분류(모델)": m_name,
                        #     "소분류(상세)": s_name,
                        #     "세부트림(등급)": g.get('name'), # 등급명 (프리미엄 등)
                        #     "생산시기": s_period,
                        #     "매물수": g.get('count', 0) # 등급별 매물 수
                        # })
                        all_mapping.append({
                            "brand_name": b_name,
                            "brand_id": b_hash,
                            "model_group_name": m_name,
                            "model_group_id": m_hash,
                            "model_name": s_name,
                            "model_id": s_hash,
                            "grade_name": g.get('name'), # 등급명 (예: 프리미엄)
                            "grade_id": g.get('hash_id'), # 등급 ID
                            "production_period": s_period,
                            "listing_count": g.get('count', 0) # 등급별 매물 수
                        })
            
            # 브랜드 완료 시점마다 파일 저장
            self.save_to_csv(all_mapping)

        logger.info("\n" + "="*70)
        logger.info(f"✨ 브랜드 분류 데이터 수집 완료! 파일 위치: {self.win_path}")
        logger.info("="*70)

#================================================================== 

    def save_to_csv(self, data):
        pd.DataFrame(data).to_csv(self.final_file_path, index=False, encoding="utf-8-sig")

if __name__ == "__main__":
    HeyDealerGradeMapper().run()