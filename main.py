from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from datetime import datetime, date
from typing import List, Optional

import models
from database import engine, get_db

# DB 테이블 생성
models.Base.metadata.create_all(bind=engine)

# 초기 seed 데이터
db_init = next(get_db())

if db_init.query(models.Household).count() == 0:
    households = [
        models.Household(building_name="A동", unit_number="101호", floor=1, alias="A-101"),
        models.Household(building_name="A동", unit_number="201호", floor=2, alias="A-201"),
        models.Household(building_name="B동", unit_number="102호", floor=1, alias="B-102"),
    ]
    db_init.add_all(households)
    db_init.commit()

if db_init.query(models.Sensor).count() == 0:
    test_sensors = [
        models.Sensor(sensor_id="SENSOR-A101-01", household_id=1, location_unit="A동 101호", source="simulator", is_online=True, battery_level=85),
        models.Sensor(sensor_id="SENSOR-A201-01", household_id=2, location_unit="A동 201호", source="simulator", is_online=True, battery_level=92),
        models.Sensor(sensor_id="SENSOR-B102-01", household_id=3, location_unit="B동 102호", source="arduino", is_online=False, battery_level=12),
    ]
    db_init.add_all(test_sensors)
    db_init.commit()

app = FastAPI(title="쿵로그(KungLog) AI 통합 서버")

# --- Pydantic 스키마 ---

class NoiseData(BaseModel):
    sensor_id: str
    sound_level: float           # decibel → sound_level 통일
    vibration_value: Optional[float] = None
    duration_ms: Optional[int] = None
    timestamp: datetime
    acceleration: Optional[dict] = None

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
    event_summary: Optional[str] = None
    resident_message: Optional[str] = None
    admin_summary: Optional[str] = None
    recommended_action: Optional[str] = None
    generation_method: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

class MediationUpdate(BaseModel):
    status: str

# --- AI 로직 ---

def classify_event(sound_level: float, vibration_value: float = None, duration_ms: int = None, timestamp: datetime = None) -> dict:
    """이벤트 분류 및 심각도 산정"""
    event_type = "background_noise"
    severity = "low"
    severity_score = 0.0
    is_night = False

    if timestamp:
        hour = timestamp.hour
        is_night = hour >= 22 or hour < 7

    if vibration_value and vibration_value >= 600 and sound_level >= 45:
        event_type = "impact_noise"
        severity = "high" if sound_level >= 60 else "medium"
        severity_score = min((sound_level - 40) / 40, 1.0)
    elif sound_level >= 45:
        event_type = "daily_noise"
        severity = "medium"
        severity_score = 0.5
    elif sound_level >= 40:
        event_type = "background_noise"
        severity = "low"
        severity_score = 0.2

    if is_night and severity == "medium":
        severity = "high"
        severity_score = min(severity_score + 0.2, 1.0)

    return {
        "event_type": event_type,
        "severity": severity,
        "severity_score": round(severity_score, 2),
        "is_night": is_night,
        "confidence": 0.85
    }

def generate_ai_message(unit: str, sound_level: float, event_type: str, is_night: bool, generation_method: str = "template") -> dict:
    """비폭력 표현 기반 중재 메시지 생성"""
    time_label = "야간 시간대" if is_night else "해당 시간대"
    type_label = {
        "impact_noise": "충격음",
        "daily_noise": "생활 소음",
        "background_noise": "소음",
        "repeated_vibration": "반복 진동음"
    }.get(event_type, "소음")

    event_summary = f"{sound_level}dB의 {type_label}이 감지되었습니다."
    resident_message = (
        f"{time_label}에 {type_label}이 감지되었습니다. "
        f"혹시 해당 시간대에 바닥 충격이 발생할 수 있는 활동이 있었는지 확인 부탁드립니다."
    )
    admin_summary = f"[{unit}] {sound_level}dB {type_label} 감지. {'야간 발생으로 주의 필요.' if is_night else ''}"
    recommended_action = "quiet_time_request" if is_night else "notice"

    return {
        "ai_message": resident_message,
        "event_summary": event_summary,
        "resident_message": resident_message,
        "admin_summary": admin_summary,
        "recommended_action": recommended_action,
        "generation_method": generation_method
    }

# --- API 엔드포인트 ---

@app.get("/")
def read_root():
    return {"message": "AI 통합 쿵로그 백엔드 가동 중"}

@app.get("/api/v1/dashboard/stats", response_model=DashboardStats)
def get_dashboard_stats(db: Session = Depends(get_db)):
    total = db.query(models.Sensor).count()
    online = db.query(models.Sensor).filter(models.Sensor.is_online == True).count()
    avg_battery = db.query(func.avg(models.Sensor.battery_level)).scalar() or 0
    today = date.today()
    warning_count = db.query(models.NoiseLog).filter(
        func.date(models.NoiseLog.timestamp) == today,
        models.NoiseLog.sound_level > 40
    ).count()
    recent_avg_db = db.query(func.avg(models.NoiseLog.sound_level)).filter(
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

@app.post("/api/v1/sensor-readings")
async def create_sensor_reading(data: NoiseData, db: Session = Depends(get_db)):
    """Arduino/시뮬레이터 데이터 수신 - 메인 엔드포인트"""
    sensor = db.query(models.Sensor).filter(models.Sensor.sensor_id == data.sensor_id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail=f"sensor_id '{data.sensor_id}' 를 찾을 수 없습니다.")

    classification = classify_event(
        sound_level=data.sound_level,
        vibration_value=data.vibration_value,
        duration_ms=data.duration_ms,
        timestamp=data.timestamp
    )

    new_log = models.NoiseLog(
        sensor_id=data.sensor_id,
        household_id=sensor.household_id,
        sound_level=data.sound_level,
        vibration_value=data.vibration_value,
        duration_ms=data.duration_ms,
        event_type=classification["event_type"],
        severity=classification["severity"],
        severity_score=classification["severity_score"],
        is_night=classification["is_night"],
        confidence=classification["confidence"],
        status="new",
        timestamp=data.timestamp
    )
    db.add(new_log)
    db.flush()

    message_created = False
    ai_result = None

    if classification["severity"] in ["medium", "high"]:
        unit = sensor.location_unit
        msg = generate_ai_message(
            unit=unit,
            sound_level=data.sound_level,
            event_type=classification["event_type"],
            is_night=classification["is_night"]
        )
        new_med = models.Mediation(
            noise_log_id=new_log.id,
            household_id=sensor.household_id,
            target_unit=unit,
            ai_message=msg["ai_message"],
            event_summary=msg["event_summary"],
            resident_message=msg["resident_message"],
            admin_summary=msg["admin_summary"],
            recommended_action=msg["recommended_action"],
            generation_method=msg["generation_method"],
            status="대기"
        )
        db.add(new_med)
        message_created = True
        ai_result = msg

    db.commit()

    return {
        "status": "success",
        "noise_log": {
            "id": new_log.id,
            "event_type": classification["event_type"],
            "severity": classification["severity"],
            "is_night": classification["is_night"]
        },
        "message_created": message_created,
        "ai_result": ai_result
    }

@app.get("/api/v1/noise-logs")
def get_noise_logs(household_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(models.NoiseLog).order_by(models.NoiseLog.timestamp.desc())
    if household_id:
        query = query.filter(models.NoiseLog.household_id == household_id)
    logs = query.limit(50).all()
    return {"logs": [
        {
            "id": log.id,
            "sensor_id": log.sensor_id,
            "household_id": log.household_id,
            "sound_level": log.sound_level,
            "vibration_value": log.vibration_value,
            "event_type": log.event_type,
            "severity": log.severity,
            "is_night": log.is_night,
            "status": log.status,
            "timestamp": log.timestamp
        } for log in logs
    ]}

@app.get("/api/v1/noise-logs/recent")
def get_recent_noise_logs(since: Optional[datetime] = None, db: Session = Depends(get_db)):
    query = db.query(models.NoiseLog).order_by(models.NoiseLog.timestamp.desc())
    if since:
        query = query.filter(models.NoiseLog.timestamp > since)
    logs = query.limit(20).all()
    return {"logs": logs}

@app.get("/api/v1/mediations", response_model=List[MediationResponse])
def get_mediations(db: Session = Depends(get_db)):
    return db.query(models.Mediation).order_by(models.Mediation.created_at.desc()).all()

@app.patch("/api/v1/mediations/{med_id}", response_model=MediationResponse)
def update_mediation_status(med_id: int, data: MediationUpdate, db: Session = Depends(get_db)):
    med = db.query(models.Mediation).filter(models.Mediation.id == med_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="해당 중재 정보를 찾을 수 없습니다.")
    med.status = data.status
    db.commit()
    db.refresh(med)
    return med