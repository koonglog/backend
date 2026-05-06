import requests
import time
import random
from datetime import datetime

# URL이 정확히 http://127.0.0.1:8000/api/v1/noise-logs 인지 확인하세요!
URL = "http://127.0.0.1:8000/api/v1/noise-logs"

sensors = ["SN-A304-01", "SN-B102-05", "SN-C505-02"]

print("🚀 가상 소음 데이터 시뮬레이션 시작...")

while True:
    for s_id in sensors:
        # 테스트를 위해 40~80 사이의 큰 값이 자주 나오도록 수정했습니다.
        db_level = round(random.uniform(40.0, 80.0), 1)
        
        data = {
            "sensor_id": s_id,
            "decibel": db_level,
            "timestamp": datetime.now().isoformat()
        }
        
        try:
            # 데이터를 서버로 전송
            response = requests.post(URL, json=data)
            if response.status_code == 200:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {s_id}: {db_level}dB -> 전송 성공!")
            else:
                print(f"❌ 전송 실패: {response.status_code}")
        except Exception as e:
            print(f"📡 서버 연결 실패: {e}")
            
    time.sleep(5)