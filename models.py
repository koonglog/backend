from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Enum, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
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

# 건물/세대 테이블
class Household(Base):
    __tablename__ = "households"

    id = Column(Integer, primary_key=True, index=True)
    building_name = Column(String)       # 예: "A동"
    unit_number = Column(String)         # 예: "101호"
    floor = Column(Integer)
    alias = Column(String)               # 예: "A-101"
    
    # 관계 설정
    sensors = relationship("Sensor", back_populates="household")
    noise_logs = relationship("NoiseLog", back_populates="household")
    mediations = relationship("Mediation", back_populates="household")

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
    household_id = Column(Integer, ForeignKey("households.id"), nullable=True)
    location_unit = Column(String)
    source = Column(String, default="simulator")  # arduino | simulator
    is_online = Column(Boolean, default=True)
    battery_level = Column(Integer, default=100)
    calibration_offset = Column(Float, default=0.0)
    last_checked = Column(DateTime, default=func.now())

    # 관계 설정
    household = relationship("Household", back_populates="sensors")
    noise_logs = relationship("NoiseLog", back_populates="sensor")

# 소음 로그 테이블 (소음 분석 페이지 대응 수정)
class NoiseLog(Base):
    __tablename__ = "noise_logs"

    id = Column(Integer, primary_key=True, index=True)
    sensor_id = Column(String, ForeignKey("sensors.sensor_id"))
    household_id = Column(Integer, ForeignKey("households.id"), nullable=True)
    
    # 소음 데이터
    sound_level = Column(Float)          # 데시벨(dB)
    vibration_value = Column(Float, nullable=True)
    duration_ms = Column(Integer, nullable=True)     # 지속시간 (ms)
    
    # AI 분석 및 분류 (기획안 하단 테이블 필드 반영)
    event_type = Column(String, nullable=True)       # 대분류: 충격음, 망치질, 끄는 소리 등
    sub_category = Column(String, nullable=True)     # 세부분류: 반복 충격, 가구 이동, 낙하 충격 등 (신규 추가)
    pattern_detail = Column(String, nullable=True)   # 패턴 상세: 7회 반복, 지속적, 일회성 등 (신규 추가)
    
    # 분석 지표
    severity = Column(String, nullable=True)         # low, medium, high
    severity_score = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    is_night = Column(Boolean, nullable=True)        # 주간/야간 구분
    pattern_label = Column(String, nullable=True)    # 분석 태그 (예: repeated_vibration)
    status = Column(String, default="new")           # new, in_mediation, resolved
    timestamp = Column(DateTime, server_default=func.now())

    # 관계 설정
    sensor = relationship("Sensor", back_populates="noise_logs")
    household = relationship("Household", back_populates="noise_logs")
    mediation = relationship("Mediation", back_populates="noise_log", uselist=False)

# 중재 프로세스 테이블
class Mediation(Base):
    __tablename__ = "mediations"

    id = Column(Integer, primary_key=True, index=True)
    noise_log_id = Column(Integer, ForeignKey("noise_logs.id"), nullable=True)
    household_id = Column(Integer, ForeignKey("households.id"), nullable=True)
    target_unit = Column(String)
    
    # AI 생성 메시지 정보
    ai_message = Column(String)
    event_summary = Column(Text, nullable=True)
    resident_message = Column(Text, nullable=True)
    admin_summary = Column(Text, nullable=True)
    recommended_action = Column(String, nullable=True)
    generation_method = Column(String, nullable=True)   # template, openai
    tone_check_json = Column(Text, nullable=True)
    
    status = Column(String, default="대기")
    created_at = Column(DateTime, server_default=func.now())

# 공지사항 테이블
class Notice(Base):
    __tablename__ = "notices"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)                    # 공지 제목
    content = Column(Text)                    # 공지 내용
    notice_type = Column(String)              # urgent, general, manner, equipment
    target_type = Column(String)              # all, specific
    target_households = Column(Text, nullable=True)  # 특정 세대 목록 JSON
    status = Column(String, default="draft")  # draft, sent, scheduled
    created_by = Column(Integer, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

# 관리자 업무 설정 테이블
class AdminSettings(Base):
    __tablename__ = "admin_settings"

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("admins.id"))
    noise_threshold = Column(Float, default=40.0)    # 긴급 알람 임계값 (dB)
    duration_threshold = Column(Integer, default=10)  # 지속 시간 (초)
    off_hours_mute = Column(Boolean, default=False)   # 업무 시간외 알람 차단
    work_start_time = Column(String, nullable=True)   # 근무 시작 시간
    work_end_time = Column(String, nullable=True)     # 근무 종료 시간
    updated_at = Column(DateTime, server_default=func.now())

