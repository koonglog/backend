from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Enum, Text, UniqueConstraint
from sqlalchemy.sql import func
import enum
from database import Base

class AdminRole(str, enum.Enum):
    MANAGER = "관리소장"
    TECHNICAL = "시설과장"
    SECURITY = "보안팀장"
    STAFF = "관리원"

class TeamType(str, enum.Enum):
    ADMIN = "관리팀"
    SECURITY = "보안팀"

# 건물/세대 테이블 (신규)
class Household(Base):
    __tablename__ = "households"

    id = Column(Integer, primary_key=True, index=True)
    building_name = Column(String)
    unit_number = Column(String)
    floor = Column(Integer)
    alias = Column(String)
    resident_name = Column(String, nullable=True)   # 추가
    phone_number = Column(String, nullable=True)    # 추가

# 관리자 테이블
class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    name = Column(String)
    role = Column(Enum(AdminRole), default=AdminRole.STAFF)
    team = Column(Enum(TeamType), default=TeamType.ADMIN)
    permission_level = Column(String)

# IoT 센서 테이블
class Sensor(Base):
    __tablename__ = "sensors"

    sensor_id = Column(String, primary_key=True, index=True)
    household_id = Column(Integer, ForeignKey("households.id"), nullable=True)  # 세대 연결 (신규)
    location_unit = Column(String)
    source = Column(String, default="simulator")  # arduino | simulator (신규)
    is_online = Column(Boolean, default=True)
    battery_level = Column(Integer, default=100)
    calibration_offset = Column(Float, default=0.0)
    last_checked = Column(DateTime, default=func.now())

# 원본 센서 데이터 테이블 (신규)
class RawSensorReading(Base):
    __tablename__ = "raw_sensor_readings"

    id = Column(Integer, primary_key=True, index=True)
    sensor_id = Column(String, ForeignKey("sensors.sensor_id"))
    household_id = Column(Integer, ForeignKey("households.id"), nullable=True)
    sound_level = Column(Float)
    vibration_value = Column(Float, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    acceleration_x = Column(Float, nullable=True)
    acceleration_y = Column(Float, nullable=True)
    acceleration_z = Column(Float, nullable=True)
    received_at = Column(DateTime, default=func.now())    # 서버 수신 시각 (UTC)
    sensor_timestamp = Column(DateTime, nullable=True)    # 센서 측정 시각

    __table_args__ = (
        UniqueConstraint("sensor_id", "sensor_timestamp", name="uq_sensor_timestamp"),
    )

# 이벤트화된 소음 이벤트 테이블 (신규)
class NoiseEvent(Base):
    __tablename__ = "noise_events"

    id = Column(Integer, primary_key=True, index=True)
    sensor_id = Column(String, ForeignKey("sensors.sensor_id"))
    household_id = Column(Integer, ForeignKey("households.id"), nullable=True)
    event_type = Column(String)              # impact_noise, daily_noise, repeated_vibration, background_noise
    severity = Column(String)               # low, medium, high
    severity_score = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    is_night = Column(Boolean, default=False)   # KST 기준 야간 판정
    is_meaningful = Column(Boolean, default=False)  # 의미 이벤트 여부
    pattern_label = Column(String, nullable=True)
    avg_sound_level = Column(Float, nullable=True)
    max_sound_level = Column(Float, nullable=True)
    avg_vibration = Column(Float, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    sample_count = Column(Integer, default=1)   # 이벤트에 포함된 샘플 수
    started_at = Column(DateTime)               # 이벤트 시작 시각 (UTC)
    ended_at = Column(DateTime, nullable=True)  # 이벤트 종료 시각 (UTC)
    status = Column(String, default="new")      # new, in_mediation, resolved

# 소음 로그 테이블 (기존 유지 - 하위 호환)
class NoiseLog(Base):
    __tablename__ = "noise_logs"

    id = Column(Integer, primary_key=True, index=True)
    sensor_id = Column(String, ForeignKey("sensors.sensor_id"))
    household_id = Column(Integer, ForeignKey("households.id"), nullable=True)
    sound_level = Column(Float)
    vibration_value = Column(Float, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    event_type = Column(String, nullable=True)
    severity = Column(String, nullable=True)
    severity_score = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    is_night = Column(Boolean, nullable=True)
    pattern_label = Column(String, nullable=True)
    status = Column(String, default="new")
    timestamp = Column(DateTime, server_default=func.now())

# 중재 프로세스 테이블
class Mediation(Base):
    __tablename__ = "mediations"

    id = Column(Integer, primary_key=True, index=True)
    noise_log_id = Column(Integer, ForeignKey("noise_logs.id"), nullable=True)
    noise_event_id = Column(Integer, ForeignKey("noise_events.id"), nullable=True)  # 신규
    household_id = Column(Integer, ForeignKey("households.id"), nullable=True)
    target_unit = Column(String)
    ai_message = Column(String)
    event_summary = Column(Text, nullable=True)
    resident_message = Column(Text, nullable=True)
    admin_summary = Column(Text, nullable=True)
    recommended_action = Column(String, nullable=True)
    generation_method = Column(String, nullable=True)
    tone_check_json = Column(Text, nullable=True)
    status = Column(String, default="pending")
    created_at = Column(DateTime, server_default=func.now())

# 공지사항 테이블
class Notice(Base):
    __tablename__ = "notices"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    content = Column(Text)
    notice_type = Column(String)
    target_type = Column(String)
    target_households = Column(Text, nullable=True)
    status = Column(String, default="draft")
    created_by = Column(Integer, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

# 관리자 업무 설정 테이블
class AdminSettings(Base):
    __tablename__ = "admin_settings"

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("admins.id"))
    noise_threshold = Column(Float, default=40.0)
    duration_threshold = Column(Integer, default=10)
    off_hours_mute = Column(Boolean, default=False)
    work_start_time = Column(String, nullable=True)
    work_end_time = Column(String, nullable=True)
    updated_at = Column(DateTime, server_default=func.now())

