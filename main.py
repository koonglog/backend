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

# 2. 초기 센서 데이터 자동 삽입 (테스트용 데이터)
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

# --- Pydantic 모델 (Schemas) ---

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

class MediationUpdate(BaseModel):
    status: str # "대기", "승인", "발송완료" 등

# --- AI 로직: 중재 메시지 생성기 ---

def generate_ai_message(unit: str, db_level: float):
    # Rule-based 기반의 AI 중재 초안 생성 로직
    if db_level > 60:
        return f"[{unit}] 현재 매우 심한 소음({db_level}dB)이 감지되었습니다. 즉시 확인 부탁드립니다."
    else:
        return f"[{unit}] 층간소음 기준을 초과하는 소음({db_level}dB)이 발생했습니다. 주의 부탁드립니다."

# --- API 엔드포인트 ---

@app.get("/")
def read_root():
    return {"message": "AI 통합 쿵로그 백엔드 가동 중"}

# [Dashboard] 통계 데이터 조회
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

# [Noise] 소음 로그 수신 및 저장
@app.post("/api/v1/noise-logs")
async def create_noise_log(data: NoiseData, db: Session = Depends(get_db)):
    print(f"📩 데이터 도착: {data.sensor_id} - {data.decibel}dB")

    new_log = models.NoiseLog(
        sensor_id=data.sensor_id,
        decibel=data.decibel,
        noise_type="AI 분석 중",
        timestamp=data.timestamp
    )
    db.add(new_log)
    db.flush() 
    
    # AI 중재 로직 가동
    if data.decibel > 40:
        sensor = db.query(models.Sensor).filter(models.Sensor.sensor_id == data.sensor_id).first()
        unit = sensor.location_unit if sensor else data.sensor_id
        
        ai_draft = generate_ai_message(unit, data.decibel)
        new_med = models.Mediation(target_unit=unit, ai_message=ai_draft, status="대기")
        db.add(new_med)
        print(f"🤖 AI: {unit} 세대 중재 메시지 생성 완료!")

    db.commit()
    return {"status": "success"}

# [Mediation] 중재 메시지 조회 및 상태 관리
@app.get("/api/v1/mediations", response_model=List[MediationResponse])
def get_mediations(db: Session = Depends(get_db)):
    return db.query(models.Mediation).order_by(models.Mediation.created_at.desc()).all()

@app.patch("/api/v1/mediations/{med_id}", response_model=MediationResponse)
def update_mediation_status(med_id: int, data: MediationUpdate, db: Session = Depends(get_db)):
    # 프론트엔드 담당자의 '승인' 요청을 처리하는 API
    med = db.query(models.Mediation).filter(models.Mediation.id == med_id).first()
    
    if not med:
        raise HTTPException(status_code=404, detail="해당 중재 정보를 찾을 수 없습니다.")
    
    med.status = data.status
    db.commit()
    db.refresh(med)
    
    print(f"✅ 중재 상태 변경: ID {med_id} -> {data.status}")
    return med