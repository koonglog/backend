import requests
import time
import random
from datetime import datetime

URL = "http://127.0.0.1:8000/api/v1/sensor-readings"

sensors = ["SENSOR-A101-01", "SENSOR-A201-01", "SENSOR-B102-01"]

print("🚀 가상 소음 데이터 시뮬레이션 시작...")

while True:
    for s_id in sensors:
        sound_level = round(random.uniform(35.0, 75.0), 1)
        vibration_value = round(random.uniform(200, 900), 1)
        duration_ms = random.randint(1000, 10000)

        data = {
            "sensor_id": s_id,
            "sound_level": sound_level,
            "vibration_value": vibration_value,
            "duration_ms": duration_ms,
            "timestamp": datetime.now().isoformat(),
            "acceleration": {
                "x": round(random.uniform(-0.1, 0.1), 3),
                "y": round(random.uniform(-0.1, 0.1), 3),
                "z": round(random.uniform(0.9, 1.2), 3)
            }
        }

        try:
            response = requests.post(URL, json=data)
            if response.status_code == 200:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {s_id}: {sound_level}dB, 진동 {vibration_value} -> 전송 성공!")
            else:
                print(f"❌ 전송 실패: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"📡 서버 연결 실패: {e}")

    time.sleep(5)
    
    