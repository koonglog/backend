from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Enum
from sqlalchemy.sql import func
import enum
# database.py에서 Base를 가져옵니다. 
# 파일명이 database.py이므로 'from database'라고 써야 합니다.
from database import Base 

# 1. 관리자 직급 및 팀 구분을 위한 Enum
class AdminRole(str, enum.Enum):
    MANAGER = "관리소장"
    TECHNICAL = "시설과장"
    SECURITY = "보안팀장"
    STAFF = "관리원"

class TeamType(str, enum.Enum):
    ADMIN = "관리팀"
    SECURITY = "보안팀"

# 2. 관리자 테이블
class Admin(Base):
    __tablename__ = "admins"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    name = Column(String)
    role = Column(Enum(AdminRole), default=AdminRole.STAFF)
    team = Column(Enum(TeamType), default=TeamType.ADMIN)
    permission_level = Column(String) 

# 3. IoT 센서 테이블
class Sensor(Base):
    __tablename__ = "sensors"
    
    sensor_id = Column(String, primary_key=True, index=True)
    location_unit = Column(String) 
    is_online = Column(Boolean, default=True)
    battery_level = Column(Integer, default=100) 
    calibration_offset = Column(Float, default=0.0) 
    last_checked = Column(DateTime, default=func.now()) 

# 4. 소음 로그 테이블
class NoiseLog(Base):
    __tablename__ = "noise_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    sensor_id = Column(String, ForeignKey("sensors.sensor_id"))
    decibel = Column(Float) 
    noise_type = Column(String, nullable=True) 
    timestamp = Column(DateTime, server_default=func.now()) 

# 5. 중재 프로세스 테이블
class Mediation(Base):
    __tablename__ = "mediations"
    
    id = Column(Integer, primary_key=True, index=True)
    target_unit = Column(String) 
    ai_message = Column(String) 
    status = Column(String, default="대기") 
    created_at = Column(DateTime, server_default=func.now())