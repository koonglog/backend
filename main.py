from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from datetime import datetime, date
from typing import List

import models
from database import engine, get_db

# 1. 서버 시작 시 DB 테이블 생성
models.Base.metadata.create_all(bind=engine)

# 2. 초기 센서 데이터 자동 삽입
db_init = next(get_db())
if db_init.query(models.Sensor).count() == 0:
    test_sensors = [
        models.Sensor(sensor_id="SN-A304-01", location_unit="A동 304호", is_online=True, battery_level=85),
        models.Sensor(sensor_id="SN-B102-05", location_unit="B동 102호", is_online=True, battery_level=92),
        models.Sensor(sensor_id="SN-C505-02", location_unit="C동 505호", is_online=False, battery_level=12),
    ]
    db_init.add_all(test_sensors)
    db_init.commit()

app = FastAPI(title="쿵로그(KungLog) AI 통합 서버")

class NoiseData(BaseModel):
    sensor_id: str
    decibel: float
    timestamp: datetime

    class Config:
        from_attributes = True

class DashboardStats(BaseModel):
    total_sensors: int
    online_sensors: int
    avg_battery: float
    today_warnings: int
    current_avg_db: float

class MediationResponse(BaseModel):
    id: int
    target_unit: str
    ai_message: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

def generate_ai_message(unit: str, db_level: float):
    if db_level > 60:
        return f"[{unit}] 현재 매우 심한 소음({db_level}dB)이 감지되었습니다. 즉시 확인 부탁드립니다."
    else:
        return f"[{unit}] 층간소음 기준을 초과하는 소음({db_level}dB)이 발생했습니다. 주의 부탁드립니다."

@app.get("/")
def read_root():
    return {"message": "AI 통합 쿵로그 백엔드"}

@app.get("/api/v1/dashboard/stats", response_model=DashboardStats)
def get_dashboard_stats(db: Session = Depends(get_db)):
    total = db.query(models.Sensor).count()
    online = db.query(models.Sensor).filter(models.Sensor.is_online == True).count()
    avg_battery = db.query(func.avg(models.Sensor.battery_level)).scalar() or 0
    today = date.today()
    warning_count = db.query(models.NoiseLog).filter(
        func.date(models.NoiseLog.timestamp) == today,
        models.NoiseLog.decibel > 40
    ).count()
    recent_avg_db = db.query(func.avg(models.NoiseLog.decibel)).filter(
        models.NoiseLog.id.in_(
            db.query(models.NoiseLog.id).order_by(models.NoiseLog.timestamp.desc()).limit(100)
        )
    ).scalar() or 0

    return {
        "total_sensors": total,
        "online_sensors": online,
        "avg_battery": round(float(avg_battery), 1),
        "today_warnings": warning_count,
        "current_avg_db": round(float(recent_avg_db), 1)
    }

@app.post("/api/v1/noise-logs")
async def create_noise_log(data: NoiseData, db: Session = Depends(get_db)):
    # 📢 서버 터미널에 데이터가 오는지 바로 찍어봅니다.
    print(f"📩 데이터 도착: {data.sensor_id} - {data.decibel}dB")

    new_log = models.NoiseLog(
        sensor_id=data.sensor_id,
        decibel=data.decibel,
        noise_type="AI 분석 중",
        timestamp=data.timestamp
    )
    db.add(new_log)
    db.flush()
    
    if data.decibel > 40:
        sensor = db.query(models.Sensor).filter(models.Sensor.sensor_id == data.sensor_id).first()
        unit = sensor.location_unit if sensor else data.sensor_id
        
        ai_draft = generate_ai_message(unit, data.decibel)
        new_med = models.Mediation(target_unit=unit, ai_message=ai_draft, status="대기")
        db.add(new_med)
        # 🤖 AI 메시지가 생성되면 서버 터미널에 찍힙니다.
        print(f"🤖 AI: {unit} 세대 중재 메시지 생성 완료!")

    db.commit()
    return {"status": "success"}

@app.get("/api/v1/mediations", response_model=List[MediationResponse])
def get_mediations(db: Session = Depends(get_db)):
    return db.query(models.Mediation).order_by(models.Mediation.created_at.desc()).all()