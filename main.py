from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from datetime import datetime, date, timedelta, timezone
from typing import List, Optional

import base64
import csv
import hashlib
import io
import json
import math
import requests
import secrets

import models
from database import engine, get_db

import os
from dotenv import load_dotenv
from openai import OpenAI

KST = timezone(timedelta(hours=9))
UTC = timezone.utc
SEVERITY_LEVELS = {"low", "medium", "high", "critical"}
MEDIATION_SEVERITIES = {"medium", "high", "critical"}
HIGH_OR_CRITICAL_SEVERITIES = {"high", "critical"}

load_dotenv()
load_dotenv(dotenv_path="/Users/ijiho/backend/.env")
ENABLE_OPENAI = os.getenv("ENABLE_OPENAI", "false").lower() == "true"
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if ENABLE_OPENAI else None
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "https://ai-production-a761.up.railway.app")
AUTO_SEED_DEMO_DATA = os.getenv("AUTO_SEED_DEMO_DATA", "true").lower() == "true"
DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000,https://koonglog.vercel.app"
REQUIRED_CORS_ORIGINS = ["https://koonglog.vercel.app"]
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]
for origin in REQUIRED_CORS_ORIGINS:
    if origin not in CORS_ALLOWED_ORIGINS:
        CORS_ALLOWED_ORIGINS.append(origin)
DEFAULT_ADMIN_EMAIL = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@koonglog.com")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin1234")

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"

def verify_password(password: str, stored_hash: Optional[str]) -> bool:
    if not stored_hash:
        return False
    try:
        algorithm, salt, digest_hex = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return secrets.compare_digest(digest.hex(), digest_hex)

def create_access_token(admin_id: int, email: str) -> str:
    payload = f"{admin_id}:{email}:{secrets.token_urlsafe(24)}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")

# DB 테이블 생성
models.Base.metadata.create_all(bind=engine)

def ensure_sqlite_schema():
    """create_all은 기존 테이블 컬럼을 갱신하지 않으므로 개발 DB에 필요한 컬럼을 보정한다."""
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as conn:
        table_names = {
            row[0] for row in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        if "raw_sensor_readings" in table_names:
            raw_columns = {
                row[1] for row in conn.exec_driver_sql("PRAGMA table_info(raw_sensor_readings)").fetchall()
            }
            raw_column_sql = {
                "household_id": "ALTER TABLE raw_sensor_readings ADD COLUMN household_id INTEGER",
                "vibration_value": "ALTER TABLE raw_sensor_readings ADD COLUMN vibration_value FLOAT",
                "duration_ms": "ALTER TABLE raw_sensor_readings ADD COLUMN duration_ms INTEGER",
                "acceleration_x": "ALTER TABLE raw_sensor_readings ADD COLUMN acceleration_x FLOAT",
                "acceleration_y": "ALTER TABLE raw_sensor_readings ADD COLUMN acceleration_y FLOAT",
                "acceleration_z": "ALTER TABLE raw_sensor_readings ADD COLUMN acceleration_z FLOAT",
                "received_at": "ALTER TABLE raw_sensor_readings ADD COLUMN received_at DATETIME",
                "sensor_timestamp": "ALTER TABLE raw_sensor_readings ADD COLUMN sensor_timestamp DATETIME",
            }
            for column_name, sql in raw_column_sql.items():
                if column_name not in raw_columns:
                    conn.exec_driver_sql(sql)

        if "noise_events" in table_names:
            noise_event_columns = {
                row[1] for row in conn.exec_driver_sql("PRAGMA table_info(noise_events)").fetchall()
            }
            noise_event_column_sql = {
                "severity_score": "ALTER TABLE noise_events ADD COLUMN severity_score FLOAT",
                "confidence": "ALTER TABLE noise_events ADD COLUMN confidence FLOAT",
                "is_night": "ALTER TABLE noise_events ADD COLUMN is_night BOOLEAN DEFAULT 0",
                "is_meaningful": "ALTER TABLE noise_events ADD COLUMN is_meaningful BOOLEAN DEFAULT 0",
                "pattern_label": "ALTER TABLE noise_events ADD COLUMN pattern_label VARCHAR",
                "avg_sound_level": "ALTER TABLE noise_events ADD COLUMN avg_sound_level FLOAT",
                "max_sound_level": "ALTER TABLE noise_events ADD COLUMN max_sound_level FLOAT",
                "avg_vibration": "ALTER TABLE noise_events ADD COLUMN avg_vibration FLOAT",
                "duration_ms": "ALTER TABLE noise_events ADD COLUMN duration_ms INTEGER",
                "sample_count": "ALTER TABLE noise_events ADD COLUMN sample_count INTEGER DEFAULT 1",
                "started_at": "ALTER TABLE noise_events ADD COLUMN started_at DATETIME",
                "ended_at": "ALTER TABLE noise_events ADD COLUMN ended_at DATETIME",
                "status": "ALTER TABLE noise_events ADD COLUMN status VARCHAR DEFAULT 'new'",
            }
            for column_name, sql in noise_event_column_sql.items():
                if column_name not in noise_event_columns:
                    conn.exec_driver_sql(sql)

        if "households" in table_names:
            household_columns = {
                row[1] for row in conn.exec_driver_sql("PRAGMA table_info(households)").fetchall()
            }
            household_column_sql = {
                "username": "ALTER TABLE households ADD COLUMN username VARCHAR",
                "email": "ALTER TABLE households ADD COLUMN email VARCHAR",
                "password_hash": "ALTER TABLE households ADD COLUMN password_hash VARCHAR",
                "apartment_name": "ALTER TABLE households ADD COLUMN apartment_name VARCHAR",
                "resident_name": "ALTER TABLE households ADD COLUMN resident_name VARCHAR",
                "phone_number": "ALTER TABLE households ADD COLUMN phone_number VARCHAR",
                "quiet_start_time": "ALTER TABLE households ADD COLUMN quiet_start_time VARCHAR",
                "quiet_end_time": "ALTER TABLE households ADD COLUMN quiet_end_time VARCHAR",
                "is_active": "ALTER TABLE households ADD COLUMN is_active BOOLEAN DEFAULT 1",
                "last_login_at": "ALTER TABLE households ADD COLUMN last_login_at DATETIME",
                "created_at": "ALTER TABLE households ADD COLUMN created_at DATETIME",
            }
            for column_name, sql in household_column_sql.items():
                if column_name not in household_columns:
                    conn.exec_driver_sql(sql)

        if "admins" in table_names:
            admin_columns = {
                row[1] for row in conn.exec_driver_sql("PRAGMA table_info(admins)").fetchall()
            }
            admin_column_sql = {
                "email": "ALTER TABLE admins ADD COLUMN email VARCHAR",
                "password_hash": "ALTER TABLE admins ADD COLUMN password_hash VARCHAR",
                "password": "ALTER TABLE admins ADD COLUMN password VARCHAR",
                "office_name": "ALTER TABLE admins ADD COLUMN office_name VARCHAR",
                "office_address": "ALTER TABLE admins ADD COLUMN office_address VARCHAR",
                "phone_number": "ALTER TABLE admins ADD COLUMN phone_number VARCHAR",
                "is_active": "ALTER TABLE admins ADD COLUMN is_active BOOLEAN DEFAULT 1",
                "last_login_at": "ALTER TABLE admins ADD COLUMN last_login_at DATETIME",
                "created_at": "ALTER TABLE admins ADD COLUMN created_at DATETIME",
            }
            for column_name, sql in admin_column_sql.items():
                if column_name not in admin_columns:
                    conn.exec_driver_sql(sql)

        if "mediations" in table_names:
            mediation_columns = {
                row[1] for row in conn.exec_driver_sql("PRAGMA table_info(mediations)").fetchall()
            }
            if "noise_event_id" not in mediation_columns:
                conn.exec_driver_sql("ALTER TABLE mediations ADD COLUMN noise_event_id INTEGER")

ensure_sqlite_schema()

# 초기 seed 데이터
db_init = next(get_db())

if db_init.query(models.Household).count() == 0:
    households = [
        models.Household(username="aster03", email="aster03@koonglog.com", password_hash=hash_password("resident1234"), apartment_name="쿵로그아파트", building_name="A동", unit_number="101호", floor=1, alias="A-101", resident_name="김철수", phone_number="010-1234-5678", is_active=True, quiet_start_time="22:00", quiet_end_time="07:00"),
        models.Household(username="resident201", email="resident201@koonglog.com", password_hash=hash_password("resident1234"), apartment_name="쿵로그아파트", building_name="A동", unit_number="201호", floor=2, alias="A-201", resident_name="이영희", phone_number="010-2345-6789", is_active=True),
        models.Household(username="resident102", email="resident102@koonglog.com", password_hash=hash_password("resident1234"), apartment_name="쿵로그아파트", building_name="B동", unit_number="102호", floor=1, alias="B-102", resident_name="박민수", phone_number="010-3456-7890", is_active=True),
    ]
    db_init.add_all(households)
    db_init.commit()
else:
    seed_households = db_init.query(models.Household).order_by(models.Household.id.asc()).all()
    changed = False
    default_usernames = ["aster03", "resident201", "resident102"]
    default_emails = ["aster03@koonglog.com", "resident201@koonglog.com", "resident102@koonglog.com"]
    default_residents = [
        ("김철수", "010-1234-5678"),
        ("이영희", "010-2345-6789"),
        ("박민수", "010-3456-7890"),
    ]
    for index, household in enumerate(seed_households[:3]):
        if not household.username:
            household.username = default_usernames[index]
            changed = True
        if not household.email:
            household.email = default_emails[index]
            changed = True
        if not household.password_hash:
            household.password_hash = hash_password("resident1234")
            changed = True
        if not household.apartment_name:
            household.apartment_name = "쿵로그아파트"
            changed = True
        if not household.resident_name:
            household.resident_name = default_residents[index][0]
            changed = True
        if not household.phone_number:
            household.phone_number = default_residents[index][1]
            changed = True
        if household.is_active is None:
            household.is_active = True
            changed = True
        if not household.quiet_start_time and index == 0:
            household.quiet_start_time = "22:00"
            household.quiet_end_time = "07:00"
            changed = True
    if changed:
        db_init.commit()

if db_init.query(models.Sensor).count() == 0:
    test_sensors = [
        models.Sensor(sensor_id="SENSOR-A101-01", household_id=1, location_unit="A동 101호", source="simulator", is_online=True, battery_level=85),
        models.Sensor(sensor_id="SENSOR-A201-01", household_id=2, location_unit="A동 201호", source="simulator", is_online=True, battery_level=92),
        models.Sensor(sensor_id="SENSOR-B102-01", household_id=3, location_unit="B동 102호", source="arduino", is_online=False, battery_level=12),
        models.Sensor(sensor_id="KOONG-LOG-MIRA", household_id=1, location_unit="A동 101호", source="arduino",
                      is_online=True, battery_level=100),  # 추가
    ]
    db_init.add_all(test_sensors)
    db_init.commit()

if db_init.query(models.Admin).count() == 0:
    admin = models.Admin(
        username="admin001",
        email=DEFAULT_ADMIN_EMAIL,
        password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
        name="김관리",
        office_name="쿵로그 관리사무소",
        office_address="서울시 쿵로그아파트",
        phone_number="010-0000-0000",
        role="관리소장",
        team="관리팀",
        permission_level="master",
        is_active=True
    )
    db_init.add(admin)
    db_init.commit()
else:
    default_admin = db_init.query(models.Admin).order_by(models.Admin.id.asc()).first()
    changed = False
    if default_admin and not default_admin.email:
        default_admin.email = DEFAULT_ADMIN_EMAIL
        changed = True
    if default_admin and not default_admin.password_hash:
        default_admin.password_hash = hash_password(DEFAULT_ADMIN_PASSWORD)
        changed = True
    if default_admin and not default_admin.office_name:
        default_admin.office_name = "쿵로그 관리사무소"
        changed = True
    if default_admin and not default_admin.office_address:
        default_admin.office_address = "서울시 쿵로그아파트"
        changed = True
    if default_admin and not default_admin.phone_number:
        default_admin.phone_number = "010-0000-0000"
        changed = True
    if default_admin and default_admin.is_active is None:
        default_admin.is_active = True
        changed = True
    if changed:
        db_init.commit()

if db_init.query(models.NoiseLog).count() == 0:
    from datetime import datetime, timedelta
    import random

    event_types = ["impact_noise", "daily_noise", "background_noise"]
    severities = ["low", "medium", "high"]

    dummy_logs = []
    for i in range(20):
        dummy_logs.append(models.NoiseLog(
            sensor_id="SENSOR-A101-01",
            household_id=1,
            sound_level=round(random.uniform(40, 90), 1),
            vibration_value=round(random.uniform(100, 1000), 1),
            duration_ms=random.randint(1000, 10000),
            event_type=random.choice(event_types),
            severity=random.choice(severities),
            severity_score=round(random.uniform(0.1, 1.0), 2),
            is_night=random.choice([True, False]),
            confidence=0.85,
            status="new",
            timestamp=datetime.utcnow() - timedelta(hours=random.randint(0, 24))
        ))
    db_init.add_all(dummy_logs)
    db_init.commit()
    if db_init.query(models.Mediation).count() == 0:
        dummy_mediations = [
            models.Mediation(
                household_id=1,
                target_unit="A동 101호",
                ai_message="안녕하세요. 3층 거주자입니다. 밤 11시 이후 시간대에 충격성 소음이 감지되고 있습니다. 서로 편안한 주거환경을 위해 야간 시간대 소음 저감에 협조 부탁드립니다.",
                event_summary="90.0dB의 충격음이 감지되었습니다.",
                resident_message="위층에서 밤 11시 이후에도 계속 쿵쿵거리는 소리가 들려서 잠을 잘 수가 없습니다.",
                admin_summary="[A동 101호] 90.0dB 충격음 감지. 야간 발생으로 주의 필요.",
                recommended_action="quiet_time_request",
                generation_method="template",
                status="pending"
            ),
            models.Mediation(
                household_id=2,
                target_unit="A동 201호",
                ai_message="안녕하세요. 5층 거주자입니다. 의자 끄는 소리가 계속 들립니다. 편안한 주거환경을 위해 협조 부탁드립니다.",
                event_summary="65.0dB의 생활 소음이 감지되었습니다.",
                resident_message="위층에서 의자 끄는 소리가 계속 납니다.",
                admin_summary="[A동 201호] 65.0dB 생활 소음 감지.",
                recommended_action="notice",
                generation_method="template",
                status="completed"
            ),
            models.Mediation(
                household_id=1,
                target_unit="A동 101호",
                ai_message="안녕하세요. 야간 시간대 반복적인 충격음이 감지되었습니다. 협조 부탁드립니다.",
                event_summary="85.0dB의 충격음이 감지되었습니다.",
                resident_message="매일 밤 11시경 윗집에서 뛰는 소리가 납니다.",
                admin_summary="[A동 101호] 85.0dB 충격음 감지. 야간 발생.",
                recommended_action="quiet_time_request",
                generation_method="template",
                status="completed"
            ),
        ]
        db_init.add_all(dummy_mediations)
        db_init.commit()

app = FastAPI(title="쿵로그(KungLog) AI 통합 서버")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.on_event("startup")
def seed_demo_data_on_startup():
    """웹 서버 시작 시 프론트 확인용 더미 데이터를 최신 날짜로 보정한다."""
    if not AUTO_SEED_DEMO_DATA:
        return

    try:
        from seed_demo_data import seed_demo_data

        seed_demo_data()
    except Exception as exc:
        print(f"[seed] demo data seeding skipped: {exc}")


# --- Pydantic 스키마 ---

class NoiseData(BaseModel):
    sensor_id: str
    sound_level: float
    vibration_value: float
    duration_ms: Optional[int] = None
    timestamp: Optional[datetime] = None
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

class AdminSummary(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    name: str
    office_name: Optional[str] = None
    office_address: Optional[str] = None
    phone_number: Optional[str] = None
    role: str
    team: str
    permission_level: str

class AdminLoginRequest(BaseModel):
    email: str
    password: str

class AdminLoginResponse(BaseModel):
    status: str
    access_token: str
    token_type: str = "bearer"
    admin: AdminSummary

class AdminRegisterRequest(BaseModel):
    email: str
    password: str
    name: str
    office_name: str
    office_address: Optional[str] = None
    phone_number: Optional[str] = None
    username: Optional[str] = None
    role: Optional[str] = "관리소장"

class FindEmailRequest(BaseModel):
    name: str
    phone_number: str

class FindEmailResponse(BaseModel):
    status: str
    email: str

class PasswordResetRequest(BaseModel):
    email: str
    name: str
    new_password: str

class BasicStatusResponse(BaseModel):
    status: str
    message: str

class ResidentSummary(BaseModel):
    household_id: int
    username: Optional[str] = None
    email: Optional[str] = None
    apartment_name: Optional[str] = None
    resident_name: Optional[str] = None
    phone_number: Optional[str] = None
    building_name: str
    unit_number: str
    floor: int
    alias: str
    quiet_start_time: Optional[str] = None
    quiet_end_time: Optional[str] = None

class ResidentLoginRequest(BaseModel):
    username: str
    password: str

class ResidentLoginResponse(BaseModel):
    status: str
    access_token: str
    token_type: str = "bearer"
    resident: ResidentSummary

class ResidentRegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    resident_name: str
    phone_number: Optional[str] = None
    apartment_name: str
    building_name: str
    unit_number: str
    floor: int
    alias: Optional[str] = None
    quiet_start_time: Optional[str] = None
    quiet_end_time: Optional[str] = None
    terms_agreed: bool
    privacy_agreed: bool

class ResidentFindIdRequest(BaseModel):
    resident_name: str
    phone_number: str

class ResidentFindIdResponse(BaseModel):
    status: str
    username: str

class ResidentPasswordResetRequest(BaseModel):
    username: str
    resident_name: str
    phone_number: str
    new_password: str

class ResidentProfileUpdate(BaseModel):
    resident_name: Optional[str] = None
    email: Optional[str] = None
    username: Optional[str] = None
    phone_number: Optional[str] = None

class ResidentApartmentUpdate(BaseModel):
    apartment_name: Optional[str] = None
    building_name: Optional[str] = None
    unit_number: Optional[str] = None
    floor: Optional[int] = None
    alias: Optional[str] = None

class ResidentPasswordUpdate(BaseModel):
    current_password: str
    new_password: str

class NoiseMeasurementCreate(BaseModel):
    sound_level: float
    vibration_value: Optional[float] = 0.0
    duration_ms: Optional[int] = None
    timestamp: Optional[datetime] = None

def serialize_admin(admin: models.Admin) -> dict:
    return {
        "id": admin.id,
        "username": admin.username,
        "email": admin.email,
        "name": admin.name,
        "office_name": admin.office_name,
        "office_address": admin.office_address,
        "phone_number": admin.phone_number,
        "role": admin.role.value if hasattr(admin.role, "value") else admin.role,
        "team": admin.team.value if hasattr(admin.team, "value") else admin.team,
        "permission_level": admin.permission_level,
    }

def normalize_email(email: str) -> str:
    return email.strip().lower()

def normalize_username(username: str) -> str:
    return username.strip()

def serialize_resident(household: models.Household) -> dict:
    return {
        "household_id": household.id,
        "username": household.username,
        "email": household.email,
        "apartment_name": household.apartment_name,
        "resident_name": household.resident_name,
        "phone_number": household.phone_number,
        "building_name": household.building_name,
        "unit_number": household.unit_number,
        "floor": household.floor,
        "alias": household.alias,
        "quiet_start_time": household.quiet_start_time,
        "quiet_end_time": household.quiet_end_time,
    }

def get_household_or_404(household_id: int, db: Session) -> models.Household:
    household = db.query(models.Household).filter(models.Household.id == household_id).first()
    if not household:
        raise HTTPException(status_code=404, detail="세대를 찾을 수 없습니다.")
    return household

# --- 관리자 인증 API ---

@app.post("/api/v1/auth/login", response_model=AdminLoginResponse)
def login_admin(data: AdminLoginRequest, db: Session = Depends(get_db)):
    admin = db.query(models.Admin).filter(models.Admin.email == normalize_email(data.email)).first()
    if not admin or not admin.is_active or not verify_password(data.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")

    admin.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(admin)

    return {
        "status": "success",
        "access_token": create_access_token(admin.id, admin.email or admin.username),
        "token_type": "bearer",
        "admin": serialize_admin(admin)
    }

@app.post("/api/v1/auth/register", response_model=AdminLoginResponse)
def register_admin(data: AdminRegisterRequest, db: Session = Depends(get_db)):
    email = normalize_email(data.email)
    if db.query(models.Admin).filter(models.Admin.email == email).first():
        raise HTTPException(status_code=409, detail="이미 등록된 이메일입니다.")

    username = data.username or email.split("@")[0]
    base_username = username
    suffix = 1
    while db.query(models.Admin).filter(models.Admin.username == username).first():
        suffix += 1
        username = f"{base_username}{suffix}"

    admin = models.Admin(
        username=username,
        email=email,
        password_hash=hash_password(data.password),
        name=data.name,
        office_name=data.office_name,
        office_address=data.office_address,
        phone_number=data.phone_number,
        role=data.role or "관리소장",
        team="관리팀",
        permission_level="manager",
        is_active=True,
        last_login_at=datetime.utcnow()
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    return {
        "status": "success",
        "access_token": create_access_token(admin.id, admin.email or admin.username),
        "token_type": "bearer",
        "admin": serialize_admin(admin)
    }

@app.post("/api/v1/auth/find-email", response_model=FindEmailResponse)
def find_admin_email(data: FindEmailRequest, db: Session = Depends(get_db)):
    admin = db.query(models.Admin).filter(
        models.Admin.name == data.name,
        models.Admin.phone_number == data.phone_number
    ).first()
    if not admin or not admin.email:
        raise HTTPException(status_code=404, detail="일치하는 관리자 계정을 찾을 수 없습니다.")
    return {"status": "success", "email": admin.email}

@app.post("/api/v1/auth/reset-password", response_model=BasicStatusResponse)
def reset_admin_password(data: PasswordResetRequest, db: Session = Depends(get_db)):
    admin = db.query(models.Admin).filter(
        models.Admin.email == normalize_email(data.email),
        models.Admin.name == data.name
    ).first()
    if not admin:
        raise HTTPException(status_code=404, detail="일치하는 관리자 계정을 찾을 수 없습니다.")
    admin.password_hash = hash_password(data.new_password)
    db.commit()
    return {"status": "success", "message": "비밀번호가 변경되었습니다."}

# --- 입주민 인증 API ---

@app.post("/api/v1/residents/auth/login", response_model=ResidentLoginResponse)
def login_resident(data: ResidentLoginRequest, db: Session = Depends(get_db)):
    household = db.query(models.Household).filter(
        models.Household.username == normalize_username(data.username)
    ).first()
    if not household or not household.is_active or not verify_password(data.password, household.password_hash):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")

    household.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(household)

    return {
        "status": "success",
        "access_token": create_access_token(household.id, household.username or household.alias),
        "token_type": "bearer",
        "resident": serialize_resident(household)
    }

@app.post("/api/v1/residents/auth/register", response_model=ResidentLoginResponse)
def register_resident(data: ResidentRegisterRequest, db: Session = Depends(get_db)):
    username = normalize_username(data.username)
    email = normalize_email(data.email)
    if not data.terms_agreed or not data.privacy_agreed:
        raise HTTPException(status_code=400, detail="필수 약관에 동의해야 회원가입할 수 있습니다.")
    if db.query(models.Household).filter(models.Household.username == username).first():
        raise HTTPException(status_code=409, detail="이미 사용 중인 아이디입니다.")
    if db.query(models.Household).filter(models.Household.email == email).first():
        raise HTTPException(status_code=409, detail="이미 사용 중인 이메일입니다.")

    alias = data.alias or f"{data.apartment_name} {data.building_name} {data.unit_number}"
    household = models.Household(
        username=username,
        email=email,
        password_hash=hash_password(data.password),
        resident_name=data.resident_name,
        phone_number=data.phone_number,
        apartment_name=data.apartment_name,
        building_name=data.building_name,
        unit_number=data.unit_number,
        floor=data.floor,
        alias=alias,
        quiet_start_time=data.quiet_start_time,
        quiet_end_time=data.quiet_end_time,
        is_active=True,
        last_login_at=datetime.utcnow()
    )
    db.add(household)
    db.commit()
    db.refresh(household)

    return {
        "status": "success",
        "access_token": create_access_token(household.id, household.username or household.alias),
        "token_type": "bearer",
        "resident": serialize_resident(household)
    }

@app.post("/api/v1/residents/auth/find-id", response_model=ResidentFindIdResponse)
def find_resident_id(data: ResidentFindIdRequest, db: Session = Depends(get_db)):
    household = db.query(models.Household).filter(
        models.Household.resident_name == data.resident_name,
        models.Household.phone_number == data.phone_number
    ).first()
    if not household or not household.username:
        raise HTTPException(status_code=404, detail="일치하는 입주민 계정을 찾을 수 없습니다.")
    return {"status": "success", "username": household.username}

@app.post("/api/v1/residents/auth/reset-password", response_model=BasicStatusResponse)
def reset_resident_password(data: ResidentPasswordResetRequest, db: Session = Depends(get_db)):
    household = db.query(models.Household).filter(
        models.Household.username == normalize_username(data.username),
        models.Household.resident_name == data.resident_name,
        models.Household.phone_number == data.phone_number
    ).first()
    if not household:
        raise HTTPException(status_code=404, detail="일치하는 입주민 계정을 찾을 수 없습니다.")
    household.password_hash = hash_password(data.new_password)
    db.commit()
    return {"status": "success", "message": "비밀번호가 변경되었습니다."}

@app.patch("/api/v1/residents/{household_id}/profile")
def update_resident_profile(household_id: int, data: ResidentProfileUpdate, db: Session = Depends(get_db)):
    household = get_household_or_404(household_id, db)

    if data.username:
        username = normalize_username(data.username)
        existing = db.query(models.Household).filter(
            models.Household.username == username,
            models.Household.id != household_id
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="이미 사용 중인 아이디입니다.")
        household.username = username

    if data.email:
        email = normalize_email(data.email)
        existing = db.query(models.Household).filter(
            models.Household.email == email,
            models.Household.id != household_id
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="이미 사용 중인 이메일입니다.")
        household.email = email

    if data.resident_name:
        household.resident_name = data.resident_name
    if data.phone_number:
        household.phone_number = data.phone_number

    db.commit()
    db.refresh(household)
    return {"status": "success", "resident": serialize_resident(household)}

@app.get("/api/v1/residents/{household_id}/profile")
def get_resident_profile(household_id: int, db: Session = Depends(get_db)):
    household = get_household_or_404(household_id, db)
    return {"resident": serialize_resident(household)}

@app.patch("/api/v1/residents/{household_id}/apartment")
def update_resident_apartment(household_id: int, data: ResidentApartmentUpdate, db: Session = Depends(get_db)):
    household = get_household_or_404(household_id, db)
    if data.apartment_name:
        household.apartment_name = data.apartment_name
    if data.building_name:
        household.building_name = data.building_name
    if data.unit_number:
        household.unit_number = data.unit_number
    if data.floor:
        household.floor = data.floor
    if data.alias:
        household.alias = data.alias
    elif data.apartment_name or data.building_name or data.unit_number:
        apartment_name = household.apartment_name or ""
        household.alias = f"{apartment_name} {household.building_name} {household.unit_number}".strip()

    db.commit()
    db.refresh(household)
    return {"status": "success", "resident": serialize_resident(household)}

@app.patch("/api/v1/residents/{household_id}/password", response_model=BasicStatusResponse)
def update_resident_password(household_id: int, data: ResidentPasswordUpdate, db: Session = Depends(get_db)):
    household = get_household_or_404(household_id, db)
    if not verify_password(data.current_password, household.password_hash):
        raise HTTPException(status_code=400, detail="현재 비밀번호가 일치하지 않습니다.")
    household.password_hash = hash_password(data.new_password)
    db.commit()
    return {"status": "success", "message": "비밀번호가 변경되었습니다."}

# --- AI 연동 로직 ---

def is_night_kst(utc_dt: datetime) -> bool:
    """UTC 시간을 KST로 변환해서 야간 판정"""
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=UTC)
    kst_dt = utc_dt.astimezone(KST)
    hour = kst_dt.hour
    return hour >= 22 or hour < 7

def format_kst(dt: Optional[datetime]) -> Optional[str]:
    """DB에 저장된 UTC/naive datetime을 KST 표시 문자열로 변환한다."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")

def to_utc_iso(value: Optional[datetime]) -> Optional[str]:
    """datetime 값을 AI 서비스에 전달할 UTC ISO 문자열로 변환한다."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

def normalize_severity(severity: str) -> str:
    normalized = str(severity).strip().lower()
    if normalized not in SEVERITY_LEVELS:
        raise HTTPException(
            status_code=502,
            detail=f"AI 이벤트 분류 응답 severity가 허용 범위를 벗어났습니다: {severity}"
        )
    return normalized

def is_high_or_critical(severity: Optional[str]) -> bool:
    return (severity or "").lower() in HIGH_OR_CRITICAL_SEVERITIES

def serialize_noise_event_for_ai(event: models.NoiseEvent) -> dict:
    return {
        "detected_at": to_utc_iso(event.started_at),
        "event_type": event.event_type,
        "severity": event.severity,
        "is_meaningful": bool(event.is_meaningful),
    }

def get_recent_meaningful_events_10min(household_id: int, db: Session) -> list:
    ten_min_ago = datetime.utcnow() - timedelta(minutes=10)
    events = db.query(models.NoiseEvent).filter(
        models.NoiseEvent.household_id == household_id,
        models.NoiseEvent.is_meaningful == True,
        models.NoiseEvent.started_at >= ten_min_ago
    ).order_by(models.NoiseEvent.started_at.asc()).all()
    return [serialize_noise_event_for_ai(event) for event in events]

def classify_event_with_ai(
    data: NoiseData,
    sensor_timestamp: datetime,
    is_night: bool,
    household_id: Optional[int],
    db: Session
) -> dict:
    """AI팀 이벤트 분류 API를 호출하고, 실패하면 요청 실패로 처리한다."""
    if not AI_SERVICE_URL:
        raise HTTPException(status_code=503, detail="AI_SERVICE_URL이 설정되지 않았습니다.")

    acceleration = data.acceleration or {}
    accel_x = float(acceleration.get("x", 0.0) or 0.0)
    accel_y = float(acceleration.get("y", 0.0) or 0.0)
    accel_z = float(acceleration.get("z", 1.0) or 1.0)
    accel_delta = abs(math.sqrt(accel_x ** 2 + accel_y ** 2 + accel_z ** 2) - 1.0)
    recent_events_10min = get_recent_meaningful_events_10min(household_id, db) if household_id else []

    try:
        response = requests.post(
            f"{AI_SERVICE_URL.rstrip('/')}/api/v1/ai/classify-event",
            json={
                "sensor_id": data.sensor_id,
                "source": "backend",
                "household_id": household_id,
                "event_feature": {
                    "sound_level": data.sound_level,
                    "vibration_value": data.vibration_value,
                    "duration_ms": data.duration_ms or 0,
                    "accel_delta": accel_delta,
                    "timestamp": sensor_timestamp.isoformat(),
                    "recent_count_10min": len(recent_events_10min)
                },
                "recent_meaningful_events_10min": recent_events_10min
            },
            timeout=3
        )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"AI 이벤트 분류 호출 실패: {response.status_code} {response.text}"
            )
        result = response.json()
        classification = result.get("classification")
        if not classification:
            raise HTTPException(
                status_code=502,
                detail="AI 이벤트 분류 응답에 classification 필드가 없습니다."
            )
        required_fields = ["event_type", "severity", "is_meaningful"]
        missing = [field for field in required_fields if field not in classification]
        if missing:
            raise HTTPException(
                status_code=502,
                detail=f"AI 이벤트 분류 응답에 필수 필드가 없습니다: {', '.join(missing)}"
            )
        classification["severity"] = normalize_severity(classification["severity"])
        classification.setdefault("severity_score", None)
        classification.setdefault("confidence", None)
        classification.setdefault("is_night", is_night)
        classification["source"] = "ai"
        return classification
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI 이벤트 분류 호출 실패: {e}")

def get_pattern_analysis_payload(household_id: int, db: Session) -> dict:
    """AI팀 패턴 분석 API 스키마에 맞는 최근 7일 이벤트 payload를 구성한다."""
    reference_time = datetime.now(UTC)
    seven_days_ago = reference_time.replace(tzinfo=None) - timedelta(days=7)

    recent_7days = db.query(models.NoiseEvent).filter(
        models.NoiseEvent.household_id == household_id,
        models.NoiseEvent.is_meaningful == True,
        models.NoiseEvent.started_at >= seven_days_ago
    ).order_by(models.NoiseEvent.started_at.asc()).all()

    recent_mediations = db.query(models.Mediation).filter(
        models.Mediation.household_id == household_id,
        models.Mediation.created_at >= seven_days_ago
    ).order_by(models.Mediation.created_at.asc()).all()

    return {
        "household_id": household_id,
        "analysis_period_days": 7,
        "reference_time": to_utc_iso(reference_time),
        "noise_events": [serialize_noise_event_for_ai(event) for event in recent_7days],
        "mediation_messages": [
            {"created_at": to_utc_iso(mediation.created_at)}
            for mediation in recent_mediations
        ]
    }

def analyze_patterns_with_ai(household_id: int, db: Session) -> dict:
    """AI팀 패턴 분석 API를 호출하고, 실패하면 요청 실패로 처리한다."""
    payload = get_pattern_analysis_payload(household_id, db)

    if not AI_SERVICE_URL:
        raise HTTPException(status_code=503, detail="AI_SERVICE_URL이 설정되지 않았습니다.")

    try:
        response = requests.post(
            f"{AI_SERVICE_URL.rstrip('/')}/api/v1/ai/analyze-patterns",
            json=payload,
            timeout=3
        )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"AI 패턴 분석 호출 실패: {response.status_code} {response.text}"
            )
        result = response.json()
        analysis = (
            result.get("analysis")
            or result.get("pattern_analysis")
            or result.get("pattern_result")
            or result
        )
        required_fields = [
            "recent_count_10min",
            "pattern_label",
            "needs_mediation",
            "needs_escalation",
            "summary"
        ]
        missing = [field for field in required_fields if field not in analysis]
        if missing:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": f"AI 패턴 분석 응답에 필수 필드가 없습니다: {', '.join(missing)}",
                    "ai_response": result
                }
            )
        analysis["source"] = "ai"
        return analysis
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI 패턴 분석 호출 실패: {e}")

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

@app.get("/monitor", response_class=HTMLResponse)
def monitor_page():
    return """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>KungLog Monitor</title>
  <style>
    body { margin: 0; font-family: Arial, sans-serif; background: #f7f7f4; color: #171717; }
    header { padding: 20px 28px 14px; border-bottom: 2px solid #111; background: #eee6d8; }
    h1 { margin: 0; font-size: 28px; }
    main { padding: 22px 28px 36px; }
    .links { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; max-width: 760px; }
    a { display: block; padding: 18px; border: 1px solid #d1d1ca; background: white; color: #111; text-decoration: none; }
    strong { display: block; margin-bottom: 8px; font-size: 18px; }
    span { color: #555; font-size: 14px; }
  </style>
</head>
<body>
  <header>
    <h1>KungLog Monitor</h1>
  </header>
  <main>
    <div class="links">
      <a href="/monitor/readings">
        <strong>All Sensor Readings</strong>
        <span>모든 원본 센서 수신값을 테이블로 확인</span>
      </a>
      <a href="/monitor/noise-events">
        <strong>Noise Events</strong>
        <span>AI가 의미 이벤트로 판단한 데이터만 확인</span>
      </a>
    </div>
  </main>
</body>
</html>
"""

def render_monitor_table_page(title: str, subtitle: str, endpoint: str, table_id: str) -> str:
    html = """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__</title>
  <style>
    body { margin: 0; font-family: Arial, sans-serif; background: #f7f7f4; color: #171717; }
    header { padding: 20px 28px 14px; border-bottom: 2px solid #111; background: #eee6d8; }
    h1 { margin: 0; font-size: 28px; }
    main { padding: 22px 28px 36px; }
    nav { margin-bottom: 16px; }
    nav a { color: #111; font-weight: 700; }
    .toolbar { display: flex; align-items: center; gap: 14px; margin-bottom: 18px; font-size: 14px; }
    .status { font-weight: 700; }
    .subtitle { margin: 8px 0 0; color: #555; }
    .table-wrap { overflow: auto; border: 1px solid #d1d1ca; background: white; }
    table { width: 100%; min-width: 1100px; border-collapse: collapse; font-size: 13px; }
    th, td { padding: 9px 10px; border-bottom: 1px solid #e6e6df; text-align: left; white-space: nowrap; }
    th { position: sticky; top: 0; background: #222; color: white; font-weight: 700; }
    tr:nth-child(even) td { background: #fafafa; }
    .empty, .error { padding: 16px; border: 1px solid #d1d1ca; background: white; }
    .error { color: #b42318; }
    code { background: #ecece7; padding: 2px 5px; border-radius: 4px; }
  </style>
</head>
<body>
  <header>
    <h1>__TITLE__</h1>
    <p class="subtitle">__SUBTITLE__</p>
  </header>
  <main>
    <nav><a href="/monitor">Back to Monitor</a></nav>
    <div class="toolbar">
      <span class="status" id="status">Loading...</span>
      <span>Auto refresh: 2s</span>
      <span>Endpoint: <code>__ENDPOINT__</code></span>
    </div>
    <div id="__TABLE_ID__"></div>
  </main>

  <script>
    const formatValue = (value) => {
      if (value === null || value === undefined) return "";
      if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
      if (typeof value === "boolean") return value ? "true" : "false";
      return String(value);
    };

    const renderTable = (targetId, columns, rows) => {
      const target = document.getElementById(targetId);
      if (!rows || rows.length === 0) {
        target.innerHTML = '<div class="empty">No data</div>';
        return;
      }

      const thead = '<thead><tr>' + columns.map((col) => `<th>${col}</th>`).join("") + '</tr></thead>';
      const tbody = '<tbody>' + rows.map((row) => {
        return '<tr>' + row.map((value) => `<td>${formatValue(value)}</td>`).join("") + '</tr>';
      }).join("") + '</tbody>';
      target.innerHTML = `<div class="table-wrap"><table>${thead}${tbody}</table></div>`;
    };

    const load = async () => {
      const status = document.getElementById("status");
      try {
        const response = await fetch("__ENDPOINT__?limit=50");
        if (!response.ok) throw new Error("API request failed");
        const data = await response.json();
        renderTable("__TABLE_ID__", data.columns, data.rows);
        status.textContent = `Updated ${new Date().toLocaleTimeString()}`;
      } catch (error) {
        status.textContent = "Load failed";
        document.getElementById("__TABLE_ID__").innerHTML = `<div class="error">${error}</div>`;
      }
    };

    load();
    setInterval(load, 2000);
  </script>
</body>
</html>
"""
    return (
        html
        .replace("__TITLE__", title)
        .replace("__SUBTITLE__", subtitle)
        .replace("__ENDPOINT__", endpoint)
        .replace("__TABLE_ID__", table_id)
    )

@app.get("/monitor/readings", response_class=HTMLResponse)
def monitor_readings_page():
    return render_monitor_table_page(
        title="All Sensor Readings",
        subtitle="raw_sensor_readings에 저장된 모든 원본 센서 수신값",
        endpoint="/api/v1/sensor-readings/recent",
        table_id="readings"
    )

@app.get("/monitor/noise-events", response_class=HTMLResponse)
def monitor_noise_events_page():
    return render_monitor_table_page(
        title="Noise Events",
        subtitle="AI가 is_meaningful=true로 판단해 noise_events에 저장한 이벤트",
        endpoint="/api/v1/noise-events/recent",
        table_id="events"
    )


@app.get("/api/v1/dashboard/stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    today = date.today()

    # 모니터링 세대 수
    total_households = db.query(models.Household).count()

    # 긴급 대응 필요 세대 수
    households = db.query(models.Household).all()
    urgent_count = 0
    for household in households:
        logs_today = db.query(models.NoiseLog).filter(
            models.NoiseLog.household_id == household.id,
            func.date(models.NoiseLog.timestamp) == today
        ).all()
        total_today = len(logs_today)
        high_today = sum(1 for l in logs_today if is_high_or_critical(l.severity))
        if total_today >= 7 or high_today >= 3:
            urgent_count += 1

    # 오늘 발생 소음 총합
    today_noise_count = db.query(models.NoiseLog).filter(
        func.date(models.NoiseLog.timestamp) == today
    ).count()

    # 조치 완료 세대 수
    completed_count = db.query(models.Mediation).filter(
        models.Mediation.status == "completed"
    ).count()

    return {
        "total_households": total_households,
        "urgent_households": urgent_count,
        "today_noise_count": today_noise_count,
        "completed_count": completed_count
    }

@app.get("/api/v1/dashboard/pending-mediations")
def get_pending_mediation_summary(db: Session = Depends(get_db)):
    """홈 화면의 미결재/미처리 중재 요청 요약"""
    pending_statuses = ["pending", "new", "in_progress", "processing"]
    pending_mediations = db.query(models.Mediation).filter(
        models.Mediation.status.in_(pending_statuses)
    ).order_by(models.Mediation.created_at.desc()).all()

    latest = pending_mediations[0] if pending_mediations else None

    return {
        "pending_count": len(pending_mediations),
        "status_filter": pending_statuses,
        "latest_request": {
            "id": latest.id,
            "household_id": latest.household_id,
            "target_unit": latest.target_unit,
            "resident_message": latest.resident_message,
            "event_summary": latest.event_summary,
            "status": latest.status,
            "created_at": latest.created_at
        } if latest else None
    }

@app.get("/api/v1/dashboard/notices/summary")
def get_notice_dashboard_summary(db: Session = Depends(get_db)):
    """홈 화면 공지사항 탭 요약"""
    recent_since = datetime.utcnow() - timedelta(days=7)
    total_households = db.query(models.Household).count()

    all_notices = db.query(models.Notice).filter(
        models.Notice.status.in_(["sent", "scheduled"])
    ).order_by(models.Notice.created_at.desc()).all()

    recent_notices = db.query(models.Notice).filter(
        models.Notice.status.in_(["sent", "scheduled"]),
        models.Notice.created_at >= recent_since
    ).order_by(models.Notice.created_at.desc()).all()

    sent_notices = [notice for notice in all_notices if notice.status == "sent"]
    confirmation_rates = [
        get_notice_confirmation_stats(notice, db)["confirmation_rate"]
        for notice in sent_notices
    ]
    avg_confirmation_rate = round(sum(confirmation_rates) / len(confirmation_rates)) if confirmation_rates else 0
    recent_notice_summaries = [
        serialize_notice_summary(notice, db)
        for notice in recent_notices[:5]
    ]
    latest_notice = recent_notice_summaries[0] if recent_notice_summaries else None
    unconfirmed_households = latest_notice["unconfirmed_count"] if latest_notice else 0

    return {
        "total_sent_count": len(sent_notices),
        "recent_sent_count": len(recent_notices),
        "recent_period_days": 7,
        "avg_confirmation_rate": avg_confirmation_rate,
        "unconfirmed_households": unconfirmed_households,
        "total_recipients": total_households,
        "latest_notice": latest_notice,
        "notice_types": NOTICE_TYPE_META,
        "statuses": NOTICE_STATUS_META,
    }

@app.get("/api/v1/dashboard/backup-status")
def get_backup_status_summary(db: Session = Depends(get_db)):
    """홈 화면 데이터 백업 상태 요약"""

    def format_elapsed(dt: Optional[datetime]) -> Optional[str]:
        if not dt:
            return None
        delta = datetime.utcnow() - dt
        minutes = max(int(delta.total_seconds() // 60), 0)
        if minutes < 1:
            return "방금 전"
        if minutes < 60:
            return f"{minutes}분 전"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}시간 전"
        return f"{hours // 24}일 전"

    def item(label: str, last_synced_at: Optional[datetime], error_if_empty: bool = False) -> dict:
        status = "normal" if last_synced_at else ("error" if error_if_empty else "empty")
        status_label = "정상" if status == "normal" else "오류" if status == "error" else "데이터 없음"
        return {
            "label": label,
            "status": status,
            "status_label": status_label,
            "last_synced_at": last_synced_at,
            "last_synced_text": format_elapsed(last_synced_at)
        }

    latest_noise_log = db.query(func.max(models.NoiseLog.timestamp)).scalar()
    latest_mediation = db.query(func.max(models.Mediation.created_at)).scalar()
    latest_sensor = db.query(func.max(models.Sensor.last_checked)).scalar()

    items = [
        item("소음 로그 데이터", latest_noise_log),
        item("중재 기록", latest_mediation),
        item("센서 상태 로그", latest_sensor, error_if_empty=True)
    ]

    has_error = any(entry["status"] == "error" for entry in items)
    return {
        "overall_status": "error" if has_error else "normal",
        "overall_status_label": "오류" if has_error else "정상",
        "items": items
    }

@app.post("/api/v1/sensor-readings")
async def create_sensor_reading(data: NoiseData, db: Session = Depends(get_db)):
    sensor = db.query(models.Sensor).filter(models.Sensor.sensor_id == data.sensor_id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail=f"sensor_id '{data.sensor_id}' 를 찾을 수 없습니다.")

    # UTC 기준 타임스탬프
    utc_now = datetime.utcnow()
    sensor_timestamp = data.timestamp or utc_now

    # 1. raw_sensor_readings 저장 (중복 방지)
    existing = db.query(models.RawSensorReading).filter(
        models.RawSensorReading.sensor_id == data.sensor_id,
        models.RawSensorReading.sensor_timestamp == sensor_timestamp
    ).first()

    if existing:
        return {"status": "duplicate", "message": "중복 데이터입니다."}

    acceleration = data.acceleration or {}
    raw = models.RawSensorReading(
        sensor_id=data.sensor_id,
        household_id=sensor.household_id,
        sound_level=data.sound_level,
        vibration_value=data.vibration_value,
        duration_ms=data.duration_ms,
        acceleration_x=acceleration.get("x"),
        acceleration_y=acceleration.get("y"),
        acceleration_z=acceleration.get("z"),
        received_at=utc_now,
        sensor_timestamp=sensor_timestamp
    )
    db.add(raw)
    db.flush()

    # 2. KST 기준 야간 판정
    is_night = is_night_kst(sensor_timestamp)

    # 3. AI 이벤트 분류 API 호출
    classification = classify_event_with_ai(
        data=data,
        sensor_timestamp=sensor_timestamp,
        is_night=is_night,
        household_id=sensor.household_id,
        db=db
    )

    # 4. AI가 의미 있는 이벤트로 판단한 경우만 noise_events 저장
    is_meaningful = classification["is_meaningful"]

    # 5. noise_events 저장 (의미 이벤트만)
    noise_event = None
    if is_meaningful:
        noise_event = models.NoiseEvent(
            sensor_id=data.sensor_id,
            household_id=sensor.household_id,
            event_type=classification["event_type"],
            severity=classification["severity"],
            severity_score=classification["severity_score"],
            confidence=classification["confidence"],
            is_night=is_night,
            is_meaningful=True,
            avg_sound_level=data.sound_level,
            max_sound_level=data.sound_level,
            avg_vibration=data.vibration_value,
            duration_ms=data.duration_ms,
            started_at=sensor_timestamp,
            status="new"
        )
        db.add(noise_event)
        db.flush()

    # 6. noise_logs 저장 (하위 호환)
    new_log = models.NoiseLog(
        sensor_id=data.sensor_id,
        household_id=sensor.household_id,
        sound_level=data.sound_level,
        vibration_value=data.vibration_value,
        duration_ms=data.duration_ms,
        event_type=classification["event_type"],
        severity=classification["severity"],
        severity_score=classification["severity_score"],
        is_night=is_night,
        confidence=classification["confidence"],
        status="new",
        timestamp=sensor_timestamp
    )
    db.add(new_log)
    db.flush()

    # 7. 의미 이벤트가 저장된 경우에만 AI 패턴 분석 API 호출
    if is_meaningful:
        pattern_result = analyze_patterns_with_ai(sensor.household_id, db)
        noise_event.pattern_label = pattern_result.get("pattern_label")
    else:
        pattern_result = {
            "recent_count_10min": 0,
            "pattern_label": "background",
            "needs_mediation": False,
            "needs_escalation": False,
            "summary": "의미 이벤트가 아니므로 패턴 분석을 생략했습니다.",
            "source": classification.get("source")
        }

    message_created = False
    ai_result = None

    # 8. generate_mediation_message
    if is_meaningful and (classification["severity"] in MEDIATION_SEVERITIES or pattern_result["needs_mediation"]):
        unit = sensor.location_unit
        msg = generate_ai_message(
            unit=unit,
            sound_level=data.sound_level,
            event_type=classification["event_type"],
            is_night=is_night
        )
        new_med = models.Mediation(
            noise_log_id=new_log.id,
            noise_event_id=noise_event.id if noise_event else None,
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
        "raw_saved": True,
        "is_meaningful": is_meaningful,
        "noise_event_id": noise_event.id if noise_event else None,
        "noise_log": {
            "id": new_log.id,
            "event_type": classification["event_type"],
            "severity": classification["severity"],
            "is_night": is_night
        },
        "pattern_result": pattern_result,
        "message_created": message_created,
        "ai_result": ai_result
    }

def _effective_since_or_week_ago(since: Optional[datetime]) -> datetime:
    if since:
        return since.replace(tzinfo=None) if since.tzinfo else since
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)


def _noise_log_to_dict(log: models.NoiseLog, household: Optional[models.Household] = None) -> dict:
    return {
        "id": log.id,
        "sensor_id": log.sensor_id,
        "household_id": log.household_id,
        "apartment_name": household.apartment_name if household else None,
        "building_name": household.building_name if household else None,
        "unit_number": household.unit_number if household else None,
        "floor": household.floor if household else None,
        "alias": household.alias if household else None,
        "sound_level": log.sound_level,
        "vibration_value": log.vibration_value,
        "duration_ms": log.duration_ms,
        "event_type": format_display_event_type(log.event_type),
        "severity": log.severity,
        "severity_score": log.severity_score,
        "confidence": log.confidence,
        "is_night": log.is_night,
        "pattern_label": log.pattern_label,
        "status": log.status,
        "timestamp": log.timestamp.isoformat() if log.timestamp else None,
    }


def format_display_vibration(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return value - 1000 if value > 1000 else value


def format_display_event_type(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return "" if value.lower() == "unknown" else value


@app.get(
    "/api/v1/noise-logs/recent",
    responses={
        200: {
            "description": "최근 소음 로그 조회",
            "content": {
                "application/json": {
                    "example": {
                        "since": "2026-05-25T12:00:00",
                        "limit": 20,
                        "total": 2,
                        "logs": [
                            {
                                "id": 1506,
                                "sensor_id": "SENSOR-A101-01",
                                "household_id": 1,
                                "apartment_name": "쿵로그아파트",
                                "building_name": "A동",
                                "unit_number": "101호",
                                "floor": 1,
                                "alias": "A-101",
                                "sound_level": 90.0,
                                "vibration_value": 1000.0,
                                "duration_ms": 3000,
                                "event_type": "impact_noise",
                                "severity": "high",
                                "severity_score": 8.0,
                                "confidence": 0.87,
                                "is_night": False,
                                "pattern_label": "no_pattern",
                                "status": "new",
                                "timestamp": "2026-05-11T12:36:35",
                            },
                            {
                                "id": 1505,
                                "sensor_id": "SENSOR-A101-01",
                                "household_id": 1,
                                "apartment_name": "쿵로그아파트",
                                "building_name": "A동",
                                "unit_number": "101호",
                                "floor": 1,
                                "alias": "A-101",
                                "sound_level": 55.0,
                                "vibration_value": 700.0,
                                "duration_ms": 3000,
                                "event_type": "daily_noise",
                                "severity": "medium",
                                "severity_score": 4.0,
                                "confidence": 0.74,
                                "is_night": False,
                                "pattern_label": "no_pattern",
                                "status": "new",
                                "timestamp": "2026-05-11T12:28:44",
                            },
                        ],
                    }
                }
            },
        }
    },
)
def get_recent_noise_logs(
    household_id: Optional[int] = Query(None, description="세대 ID. 없으면 전체 세대 조회"),
    since: Optional[datetime] = Query(None, description="조회 시작 시각. 없으면 최근 7일 기준"),
    limit: int = Query(20, ge=1, le=100, description="조회 개수"),
    db: Session = Depends(get_db),
):
    effective_since = _effective_since_or_week_ago(since)
    query = db.query(models.NoiseLog).order_by(models.NoiseLog.timestamp.desc())
    query = query.filter(models.NoiseLog.timestamp >= effective_since)
    query = query.filter(func.lower(models.NoiseLog.event_type) != "unknown")
    if household_id:
        query = query.filter(models.NoiseLog.household_id == household_id)
    logs = query.limit(limit).all()
    household_ids = {log.household_id for log in logs if log.household_id}
    households = {}
    if household_ids:
        households = {
            household.id: household
            for household in db.query(models.Household).filter(models.Household.id.in_(household_ids)).all()
        }
    return {
        "since": effective_since.isoformat(),
        "limit": limit,
        "total": len(logs),
        "logs": [_noise_log_to_dict(log, households.get(log.household_id)) for log in logs],
    }


@app.get("/api/v1/noise-logs/recent/export")
def export_recent_noise_logs(
    household_id: Optional[int] = Query(None, description="세대 ID. 없으면 전체 세대 내보내기"),
    since: Optional[datetime] = Query(None, description="내보내기 시작 시각. 없으면 최근 7일 기준"),
    limit: int = Query(1000, ge=1, le=10000, description="내보내기 최대 개수"),
    db: Session = Depends(get_db),
):
    effective_since = _effective_since_or_week_ago(since)
    query = db.query(models.NoiseLog).order_by(models.NoiseLog.timestamp.desc())
    query = query.filter(models.NoiseLog.timestamp >= effective_since)
    query = query.filter(func.lower(models.NoiseLog.event_type) != "unknown")
    if household_id:
        query = query.filter(models.NoiseLog.household_id == household_id)
    logs = query.limit(limit).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id",
        "sensor_id",
        "household_id",
        "sound_level",
        "vibration_value",
        "duration_ms",
        "event_type",
        "severity",
        "severity_score",
        "confidence",
        "is_night",
        "pattern_label",
        "status",
        "timestamp",
    ])
    for log in logs:
        row = _noise_log_to_dict(log)
        writer.writerow([
            row["id"],
            row["sensor_id"],
            row["household_id"],
            row["sound_level"],
            row["vibration_value"],
            row["duration_ms"],
            row["event_type"],
            row["severity"],
            row["severity_score"],
            row["confidence"],
            row["is_night"],
            row["pattern_label"],
            row["status"],
            row["timestamp"],
        ])

    filename = f"noise_logs_{datetime.now(KST).strftime('%Y%m%d_%H%M%S')}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )

@app.get("/api/v1/sensor-readings/recent")
def get_recent_sensor_readings(
    household_id: Optional[int] = None,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """최근 원본 센서 수신값을 테이블 형태로 조회"""
    safe_limit = min(max(limit, 1), 100)
    query = db.query(models.RawSensorReading).order_by(models.RawSensorReading.received_at.desc())
    if household_id:
        query = query.filter(models.RawSensorReading.household_id == household_id)
    readings = query.limit(safe_limit).all()

    columns = [
        "id",
        "sensor_id",
        "household_id",
        "sound_level",
        "vibration_value",
        "duration_ms",
        "time"
    ]
    rows = [
        [
            reading.id,
            reading.sensor_id,
            reading.household_id,
            reading.sound_level,
            format_display_vibration(reading.vibration_value),
            reading.duration_ms,
            format_kst(reading.received_at)
        ]
        for reading in readings
    ]

    return {
        "columns": columns,
        "rows": rows,
        "readings": [
            dict(zip(columns, row))
            for row in rows
        ],
        "total": len(rows)
    }

@app.get("/api/v1/noise-events/recent")
def get_recent_noise_events_api(
    household_id: Optional[int] = None,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """AI가 의미 있는 이벤트로 판단해 noise_events에 저장된 최근 이벤트를 테이블 형태로 조회"""
    safe_limit = min(max(limit, 1), 100)
    query = db.query(models.NoiseEvent).order_by(models.NoiseEvent.started_at.desc())
    query = query.filter(func.lower(models.NoiseEvent.event_type) != "unknown")
    if household_id:
        query = query.filter(models.NoiseEvent.household_id == household_id)
    events = query.limit(safe_limit).all()

    columns = [
        "id",
        "sensor_id",
        "household_id",
        "event_type",
        "severity",
        "severity_score",
        "confidence",
        "is_night",
        "is_meaningful",
        "avg_sound_level",
        "avg_vibration",
        "time"
    ]
    rows = [
        [
            event.id,
            event.sensor_id,
            event.household_id,
            format_display_event_type(event.event_type),
            event.severity,
            event.severity_score,
            event.confidence,
            event.is_night,
            event.is_meaningful,
            event.avg_sound_level,
            format_display_vibration(event.avg_vibration),
            format_kst(event.started_at)
        ]
        for event in events
    ]

    return {
        "columns": columns,
        "rows": rows,
        "events": [
            dict(zip(columns, row))
            for row in rows
        ],
        "total": len(rows)
    }

@app.get("/api/v1/noise-events/{event_id}")
def get_noise_event(event_id: int, db: Session = Depends(get_db)):
    event = db.query(models.NoiseEvent).filter(models.NoiseEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="소음 이벤트를 찾을 수 없습니다.")

    return {
        "id": event.id,
        "sensor_id": event.sensor_id,
        "household_id": event.household_id,
        "event_type": format_display_event_type(event.event_type),
        "severity": event.severity,
        "severity_score": event.severity_score,
        "confidence": event.confidence,
        "is_night": event.is_night,
        "is_meaningful": event.is_meaningful,
        "pattern_label": event.pattern_label,
        "avg_sound_level": event.avg_sound_level,
        "max_sound_level": event.max_sound_level,
        "avg_vibration": format_display_vibration(event.avg_vibration),
        "duration_ms": event.duration_ms,
        "sample_count": event.sample_count,
        "started_at": event.started_at,
        "ended_at": event.ended_at,
        "status": event.status
    }

@app.get("/api/v1/households/{household_id}/patterns")
def get_household_patterns(household_id: int, db: Session = Depends(get_db)):
    pattern_result = analyze_patterns_with_ai(household_id, db)
    return pattern_result


@app.get("/api/v1/mediations")
def get_mediations(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.Mediation).order_by(models.Mediation.created_at.desc())
    if status:
        query = query.filter(models.Mediation.status == status)
    mediations = query.all()

    result = []
    for med in mediations:
        household = db.query(models.Household).filter(models.Household.id == med.household_id).first()
        result.append({
            "id": med.id,
            "target_unit": med.target_unit,
            "ai_message": med.ai_message,
            "event_summary": med.event_summary,
            "resident_message": med.resident_message,
            "admin_summary": med.admin_summary,
            "recommended_action": med.recommended_action,
            "generation_method": med.generation_method,
            "status": med.status,
            "created_at": med.created_at,
            "quiet_start_time": household.quiet_start_time if household else None,
            "quiet_end_time": household.quiet_end_time if household else None
        })
    return result


@app.get("/api/v1/mediations/{med_id}")
def get_mediation(med_id: int, db: Session = Depends(get_db)):
    med = db.query(models.Mediation).filter(models.Mediation.id == med_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="해당 중재 정보를 찾을 수 없습니다.")

    household = db.query(models.Household).filter(models.Household.id == med.household_id).first()

    result = {
        "id": med.id,
        "target_unit": med.target_unit,
        "ai_message": med.ai_message,
        "event_summary": med.event_summary,
        "resident_message": med.resident_message,
        "admin_summary": med.admin_summary,
        "recommended_action": med.recommended_action,
        "generation_method": med.generation_method,
        "status": med.status,
        "created_at": med.created_at,
        "quiet_start_time": household.quiet_start_time if household else None,
        "quiet_end_time": household.quiet_end_time if household else None
    }
    return result

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

@app.get("/api/v1/residents/{household_id}/mediations")
def get_resident_mediations(household_id: int, status: Optional[str] = None, db: Session = Depends(get_db)):
    household = db.query(models.Household).filter(models.Household.id == household_id).first()
    if not household:
        raise HTTPException(status_code=404, detail="세대를 찾을 수 없습니다.")

    query = db.query(models.Mediation).filter(
        models.Mediation.household_id == household_id
    ).order_by(models.Mediation.created_at.desc())
    if status:
        query = query.filter(models.Mediation.status == status)

    mediations = query.all()
    return {
        "mediations": [
            {
                "id": mediation.id,
                "target_unit": mediation.target_unit,
                "resident_message": mediation.resident_message,
                "event_summary": mediation.event_summary,
                "recommended_action": mediation.recommended_action,
                "status": mediation.status,
                "created_at": mediation.created_at
            }
            for mediation in mediations
        ],
        "total": len(mediations)
    }

@app.get("/api/v1/residents/{household_id}/mediations/{mediation_id}")
def get_resident_mediation_detail(household_id: int, mediation_id: int, db: Session = Depends(get_db)):
    household = get_household_or_404(household_id, db)
    mediation = db.query(models.Mediation).filter(
        models.Mediation.id == mediation_id,
        models.Mediation.household_id == household_id
    ).first()
    if not mediation:
        raise HTTPException(status_code=404, detail="중재 메시지를 찾을 수 없습니다.")

    return {
        "id": mediation.id,
        "household_id": mediation.household_id,
        "target_unit": mediation.target_unit,
        "ai_message": mediation.ai_message,
        "event_summary": mediation.event_summary,
        "resident_message": mediation.resident_message,
        "recommended_action": mediation.recommended_action,
        "status": mediation.status,
        "created_at": mediation.created_at,
        "quiet_start_time": household.quiet_start_time,
        "quiet_end_time": household.quiet_end_time
    }

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
    notice_type: str
    target_type: str
    target_households: Optional[list] = None
    scheduled_at: Optional[datetime] = None  # 예약 발송 시간 추가

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

NOTICE_TYPE_META = {
    "urgent_alert": "긴급 알림",
    "general_notice": "일반 공지",
    "life_etiquette": "생활 에티켓",
    "equipment_check": "장비 점검 안내",
}

NOTICE_TYPE_ALIASES = {
    "urgent": "urgent_alert",
    "general": "general_notice",
    "manner": "life_etiquette",
    "equipment": "equipment_check",
}

NOTICE_STATUS_META = {
    "draft": "임시 저장",
    "sent": "발송 완료",
    "scheduled": "예약됨",
    "cancelled": "취소됨",
}


def normalize_notice_type(notice_type: Optional[str]) -> str:
    value = (notice_type or "general_notice").strip()
    return NOTICE_TYPE_ALIASES.get(value, value)


def parse_notice_targets(notice: models.Notice) -> list:
    if not notice.target_households:
        return []
    try:
        targets = json.loads(notice.target_households)
    except json.JSONDecodeError:
        return []
    if not isinstance(targets, list):
        return []
    return targets


def get_notice_target_count(notice: models.Notice, db: Session) -> int:
    if notice.target_type in ["all", "전체", "all_households"]:
        return db.query(models.Household).count()
    return len(parse_notice_targets(notice))


def get_notice_confirmation_stats(notice: models.Notice, db: Session) -> dict:
    target_count = get_notice_target_count(notice, db)
    if target_count <= 0:
        return {
            "target_count": 0,
            "confirmed_count": 0,
            "unconfirmed_count": 0,
            "confirmation_rate": 0,
        }

    if notice.status == "sent":
        # 아직 공지 확인 이력 테이블이 없으므로 화면 표시용 기본 확인율을 적용한다.
        confirmed_count = round(target_count * 0.92)
    else:
        confirmed_count = 0

    confirmed_count = min(confirmed_count, target_count)
    unconfirmed_count = target_count - confirmed_count
    confirmation_rate = round((confirmed_count / target_count) * 100)
    return {
        "target_count": target_count,
        "confirmed_count": confirmed_count,
        "unconfirmed_count": unconfirmed_count,
        "confirmation_rate": confirmation_rate,
    }


def serialize_notice_summary(notice: models.Notice, db: Session) -> dict:
    stats = get_notice_confirmation_stats(notice, db)
    return {
        "id": notice.id,
        "title": notice.title,
        "notice_type": normalize_notice_type(notice.notice_type),
        "notice_type_label": NOTICE_TYPE_META.get(normalize_notice_type(notice.notice_type), notice.notice_type),
        "target_type": notice.target_type,
        "status": notice.status,
        "status_label": NOTICE_STATUS_META.get(notice.status, notice.status),
        "target_count": stats["target_count"],
        "confirmed_count": stats["confirmed_count"],
        "unconfirmed_count": stats["unconfirmed_count"],
        "confirmation_rate": stats["confirmation_rate"],
        "created_at": notice.created_at,
        "sent_at": notice.sent_at,
    }


def serialize_notice_detail(notice: models.Notice, db: Session) -> dict:
    summary = serialize_notice_summary(notice, db)
    summary.update({
        "content": notice.content,
        "target_households": parse_notice_targets(notice),
        "scheduled_at": notice.sent_at if notice.status == "scheduled" else None,
    })
    return summary


@app.post("/api/v1/notices")
def create_notice(data: NoticeCreate, db: Session = Depends(get_db)):
    # 예약 발송이면 scheduled, 아니면 바로 sent
    if data.scheduled_at:
        status = "scheduled"
        sent_at = data.scheduled_at
    else:
        status = "sent"
        sent_at = datetime.now()

    new_notice = models.Notice(
        title=data.title,
        content=data.content,
        notice_type=normalize_notice_type(data.notice_type),
        target_type=data.target_type,
        target_households=json.dumps(data.target_households) if data.target_households else None,
        status=status,
        sent_at=sent_at
    )
    db.add(new_notice)
    db.commit()
    db.refresh(new_notice)
    return {
        "status": "success",
        "notice_id": new_notice.id,
        "scheduled_at": data.scheduled_at,
        "notice": serialize_notice_detail(new_notice, db),
    }

@app.get("/api/v1/notices")
def get_notices(notice_type: Optional[str] = None, status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(models.Notice).order_by(models.Notice.created_at.desc())
    if notice_type:
        query = query.filter(models.Notice.notice_type == normalize_notice_type(notice_type))
    if status:
        query = query.filter(models.Notice.status == status)
    notices = query.all()
    return {
        "notices": [serialize_notice_summary(notice, db) for notice in notices],
        "total": len(notices),
        "notice_types": NOTICE_TYPE_META,
        "statuses": NOTICE_STATUS_META,
    }


@app.get("/api/v1/notices/ai-template")
def get_ai_template(notice_type: Optional[str] = None, db: Session = Depends(get_db)):
    templates = {
        "urgent_alert": [
            {"title": "긴급 소음 발생 알림", "content": "긴급 알림입니다. 현재 귀하의 세대에서 기준치를 초과하는 소음이 측정되고 있습니다. 아래층 주민의 불편을 최소화하기 위해 즉시 확인 부탁드립니다.", "notice_type": "urgent_alert", "notice_type_label": NOTICE_TYPE_META["urgent_alert"]},
            {"title": "반복 소음 경고", "content": "최근 반복적인 생활 소음이 감지되었습니다. 층간소음 분쟁 예방을 위해 주의를 기울여 주시기 바랍니다.", "notice_type": "urgent_alert", "notice_type_label": NOTICE_TYPE_META["urgent_alert"]},
        ],
        "general_notice": [
            {"title": "월간 소음 현황 안내", "content": "이번 달 우리 단지의 층간소음 발생 현황을 안내드립니다. 쾌적한 주거 환경을 위해 입주민 여러분의 협조를 부탁드립니다.", "notice_type": "general_notice", "notice_type_label": NOTICE_TYPE_META["general_notice"]},
            {"title": "층간소음 예방 캠페인", "content": "층간소음 예방 캠페인을 진행합니다. 실내 슬리퍼 착용과 야간 시간대 소음 자제를 부탁드립니다.", "notice_type": "general_notice", "notice_type_label": NOTICE_TYPE_META["general_notice"]},
        ],
        "life_etiquette": [
            {"title": "야간 소음 자제 안내", "content": "밤 10시 이후 생활 소음으로 인한 불편이 증가하고 있습니다. 청소기, 세탁기 사용을 자제하고 실내화 착용을 권장드립니다.", "notice_type": "life_etiquette", "notice_type_label": NOTICE_TYPE_META["life_etiquette"]},
            {"title": "발소리 완화 가이드", "content": "층간소음 예방을 위해 실내 슬리퍼 착용과 바닥 매트 사용을 권장드립니다.", "notice_type": "life_etiquette", "notice_type_label": NOTICE_TYPE_META["life_etiquette"]},
        ],
        "equipment_check": [
            {"title": "IoT 센서 점검 안내", "content": "층간소음 측정 센서의 정기 점검이 예정되어 있습니다. 대상 세대는 점검에 협조 부탁드립니다.", "notice_type": "equipment_check", "notice_type_label": NOTICE_TYPE_META["equipment_check"]},
            {"title": "센서 배터리 교체 안내", "content": "층간소음 측정 센서의 배터리 교체가 필요합니다. 원활한 측정을 위해 점검 부탁드립니다.", "notice_type": "equipment_check", "notice_type_label": NOTICE_TYPE_META["equipment_check"]},
        ],
    }

    if not notice_type:
        return {
            "all_templates": {
                ntype: {
                    "notice_type": ntype,
                    "notice_type_label": NOTICE_TYPE_META.get(ntype, ntype),
                    "templates": tmpls
                }
                for ntype, tmpls in templates.items()
            }
        }

    normalized_type = normalize_notice_type(notice_type)
    return {
        "notice_type": normalized_type,
        "notice_type_label": NOTICE_TYPE_META.get(normalized_type, normalized_type),
        "templates": templates.get(normalized_type, templates["general_notice"]),
    }

@app.get("/api/v1/notices/{notice_id}")
def get_notice(notice_id: int, db: Session = Depends(get_db)):
    notice = db.query(models.Notice).filter(models.Notice.id == notice_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다.")
    return serialize_notice_detail(notice, db)

@app.get("/api/v1/residents/{household_id}/notices")
def get_resident_notices(household_id: int, db: Session = Depends(get_db)):
    household = db.query(models.Household).filter(models.Household.id == household_id).first()
    if not household:
        raise HTTPException(status_code=404, detail="세대를 찾을 수 없습니다.")

    notices = db.query(models.Notice).order_by(models.Notice.created_at.desc()).all()
    visible_notices = []
    for notice in notices:
        if notice.target_type in ["all", "전체", "all_households"]:
            visible_notices.append(notice)
            continue
        if not notice.target_households:
            continue
        try:
            target_households = json.loads(notice.target_households)
        except json.JSONDecodeError:
            target_households = []
        if household_id in target_households or str(household_id) in target_households:
            visible_notices.append(notice)

    return {
        "notices": [
            {
                "id": notice.id,
                "title": notice.title,
                "content": notice.content,
                "notice_type": notice.notice_type,
                "status": notice.status,
                "created_at": notice.created_at,
                "sent_at": notice.sent_at
            }
            for notice in visible_notices
        ],
        "total": len(visible_notices)
    }

@app.get("/api/v1/residents/{household_id}/notifications")
def get_resident_notifications(household_id: int, db: Session = Depends(get_db)):
    get_household_or_404(household_id, db)

    recent_mediations = db.query(models.Mediation).filter(
        models.Mediation.household_id == household_id
    ).order_by(models.Mediation.created_at.desc()).limit(5).all()

    recent_notices = db.query(models.Notice).order_by(
        models.Notice.created_at.desc()
    ).limit(5).all()

    notifications = []
    for mediation in recent_mediations:
        notifications.append({
            "id": f"mediation-{mediation.id}",
            "type": "mediation",
            "title": "중재 메시지가 도착했습니다.",
            "message": mediation.event_summary or mediation.resident_message or mediation.ai_message,
            "created_at": mediation.created_at,
            "target_id": mediation.id
        })

    for notice in recent_notices:
        notifications.append({
            "id": f"notice-{notice.id}",
            "type": "notice",
            "title": notice.title,
            "message": notice.content,
            "created_at": notice.created_at,
            "target_id": notice.id
        })

    notifications.sort(key=lambda item: item["created_at"] or datetime.min, reverse=True)
    return {"notifications": notifications[:10], "total": len(notifications[:10])}

@app.delete("/api/v1/notices/{notice_id}")
def delete_notice(notice_id: int, db: Session = Depends(get_db)):
    notice = db.query(models.Notice).filter(models.Notice.id == notice_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다.")
    if notice.status != "scheduled":
        raise HTTPException(status_code=400, detail="예약된 공지사항만 취소할 수 있습니다.")
    db.delete(notice)
    db.commit()
    return {"status": "success", "notice_id": notice_id}

class NoticeUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    notice_type: Optional[str] = None
    scheduled_at: Optional[datetime] = None

@app.patch("/api/v1/notices/{notice_id}")
def update_notice(notice_id: int, data: NoticeUpdate, db: Session = Depends(get_db)):
    notice = db.query(models.Notice).filter(models.Notice.id == notice_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="공지사항을 찾을 수 없습니다.")
    if notice.status != "scheduled":
        raise HTTPException(status_code=400, detail="예약된 공지사항만 수정할 수 있습니다.")
    if data.title:
        notice.title = data.title
    if data.content:
        notice.content = data.content
    if data.notice_type:
        notice.notice_type = normalize_notice_type(data.notice_type)
    if data.scheduled_at:
        notice.sent_at = data.scheduled_at
    db.commit()
    db.refresh(notice)
    return serialize_notice_detail(notice, db)

@app.post("/api/v1/notices/ai-template")
def get_ai_template_legacy(notice_type: str = "general_notice", db: Session = Depends(get_db)):
    return get_ai_template(notice_type=notice_type, db=db)

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
    high_count = sum(1 for l in logs if is_high_or_critical(l.severity))
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
    high_count = sum(1 for l in logs if is_high_or_critical(l.severity))

    household_stats = {}
    for log in logs:
        hid = log.household_id
        if hid not in household_stats:
            household_stats[hid] = {"count": 0, "night_count": 0, "high_count": 0}
        household_stats[hid]["count"] += 1
        if log.is_night:
            household_stats[hid]["night_count"] += 1
        if is_high_or_critical(log.severity):
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
    high_count = sum(1 for l in logs if is_high_or_critical(l.severity))
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
    high_count = sum(1 for l in logs if is_high_or_critical(l.severity))
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

# --- 관리자 프로필 ---

class AdminProfileResponse(BaseModel):
    id: int
    username: str
    name: str
    role: str
    team: str

    class Config:
        from_attributes = True

class AdminProfileUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    team: Optional[str] = None

@app.get("/api/v1/admin/profile/{admin_id}", response_model=AdminProfileResponse)
def get_admin_profile(admin_id: int, db: Session = Depends(get_db)):
    admin = db.query(models.Admin).filter(models.Admin.id == admin_id).first()
    if not admin:
        raise HTTPException(status_code=404, detail="관리자를 찾을 수 없습니다.")
    return admin

@app.patch("/api/v1/admin/profile/{admin_id}", response_model=AdminProfileResponse)
def update_admin_profile(admin_id: int, data: AdminProfileUpdate, db: Session = Depends(get_db)):
    admin = db.query(models.Admin).filter(models.Admin.id == admin_id).first()
    if not admin:
        raise HTTPException(status_code=404, detail="관리자를 찾을 수 없습니다.")
    if data.name:
        admin.name = data.name
    if data.role:
        admin.role = data.role
    if data.team:
        admin.team = data.team
    db.commit()
    db.refresh(admin)
    return admin

# --- 센서 상태 및 캘리브레이션 ---

@app.get("/api/v1/sensors/status")
def get_sensors_status(db: Session = Depends(get_db)):
    sensors = db.query(models.Sensor).all()
    total = len(sensors)
    online = sum(1 for s in sensors if s.is_online)
    avg_battery = round(sum(s.battery_level for s in sensors) / total, 1) if total > 0 else 0
    needs_calibration = sum(1 for s in sensors if s.calibration_offset != 0.0)

    return {
        "total_sensors": total,
        "online_sensors": online,
        "avg_battery": avg_battery,
        "needs_calibration": needs_calibration,
        "sensors": [
            {
                "sensor_id": s.sensor_id,
                "location_unit": s.location_unit,
                "is_online": s.is_online,
                "battery_level": s.battery_level,
                "calibration_offset": s.calibration_offset,
                "source": s.source,
                "last_checked": s.last_checked
            } for s in sensors
        ]
    }

class CalibrationUpdate(BaseModel):
    calibration_offset: float

@app.patch("/api/v1/sensors/{sensor_id}/calibrate")
def calibrate_sensor(sensor_id: str, data: CalibrationUpdate, db: Session = Depends(get_db)):
    sensor = db.query(models.Sensor).filter(models.Sensor.sensor_id == sensor_id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail="센서를 찾을 수 없습니다.")
    sensor.calibration_offset = data.calibration_offset
    db.commit()
    db.refresh(sensor)
    return {"status": "success", "sensor_id": sensor_id, "calibration_offset": sensor.calibration_offset}

# --- 관리자 업무 설정 ---

class AdminSettingsResponse(BaseModel):
    id: int
    admin_id: int
    noise_threshold: float
    duration_threshold: int
    off_hours_mute: bool
    work_start_time: Optional[str] = None
    work_end_time: Optional[str] = None

    class Config:
        from_attributes = True

class AdminSettingsUpdate(BaseModel):
    noise_threshold: Optional[float] = None
    duration_threshold: Optional[int] = None
    off_hours_mute: Optional[bool] = None
    work_start_time: Optional[str] = None
    work_end_time: Optional[str] = None

@app.get("/api/v1/admin/settings/{admin_id}", response_model=AdminSettingsResponse)
def get_admin_settings(admin_id: int, db: Session = Depends(get_db)):
    settings = db.query(models.AdminSettings).filter(models.AdminSettings.admin_id == admin_id).first()
    if not settings:
        # 없으면 기본값으로 생성
        settings = models.AdminSettings(admin_id=admin_id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings

@app.patch("/api/v1/admin/settings/{admin_id}", response_model=AdminSettingsResponse)
def update_admin_settings(admin_id: int, data: AdminSettingsUpdate, db: Session = Depends(get_db)):
    settings = db.query(models.AdminSettings).filter(models.AdminSettings.admin_id == admin_id).first()
    if not settings:
        settings = models.AdminSettings(admin_id=admin_id)
        db.add(settings)
        db.flush()
    if data.noise_threshold is not None:
        settings.noise_threshold = data.noise_threshold
    if data.duration_threshold is not None:
        settings.duration_threshold = data.duration_threshold
    if data.off_hours_mute is not None:
        settings.off_hours_mute = data.off_hours_mute
    if data.work_start_time is not None:
        settings.work_start_time = data.work_start_time
    if data.work_end_time is not None:
        settings.work_end_time = data.work_end_time
    db.commit()
    db.refresh(settings)
    return settings


# --- 소음 분포도 ---

@app.get("/api/v1/noise/distribution")
def get_noise_distribution(building: Optional[str] = None, db: Session = Depends(get_db)):
    households = db.query(models.Household).all()

    result = []
    for household in households:
        if building and household.building_name != building:
            continue

        logs = db.query(models.NoiseLog).filter(
            models.NoiseLog.household_id == household.id
        ).all()

        total_count = len(logs)
        high_count = sum(1 for l in logs if is_high_or_critical(l.severity))

        # 위험도 판단
        if total_count >= 7 or high_count >= 3:
            risk_level = "urgent"
            risk_label = "긴급 대응 필요"
        elif total_count >= 3:
            risk_level = "caution"
            risk_label = "관찰 필요"
        else:
            risk_level = "normal"
            risk_label = "정상"

        result.append({
            "household_id": household.id,
            "building_name": household.building_name,
            "unit_number": household.unit_number,
            "floor": household.floor,
            "alias": household.alias,
            "total_count": total_count,
            "high_count": high_count,
            "risk_level": risk_level,
            "risk_label": risk_label
        })

    # 건물별로 그룹핑
    buildings = {}
    for item in result:
        bname = item["building_name"]
        if bname not in buildings:
            buildings[bname] = []
        buildings[bname].append(item)

    return {
        "buildings": buildings,
        "legend": {
            "urgent": "긴급 대응 필요 (7건 이상 또는 고강도 3건 이상)",
            "caution": "관찰 필요 (3~6건)",
            "normal": "정상 (2건 이하)"
        }
    }


@app.get("/api/v1/noise/distribution/export")
def export_noise_distribution(db: Session = Depends(get_db)):
    households = db.query(models.Household).all()

    rows = []
    for household in households:
        logs = db.query(models.NoiseLog).filter(
            models.NoiseLog.household_id == household.id
        ).all()

        total_count = len(logs)
        high_count = sum(1 for l in logs if is_high_or_critical(l.severity))
        night_count = sum(1 for l in logs if l.is_night)

        if total_count >= 7 or high_count >= 3:
            risk_level = "긴급 대응 필요"
        elif total_count >= 3:
            risk_level = "관찰 필요"
        else:
            risk_level = "정상"

        rows.append({
            "세대": household.alias,
            "건물": household.building_name,
            "호수": household.unit_number,
            "총 이벤트": total_count,
            "고강도 이벤트": high_count,
            "야간 이벤트": night_count,
            "위험도": risk_level
        })

    return {"data": rows, "total": len(rows)}

# --- 대시보드 ---

@app.get("/api/v1/dashboard/households")
def get_dashboard_households(
    building: Optional[str] = Query(None, description="동 이름 필터. 예: A동"),
    search: Optional[str] = Query(None, description="동/호수/별칭/입주민명 검색어"),
    status_filter: Optional[str] = Query(None, alias="status", description="상태 필터: urgent, caution, normal"),
    db: Session = Depends(get_db)
):
    """전체 모니터링 세대 목록"""
    if status_filter and status_filter not in {"urgent", "caution", "normal"}:
        raise HTTPException(status_code=400, detail="status는 urgent, caution, normal 중 하나여야 합니다.")

    query = db.query(models.Household)
    if building:
        query = query.filter(models.Household.building_name == building)
    households = query.order_by(models.Household.building_name, models.Household.unit_number).all()
    today = date.today()

    result = []
    for household in households:
        display_unit = f"{household.building_name} {household.unit_number}".strip()
        if search:
            keyword = search.lower()
            searchable = " ".join([
                str(household.building_name or ""),
                str(household.unit_number or ""),
                str(household.alias or ""),
                str(household.resident_name or ""),
                display_unit,
            ]).lower()
            if keyword not in searchable:
                continue

        logs_today = db.query(models.NoiseLog).filter(
            models.NoiseLog.household_id == household.id,
            func.date(models.NoiseLog.timestamp) == today
        ).all()

        total_today = len(logs_today)
        high_today = sum(1 for l in logs_today if is_high_or_critical(l.severity))
        latest_log = db.query(models.NoiseLog).filter(
            models.NoiseLog.household_id == household.id
        ).order_by(models.NoiseLog.timestamp.desc()).first()

        if total_today >= 7 or high_today >= 3:
            status = "urgent"
            status_label = "즉시 대응 필요"
            status_color = "red"
        elif total_today >= 3:
            status = "caution"
            status_label = "관찰 필요"
            status_color = "orange"
        else:
            status = "normal"
            status_label = "정상"
            status_color = "green"

        if status_filter and status_filter != status:
            continue

        result.append({
            "household_id": household.id,
            "apartment_name": household.apartment_name,
            "alias": household.alias,
            "display_unit": display_unit,
            "building_name": household.building_name,
            "unit_number": household.unit_number,
            "floor": household.floor,
            "resident_name": household.resident_name,
            "phone_number": household.phone_number,
            "status": status,
            "status_label": status_label,
            "status_color": status_color,
            "today_count": total_today,
            "high_count": high_today,
            "latest_time": latest_log.timestamp if latest_log else None,
            "latest_time_text": format_kst(latest_log.timestamp) if latest_log else None,
            "latest_event_type": format_display_event_type(latest_log.event_type) if latest_log else None,
            "latest_severity": latest_log.severity if latest_log else None
        })

    return {
        "households": result,
        "total": len(result),
        "filters": {
            "building": building,
            "search": search,
            "status": status_filter
        },
        "status_labels": {
            "urgent": "즉시 대응 필요",
            "caution": "관찰 필요",
            "normal": "정상"
        }
    }

@app.get("/api/v1/dashboard/urgent")
def get_urgent_households(db: Session = Depends(get_db)):
    """긴급 대응 필요 세대"""
    households = db.query(models.Household).all()
    today = date.today()

    result = []
    for household in households:
        logs_today = db.query(models.NoiseLog).filter(
            models.NoiseLog.household_id == household.id,
            func.date(models.NoiseLog.timestamp) == today
        ).all()

        total_today = len(logs_today)
        high_today = sum(1 for l in logs_today if is_high_or_critical(l.severity))

        if total_today >= 7 or high_today >= 3:
            latest_log = db.query(models.NoiseLog).filter(
                models.NoiseLog.household_id == household.id
            ).order_by(models.NoiseLog.timestamp.desc()).first()

            avg_duration = 0
            if logs_today:
                durations = [l.duration_ms for l in logs_today if l.duration_ms]
                avg_duration = round(sum(durations) / len(durations) / 60000, 1) if durations else 0

            result.append({
                "household_id": household.id,
                "alias": household.alias,
                "building_name": household.building_name,
                "unit_number": household.unit_number,
                "resident_name": household.resident_name,  # 추가
                "phone_number": household.phone_number,  # 추가
                "today_count": total_today,
                "high_count": high_today,
                "avg_duration_min": avg_duration,
                "latest_time": latest_log.timestamp if latest_log else None
            })

    return {"urgent_households": result, "total": len(result)}

@app.get("/api/v1/dashboard/today-events")
def get_today_events(db: Session = Depends(get_db)):
    """오늘 발생 소음 종합"""
    today = date.today()
    logs = db.query(models.NoiseLog).filter(
        func.date(models.NoiseLog.timestamp) == today
    ).order_by(models.NoiseLog.timestamp.desc()).all()

    result = []
    for log in logs:
        household = db.query(models.Household).filter(
            models.Household.id == log.household_id
        ).first()

        result.append({
            "id": log.id,
            "alias": household.alias if household else None,
            "building_name": household.building_name if household else None,
            "unit_number": household.unit_number if household else None,
            "event_type": log.event_type,
            "severity": log.severity,
            "sound_level": log.sound_level,
            "duration_ms": log.duration_ms,
            "is_night": log.is_night,
            "timestamp": log.timestamp
        })

    return {"events": result, "total": len(result)}

@app.get("/api/v1/dashboard/completed")
def get_completed_actions(db: Session = Depends(get_db)):
    """조치 완료 내역"""
    mediations = db.query(models.Mediation).filter(
        models.Mediation.status == "completed"
    ).order_by(models.Mediation.created_at.desc()).all()

    admin = db.query(models.Admin).first()

    return {"completed": [
        {
            "id": m.id,
            "target_unit": m.target_unit,
            "admin_summary": m.admin_summary,
            "recommended_action": m.recommended_action,
            "created_at": m.created_at,
            "admin_name": admin.name if admin else None
        } for m in mediations
    ], "total": len(mediations)}

@app.get("/api/v1/dashboard/hourly")
def get_hourly_stats(hours: int = 24, db: Session = Depends(get_db)):
    now = datetime.now()
    since = now - timedelta(hours=hours)
    logs = db.query(models.NoiseLog).filter(
        models.NoiseLog.timestamp >= since
    ).all()

    if hours == 1:
        intervals = {}
        for i in range(12):
            key = (now - timedelta(minutes=55 - i*5)).strftime("%H:%M")
            intervals[key] = {"total": 0, "high": 0, "night": 0}
        for log in logs:
            minute = (log.timestamp.minute // 5) * 5
            key = log.timestamp.strftime(f"%H:{minute:02d}")
            if key in intervals:
                intervals[key]["total"] += 1
                if is_high_or_critical(log.severity):
                    intervals[key]["high"] += 1
                if log.is_night:
                    intervals[key]["night"] += 1
        return {"hourly": intervals, "period": "최근 1시간"}
    else:
        hourly = {}
        for i in range(hours):
            hour = (now - timedelta(hours=hours-1-i)).hour
            hourly[f"{hour:02d}"] = {"total": 0, "high": 0, "night": 0}
        for log in logs:
            hour_key = f"{log.timestamp.hour:02d}"
            if hour_key in hourly:
                hourly[hour_key]["total"] += 1
                if is_high_or_critical(log.severity):
                    hourly[hour_key]["high"] += 1
                if log.is_night:
                    hourly[hour_key]["night"] += 1
        return {"hourly": hourly, "period": f"최근 {hours}시간"}


# --- 협의 일정 ---

class MediationScheduleCreate(BaseModel):
    available_dates: list
    confirmed_date: Optional[datetime] = None

class MediationScheduleResponse(BaseModel):
    id: int
    mediation_id: int
    available_dates: Optional[str] = None
    confirmed_date: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True

@app.post("/api/v1/mediations/{med_id}/schedule")
def create_schedule(med_id: int, data: MediationScheduleCreate, db: Session = Depends(get_db)):
    med = db.query(models.Mediation).filter(models.Mediation.id == med_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="중재 정보를 찾을 수 없습니다.")
    schedule = models.MediationSchedule(
        mediation_id=med_id,
        available_dates=json.dumps(data.available_dates, ensure_ascii=False),
        confirmed_date=data.confirmed_date
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return {"status": "success", "schedule_id": schedule.id}

@app.get("/api/v1/mediations/{med_id}/schedule", response_model=MediationScheduleResponse)
def get_schedule(med_id: int, db: Session = Depends(get_db)):
    schedule = db.query(models.MediationSchedule).filter(
        models.MediationSchedule.mediation_id == med_id
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="협의 일정을 찾을 수 없습니다.")
    return schedule

@app.patch("/api/v1/mediations/{med_id}/schedule")
def update_schedule(med_id: int, data: MediationScheduleCreate, db: Session = Depends(get_db)):
    schedule = db.query(models.MediationSchedule).filter(
        models.MediationSchedule.mediation_id == med_id
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="협의 일정을 찾을 수 없습니다.")
    if data.available_dates:
        schedule.available_dates = json.dumps(data.available_dates, ensure_ascii=False)
    if data.confirmed_date:
        schedule.confirmed_date = data.confirmed_date
    db.commit()
    db.refresh(schedule)
    return {"status": "success"}

@app.get("/api/v1/mediations/{med_id}/schedule/overlap")
def get_schedule_overlap(med_id: int, db: Session = Depends(get_db)):
    med = db.query(models.Mediation).filter(models.Mediation.id == med_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="중재 정보를 찾을 수 없습니다.")

    schedules = db.query(models.MediationSchedule).filter(
        models.MediationSchedule.mediation_id == med_id
    ).all()

    overlap_counts = {str(i): 0 for i in range(1, 25)}

    for schedule in schedules:
        if schedule.available_dates:
            dates = json.loads(schedule.available_dates)
            for hour in dates:
                key = str(hour)
                if key in overlap_counts:
                    overlap_counts[key] += 1

    return {
        "mediation_id": med_id,
        "overlap_counts": overlap_counts,
        "total_responses": len(schedules)
    }


class MediationCreateRequest(BaseModel):
    household_id: int
    complaint_text: str
    noise_type: str  # impact_noise, daily_noise 등
    time_of_day: str  # day, night
    frequency: str  # once, sometimes, often


@app.post("/api/v1/mediations/request")
def create_mediation_request(data: MediationCreateRequest, db: Session = Depends(get_db)):
    household = db.query(models.Household).filter(models.Household.id == data.household_id).first()
    if not household:
        raise HTTPException(status_code=404, detail="세대를 찾을 수 없습니다.")

    is_night = data.time_of_day == "night"

    msg = generate_ai_message(
        unit=household.alias,
        sound_level=0.0,
        event_type=data.noise_type,
        is_night=is_night
    )

    new_med = models.Mediation(
        household_id=data.household_id,
        target_unit=household.alias,
        ai_message=msg["ai_message"],
        event_summary=msg["event_summary"],
        resident_message=data.complaint_text,
        admin_summary=msg["admin_summary"],
        recommended_action=msg["recommended_action"],
        generation_method=msg["generation_method"],
        tone_check_json=json.dumps(msg["tone_check"], ensure_ascii=False),
        status="pending"
    )
    db.add(new_med)
    db.commit()
    db.refresh(new_med)

    return {
        "status": "success",
        "mediation_id": new_med.id,
        "ai_message": msg["ai_message"]
    }

@app.get("/api/v1/households/{household_id}/summary")
def get_household_summary(household_id: int, db: Session = Depends(get_db)):
    today = date.today()
    seven_days_ago = datetime.utcnow() - timedelta(days=7)

    # 오늘 충격 소음 횟수
    today_impact = db.query(models.NoiseLog).filter(
        models.NoiseLog.household_id == household_id,
        func.date(models.NoiseLog.timestamp) == today,
        models.NoiseLog.event_type == "impact_noise"
    ).count()

    # 7일 평균 충격 소음 횟수
    week_logs = db.query(models.NoiseLog).filter(
        models.NoiseLog.household_id == household_id,
        models.NoiseLog.timestamp >= seven_days_ago,
        models.NoiseLog.event_type == "impact_noise"
    ).count()
    daily_avg = round(week_logs / 7, 1)
    change_percent = round((today_impact - daily_avg) / daily_avg * 100, 1) if daily_avg > 0 else 0

    # 최근 평균 강도
    recent_logs = db.query(models.NoiseLog).filter(
        models.NoiseLog.household_id == household_id
    ).order_by(models.NoiseLog.timestamp.desc()).limit(10).all()
    avg_sound = round(sum(l.sound_level for l in recent_logs) / len(recent_logs), 1) if recent_logs else 0
    is_caution = any(l.is_night for l in recent_logs)

    # 최근 소음 패턴
    night_count = db.query(models.NoiseLog).filter(
        models.NoiseLog.household_id == household_id,
        models.NoiseLog.timestamp >= seven_days_ago,
        models.NoiseLog.is_night == True
    ).count()
    pattern_label = "야간 반복 소음 주의" if night_count >= 3 else "정상"
    pattern_desc = f"최근 7일간 인근 세대에서 소음이 반복적으로 감지되었어요" if night_count >= 3 else "최근 소음 패턴이 정상입니다"

    # 최근 이벤트 로그
    recent_events = db.query(models.NoiseLog).filter(
        models.NoiseLog.household_id == household_id
    ).order_by(models.NoiseLog.timestamp.desc()).limit(4).all()

    return {
        "today_impact_count": today_impact,
        "change_percent": change_percent,
        "avg_sound_level": avg_sound,
        "is_caution": is_caution,
        "pattern_label": pattern_label,
        "pattern_desc": pattern_desc,
        "recent_events": [
            {
                "id": l.id,
                "event_type": l.event_type,
                "sound_level": l.sound_level,
                "duration_ms": l.duration_ms,
                "timestamp": l.timestamp
            } for l in recent_events
        ]
    }

@app.get("/api/v1/households/{household_id}/home")
def get_resident_home(household_id: int, db: Session = Depends(get_db)):
    household = get_household_or_404(household_id, db)
    summary = get_household_summary(household_id, db)

    latest_mediation = db.query(models.Mediation).filter(
        models.Mediation.household_id == household_id
    ).order_by(models.Mediation.created_at.desc()).first()

    notices_response = get_resident_notices(household_id, db)
    notices = notices_response["notices"][:3]

    return {
        "resident": serialize_resident(household),
        "summary": summary,
        "latest_mediation": {
            "id": latest_mediation.id,
            "status": latest_mediation.status,
            "resident_message": latest_mediation.resident_message,
            "event_summary": latest_mediation.event_summary,
            "created_at": latest_mediation.created_at
        } if latest_mediation else None,
        "notices": notices,
        "notice_count": notices_response["total"]
    }

@app.post("/api/v1/households/{household_id}/noise/measure")
def create_resident_noise_measurement(
    household_id: int,
    data: NoiseMeasurementCreate,
    db: Session = Depends(get_db)
):
    household = get_household_or_404(household_id, db)
    measured_at = data.timestamp or datetime.utcnow()
    severity = "high" if data.sound_level >= 57 else "medium" if data.sound_level >= 40 else "low"

    new_log = models.NoiseLog(
        household_id=household_id,
        sound_level=data.sound_level,
        vibration_value=data.vibration_value,
        duration_ms=data.duration_ms,
        event_type="resident_measurement",
        severity=severity,
        is_night=is_night_kst(measured_at),
        status="new",
        timestamp=measured_at
    )
    db.add(new_log)
    db.commit()
    db.refresh(new_log)

    return {
        "status": "success",
        "measurement": {
            "id": new_log.id,
            "household_id": household.id,
            "sound_level": new_log.sound_level,
            "vibration_value": new_log.vibration_value,
            "duration_ms": new_log.duration_ms,
            "severity": new_log.severity,
            "is_night": new_log.is_night,
            "timestamp": new_log.timestamp
        }
    }

@app.get("/api/v1/households/{household_id}/noise/latest")
def get_latest_resident_noise_measurement(household_id: int, db: Session = Depends(get_db)):
    get_household_or_404(household_id, db)
    latest_log = db.query(models.NoiseLog).filter(
        models.NoiseLog.household_id == household_id
    ).order_by(models.NoiseLog.timestamp.desc()).first()

    if not latest_log:
        return {"measurement": None}

    return {
        "measurement": {
            "id": latest_log.id,
            "household_id": latest_log.household_id,
            "sound_level": latest_log.sound_level,
            "vibration_value": latest_log.vibration_value,
            "duration_ms": latest_log.duration_ms,
            "event_type": latest_log.event_type,
            "severity": latest_log.severity,
            "is_night": latest_log.is_night,
            "timestamp": latest_log.timestamp
        }
    }
# --- 주민 프로필 ---

@app.get("/api/v1/households/{household_id}/profile")
def get_household_profile(household_id: int, db: Session = Depends(get_db)):
    household = db.query(models.Household).filter(models.Household.id == household_id).first()
    if not household:
        raise HTTPException(status_code=404, detail="세대를 찾을 수 없습니다.")
    return {
        "household_id": household.id,
        "resident_name": household.resident_name,
        "building_name": household.building_name,
        "unit_number": household.unit_number,
        "floor": household.floor,
        "alias": household.alias
    }

@app.delete("/api/v1/households/{household_id}/withdraw")
def withdraw_household(household_id: int, db: Session = Depends(get_db)):
    household = db.query(models.Household).filter(models.Household.id == household_id).first()
    if not household:
        raise HTTPException(status_code=404, detail="세대를 찾을 수 없습니다.")
    db.delete(household)
    db.commit()
    return {"status": "success", "message": "회원 탈퇴가 완료되었습니다."}

@app.post("/api/v1/auth/logout")
def logout():
    return {"status": "success", "message": "로그아웃 되었습니다."}

class PasswordUpdate(BaseModel):
    admin_id: int
    current_password: str
    new_password: str

@app.patch("/api/v1/auth/update-password")
def update_password(data: PasswordUpdate, db: Session = Depends(get_db)):
    admin = db.query(models.Admin).filter(models.Admin.id == data.admin_id).first()
    if not admin:
        raise HTTPException(status_code=404, detail="관리자를 찾을 수 없습니다.")
    if admin.password != data.current_password:
        raise HTTPException(status_code=400, detail="현재 비밀번호가 일치하지 않습니다.")
    admin.password = data.new_password
    db.commit()
    return {"status": "success", "message": "비밀번호가 변경되었습니다."}

class HouseholdUpdate(BaseModel):
    building_name: Optional[str] = None
    unit_number: Optional[str] = None
    floor: Optional[int] = None
    alias: Optional[str] = None

@app.patch("/api/v1/households/{household_id}")
def update_household(household_id: int, data: HouseholdUpdate, db: Session = Depends(get_db)):
    household = db.query(models.Household).filter(models.Household.id == household_id).first()
    if not household:
        raise HTTPException(status_code=404, detail="세대를 찾을 수 없습니다.")
    if data.building_name:
        household.building_name = data.building_name
    if data.unit_number:
        household.unit_number = data.unit_number
    if data.floor:
        household.floor = data.floor
    if data.alias:
        household.alias = data.alias
    db.commit()
    db.refresh(household)
    return {"status": "success", "household_id": household_id}

class QuietTimeUpdate(BaseModel):
    quiet_start_time: str
    quiet_end_time: str

@app.patch("/api/v1/households/{household_id}/quiet-time")
def update_quiet_time(household_id: int, data: QuietTimeUpdate, db: Session = Depends(get_db)):
    household = db.query(models.Household).filter(models.Household.id == household_id).first()
    if not household:
        raise HTTPException(status_code=404, detail="세대를 찾을 수 없습니다.")
    household.quiet_start_time = data.quiet_start_time
    household.quiet_end_time = data.quiet_end_time
    db.commit()
    db.refresh(household)
    return {"status": "success", "quiet_start_time": data.quiet_start_time, "quiet_end_time": data.quiet_end_time}

@app.get("/api/v1/households/{household_id}/home")
def get_household_home(household_id: int, db: Session = Depends(get_db)):
    # 중재 진행 상태
    mediation = db.query(models.Mediation).filter(
        models.Mediation.household_id == household_id,
        models.Mediation.status == "pending"
    ).order_by(models.Mediation.created_at.desc()).first()

    # 공지사항 최근 3개
    notices = db.query(models.Notice).filter(
        models.Notice.status == "sent"
    ).order_by(models.Notice.created_at.desc()).limit(3).all()

    return {
        "mediation": {
            "id": mediation.id,
            "status": mediation.status,
            "created_at": mediation.created_at
        } if mediation else None,
        "notices": [
            {
                "id": n.id,
                "title": n.title,
                "created_at": n.created_at
            } for n in notices
        ]
    }


@app.get("/api/v1/households/{household_id}/noise-stats")
def get_household_noise_stats(household_id: int, db: Session = Depends(get_db)):
    since = datetime.utcnow() - timedelta(hours=24)

    logs = db.query(models.NoiseLog).filter(
        models.NoiseLog.household_id == household_id,
        models.NoiseLog.timestamp >= since
    ).all()

    total_count = len(logs)
    high_count = sum(1 for l in logs if is_high_or_critical(l.severity))
    durations = [l.duration_ms for l in logs if l.duration_ms]
    avg_duration_min = round(sum(durations) / len(durations) / 60000, 1) if durations else 0

    return {
        "total_count": total_count,
        "high_count": high_count,
        "avg_duration_min": avg_duration_min,
        "period": "최근 24시간"
    }


@app.get("/api/v1/noise/hotspot")
def get_noise_hotspot(db: Session = Depends(get_db)):
    households = db.query(models.Household).all()

    buildings = {}
    for household in households:
        logs = db.query(models.NoiseLog).filter(
            models.NoiseLog.household_id == household.id
        ).all()

        total_count = len(logs)
        high_count = sum(1 for l in logs if l.severity == "high")

        if total_count >= 7 or high_count >= 3:
            risk_level = "urgent"
        elif total_count >= 3:
            risk_level = "caution"
        else:
            risk_level = "normal"

        bname = household.building_name.replace("동", "").strip() + "동"
        if bname not in buildings:
            buildings[bname] = {"urgent": 0, "caution": 0, "normal": 0, "total": 0}

        buildings[bname][risk_level] += 1
        buildings[bname]["total"] += 1

    return {
        "buildings": buildings,
        "legend": {
            "urgent": "긴급 대응 필요",
            "caution": "관찰 필요",
            "normal": "정상"
        }
    }

@app.get("/api/v1/dashboard/households/by-building")
def get_households_by_building(db: Session = Depends(get_db)):
    """공지 작성용 동별 세대 목록"""
    households = db.query(models.Household).order_by(
        models.Household.building_name, models.Household.unit_number
    ).all()

    buildings = {}
    for household in households:
        bname = household.building_name.replace("동", "").strip() + "동"
        if bname not in buildings:
            buildings[bname] = []
        buildings[bname].append({
            "household_id": household.id,
            "unit_number": household.unit_number,
            "floor": household.floor,
            "alias": household.alias,
            "resident_name": household.resident_name,
            "phone_number": household.phone_number,
        })

    return {
        "buildings": buildings,
        "building_names": list(buildings.keys()),
        "total": sum(len(v) for v in buildings.values())
    }

@app.post("/api/v1/mediations/{med_id}/approve")
def approve_mediation(med_id: int, db: Session = Depends(get_db)):
    med = db.query(models.Mediation).filter(models.Mediation.id == med_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="중재 정보를 찾을 수 없습니다.")
    med.status = "completed"
    db.commit()
    return {"status": "success", "message": "메시지가 승인 및 발송되었습니다."}
