from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from datetime import datetime, date, timedelta
from typing import List, Optional
import json

import models
from database import engine, get_db

import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
load_dotenv(dotenv_path="/Users/ijiho/backend/.env")
ENABLE_OPENAI = os.getenv("ENABLE_OPENAI", "false").lower() == "true"
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if ENABLE_OPENAI else None

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
    sound_level: float
    vibration_value: float        # 필수로 변경
    duration_ms: int              # 필수로 변경
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
    status: Optional[str] = None
    ai_message: Optional[str] = None
    resident_message: Optional[str] = None

# --- AI 로직 ---

def classify_event(sound_level: float, vibration_value: float = None, duration_ms: int = None, timestamp: datetime = None) -> dict:
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

def analyze_patterns(household_id: int, db: Session) -> dict:
    """최근 7일 패턴 분석"""
    seven_days_ago = datetime.now() - timedelta(days=7)
    logs = db.query(models.NoiseLog).filter(
        models.NoiseLog.household_id == household_id,
        models.NoiseLog.timestamp >= seven_days_ago
    ).all()

    total_count = len(logs)
    night_count = sum(1 for l in logs if l.is_night)
    high_count = sum(1 for l in logs if l.severity == "high")

    needs_mediation = night_count >= 3 or high_count >= 5 or total_count >= 15

    return {
        "total_count": total_count,
        "night_count": night_count,
        "high_count": high_count,
        "needs_mediation": needs_mediation,
        "period_days": 7
    }

def generate_ai_message(unit: str, sound_level: float, event_type: str, is_night: bool) -> dict:
    time_label = "야간 시간대" if is_night else "해당 시간대"
    type_label = {
        "impact_noise": "충격음",
        "daily_noise": "생활 소음",
        "background_noise": "소음",
        "repeated_vibration": "반복 진동음"
    }.get(event_type, "소음")

    resident_message = (
        f"{time_label}에 {type_label}이 감지되었습니다. "
        f"혹시 해당 시간대에 바닥 충격이 발생할 수 있는 활동이 있었는지 확인 부탁드립니다."
    )
    event_summary = f"{sound_level}dB의 {type_label}이 감지되었습니다."
    admin_summary = f"[{unit}] {sound_level}dB {type_label} 감지. {'야간 발생으로 주의 필요.' if is_night else ''}"
    recommended_action = "quiet_time_request" if is_night else "notice"
    generation_method = "template"

    tone_check = {"checked": True, "tone": "neutral", "is_violent": False}

    if ENABLE_OPENAI and client:
        try:
            prompt = f"""
층간소음 중재 메시지를 작성해주세요. 감정 없이 중립적으로 작성하세요.

상황:
- 세대: {unit}
- 소음 유형: {type_label}
- 소음 강도: {sound_level}dB
- 야간 여부: {"야간" if is_night else "주간"}

다음 형식으로 작성하세요:
- 주민용 메시지: (부드럽고 중립적인 안내문)
- 관리자 요약: (간단한 상황 요약)
"""
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300
            )
            content = response.choices[0].message.content
            resident_message = content
            generation_method = "llm"
        except Exception as e:
            print(f"⚠️ OpenAI 호출 실패, fallback 사용: {e}")
            generation_method = "template"

    return {
        "ai_message": resident_message,
        "event_summary": event_summary,
        "resident_message": resident_message,
        "admin_summary": admin_summary,
        "recommended_action": recommended_action,
        "generation_method": generation_method,
        "tone_check": tone_check
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
    sensor = db.query(models.Sensor).filter(models.Sensor.sensor_id == data.sensor_id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail=f"sensor_id '{data.sensor_id}' 를 찾을 수 없습니다.")

    # 1. classify_event
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

    # 2. analyze_patterns
    pattern_result = analyze_patterns(sensor.household_id, db)

    message_created = False
    ai_result = None

    # 3. generate_mediation_message (severity >= medium 또는 needs_mediation)
    if classification["severity"] in ["medium", "high"] or pattern_result["needs_mediation"]:
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
            tone_check_json=json.dumps(msg["tone_check"], ensure_ascii=False),
            status="pending"
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
        "pattern_result": pattern_result,
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

@app.get("/api/v1/households/{household_id}/patterns")
def get_household_patterns(household_id: int, db: Session = Depends(get_db)):
    pattern_result = analyze_patterns(household_id, db)
    return pattern_result

@app.get("/api/v1/mediations", response_model=List[MediationResponse])
def get_mediations(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.Mediation).order_by(models.Mediation.created_at.desc())
    if status:
        query = query.filter(models.Mediation.status == status)
    return query.all()

@app.get("/api/v1/mediations/{med_id}", response_model=MediationResponse)
def get_mediation(med_id: int, db: Session = Depends(get_db)):
    med = db.query(models.Mediation).filter(models.Mediation.id == med_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="해당 중재 정보를 찾을 수 없습니다.")
    return med

@app.patch("/api/v1/mediations/{med_id}", response_model=MediationResponse)
def update_mediation_status(med_id: int, data: MediationUpdate, db: Session = Depends(get_db)):
    med = db.query(models.Mediation).filter(models.Mediation.id == med_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="해당 중재 정보를 찾을 수 없습니다.")
    if data.status:
        med.status = data.status
    if data.ai_message:
        med.ai_message = data.ai_message
    if data.resident_message:
        med.resident_message = data.resident_message
    db.commit()
    db.refresh(med)
    return med

@app.get("/api/v1/admin/cases")
def get_admin_cases(db: Session = Depends(get_db)):
    mediations = db.query(models.Mediation).order_by(models.Mediation.created_at.desc()).all()
    return {"cases": [
        {
            "id": m.id,
            "target_unit": m.target_unit,
            "ai_message": m.ai_message,
            "event_summary": m.event_summary,
            "admin_summary": m.admin_summary,
            "recommended_action": m.recommended_action,
            "generation_method": m.generation_method,
            "status": m.status,
            "created_at": m.created_at
        } for m in mediations
    ]}

# --- 공지사항 ---

class NoticeCreate(BaseModel):
    title: str
    content: str
    notice_type: str  # urgent, general, manner, equipment
    target_type: str  # all, specific
    target_households: Optional[list] = None

class NoticeResponse(BaseModel):
    id: int
    title: str
    content: str
    notice_type: str
    target_type: str
    target_households: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

@app.post("/api/v1/notices")
def create_notice(data: NoticeCreate, db: Session = Depends(get_db)):
    new_notice = models.Notice(
        title=data.title,
        content=data.content,
        notice_type=data.notice_type,
        target_type=data.target_type,
        target_households=json.dumps(data.target_households) if data.target_households else None,
        status="sent",
        sent_at=datetime.now()
    )
    db.add(new_notice)
    db.commit()
    db.refresh(new_notice)
    return {"status": "success", "notice_id": new_notice.id}

@app.get("/api/v1/notices", response_model=List[NoticeResponse])
def get_notices(notice_type: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.Notice).order_by(models.Notice.created_at.desc())
    if notice_type:
        query = query.filter(models.Notice.notice_type == notice_type)
    return query.all()

@app.get("/api/v1/notices/{notice_id}", response_model=NoticeResponse)
def get_notice(notice_id: int, db: Session = Depends(get_db)):
    notice = db.query(models.Notice).filter(models.Notice.id == notice_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다.")
    return notice

@app.post("/api/v1/notices/ai-template")
def get_ai_template(notice_type: str, db: Session = Depends(get_db)):
    templates = {
        "urgent": {
            "title": "[긴급] 층간소음 주의 안내",
            "content": "관리사무소입니다. 최근 층간소음 민원이 증가하고 있습니다. 야간 시간대(22시~07시) 소음에 각별히 주의해 주시기 바랍니다."
        },
        "general": {
            "title": "[공지] 층간소음 예절 안내",
            "content": "관리사무소입니다. 쾌적한 주거환경을 위해 층간소음 예절을 지켜주시기 바랍니다."
        },
        "manner": {
            "title": "[생활매너] 발소리 줄이기 안내",
            "content": "층간소음을 예방하기 위해 실내에서 슬리퍼 착용 및 뛰는 행동을 자제해 주시기 바랍니다."
        },
        "equipment": {
            "title": "[장비점검] IoT 센서 점검 안내",
            "content": "층간소음 측정 센서 정기 점검이 예정되어 있습니다. 일시 및 세대 안내는 별도 공지 부탁드립니다."
        }
    }
    template = templates.get(notice_type, templates["general"])
    return {"template": template}

# --- 리포트 ---

@app.get("/api/v1/reports/household/{household_id}")
def get_household_report(household_id: int, start_date: Optional[str] = None, end_date: Optional[str] = None, db: Session = Depends(get_db)):
    """세대별 종합 리포트"""
    household = db.query(models.Household).filter(models.Household.id == household_id).first()
    if not household:
        raise HTTPException(status_code=404, detail="세대를 찾을 수 없습니다.")

    query = db.query(models.NoiseLog).filter(models.NoiseLog.household_id == household_id)

    if start_date:
        query = query.filter(models.NoiseLog.timestamp >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.filter(models.NoiseLog.timestamp <= datetime.fromisoformat(end_date))

    logs = query.all()

    total_count = len(logs)
    night_count = sum(1 for l in logs if l.is_night)
    high_count = sum(1 for l in logs if l.severity == "high")
    avg_sound = round(sum(l.sound_level for l in logs) / total_count, 1) if total_count > 0 else 0

    event_types = {}
    for log in logs:
        event_types[log.event_type] = event_types.get(log.event_type, 0) + 1

    return {
        "household": {
            "id": household.id,
            "building_name": household.building_name,
            "unit_number": household.unit_number,
            "alias": household.alias
        },
        "period": {
            "start_date": start_date,
            "end_date": end_date
        },
        "summary": {
            "total_count": total_count,
            "night_count": night_count,
            "high_count": high_count,
            "avg_sound_level": avg_sound,
            "event_types": event_types
        },
        "logs": [
            {
                "id": l.id,
                "sound_level": l.sound_level,
                "event_type": l.event_type,
                "severity": l.severity,
                "is_night": l.is_night,
                "timestamp": l.timestamp
            } for l in logs
        ]
    }

@app.get("/api/v1/reports/monthly")
def get_monthly_report(year: int, month: int, db: Session = Depends(get_db)):
    """전체 동 월간 통계"""
    from datetime import date
    import calendar

    start = datetime(year, month, 1)
    end = datetime(year, month, calendar.monthrange(year, month)[1], 23, 59, 59)

    logs = db.query(models.NoiseLog).filter(
        models.NoiseLog.timestamp >= start,
        models.NoiseLog.timestamp <= end
    ).all()

    total_count = len(logs)
    night_count = sum(1 for l in logs if l.is_night)
    high_count = sum(1 for l in logs if l.severity == "high")

    household_stats = {}
    for log in logs:
        hid = log.household_id
        if hid not in household_stats:
            household_stats[hid] = {"count": 0, "night_count": 0, "high_count": 0}
        household_stats[hid]["count"] += 1
        if log.is_night:
            household_stats[hid]["night_count"] += 1
        if log.severity == "high":
            household_stats[hid]["high_count"] += 1

    return {
        "period": {"year": year, "month": month},
        "summary": {
            "total_count": total_count,
            "night_count": night_count,
            "high_count": high_count
        },
        "household_stats": household_stats
    }

@app.get("/api/v1/reports/custom")
def get_custom_report(
    household_id: Optional[int] = None,
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """커스텀 리포트"""
    query = db.query(models.NoiseLog)

    if household_id:
        query = query.filter(models.NoiseLog.household_id == household_id)
    if event_type:
        query = query.filter(models.NoiseLog.event_type == event_type)
    if severity:
        query = query.filter(models.NoiseLog.severity == severity)
    if start_date:
        query = query.filter(models.NoiseLog.timestamp >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.filter(models.NoiseLog.timestamp <= datetime.fromisoformat(end_date))

    logs = query.order_by(models.NoiseLog.timestamp.desc()).all()
    total_count = len(logs)
    avg_sound = round(sum(l.sound_level for l in logs) / total_count, 1) if total_count > 0 else 0

    return {
        "filters": {
            "household_id": household_id,
            "event_type": event_type,
            "severity": severity,
            "start_date": start_date,
            "end_date": end_date
        },
        "summary": {
            "total_count": total_count,
            "avg_sound_level": avg_sound
        },
        "logs": [
            {
                "id": l.id,
                "household_id": l.household_id,
                "sound_level": l.sound_level,
                "event_type": l.event_type,
                "severity": l.severity,
                "is_night": l.is_night,
                "timestamp": l.timestamp
            } for l in logs
        ]
    }

# --- PDF 다운로드 ---
from fastapi.responses import StreamingResponse
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import io

def create_pdf_report(title: str, data: dict) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # 제목
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, title)

    # 날짜
    c.setFont("Helvetica", 10)
    c.drawString(50, height - 70, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    y = height - 110

    # 요약 정보
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Summary")
    y -= 20

    c.setFont("Helvetica", 10)
    for key, value in data.get("summary", {}).items():
        c.drawString(60, y, f"{key}: {value}")
        y -= 15

    y -= 10

    # 로그 목록
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Noise Logs")
    y -= 20

    c.setFont("Helvetica", 9)
    for log in data.get("logs", [])[:30]:  # 최대 30개
        line = f"ID:{log['id']} | {log.get('timestamp', '')} | {log.get('event_type', '')} | {log.get('severity', '')} | {log.get('sound_level', '')}dB"
        c.drawString(60, y, line)
        y -= 13
        if y < 50:
            c.showPage()
            y = height - 50

    c.save()
    buffer.seek(0)
    return buffer.getvalue()

@app.get("/api/v1/reports/household/{household_id}/pdf")
def download_household_pdf(household_id: int, db: Session = Depends(get_db)):
    household = db.query(models.Household).filter(models.Household.id == household_id).first()
    if not household:
        raise HTTPException(status_code=404, detail="세대를 찾을 수 없습니다.")

    logs = db.query(models.NoiseLog).filter(models.NoiseLog.household_id == household_id).all()
    total_count = len(logs)
    night_count = sum(1 for l in logs if l.is_night)
    high_count = sum(1 for l in logs if l.severity == "high")
    avg_sound = round(sum(l.sound_level for l in logs) / total_count, 1) if total_count > 0 else 0

    data = {
        "summary": {
            "household": f"{household.building_name} {household.unit_number}",
            "total_count": total_count,
            "night_count": night_count,
            "high_count": high_count,
            "avg_sound_level": avg_sound
        },
        "logs": [
            {
                "id": l.id,
                "sound_level": l.sound_level,
                "event_type": l.event_type,
                "severity": l.severity,
                "is_night": l.is_night,
                "timestamp": str(l.timestamp)
            } for l in logs
        ]
    }

    pdf_bytes = create_pdf_report(f"Household Report - {household.alias}", data)

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=report_{household.alias}.pdf"}
    )

@app.get("/api/v1/reports/monthly/pdf")
def download_monthly_pdf(year: int, month: int, db: Session = Depends(get_db)):
    import calendar
    start = datetime(year, month, 1)
    end = datetime(year, month, calendar.monthrange(year, month)[1], 23, 59, 59)

    logs = db.query(models.NoiseLog).filter(
        models.NoiseLog.timestamp >= start,
        models.NoiseLog.timestamp <= end
    ).all()

    total_count = len(logs)
    night_count = sum(1 for l in logs if l.is_night)
    high_count = sum(1 for l in logs if l.severity == "high")
    avg_sound = round(sum(l.sound_level for l in logs) / total_count, 1) if total_count > 0 else 0

    data = {
        "summary": {
            "period": f"{year}-{month:02d}",
            "total_count": total_count,
            "night_count": night_count,
            "high_count": high_count,
            "avg_sound_level": avg_sound
        },
        "logs": [
            {
                "id": l.id,
                "sound_level": l.sound_level,
                "event_type": l.event_type,
                "severity": l.severity,
                "is_night": l.is_night,
                "timestamp": str(l.timestamp)
            } for l in logs
        ]
    }

    pdf_bytes = create_pdf_report(f"Monthly Report - {year}.{month:02d}", data)

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=monthly_report_{year}_{month:02d}.pdf"}
    )