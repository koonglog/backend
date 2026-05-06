from pydantic import BaseModel
from datetime import datetime, date
from typing import List, Optional

# --- [1] 기존 main.py에서 옮겨온 스키마 ---

class NoiseData(BaseModel):
    sensor_id: str
    sound_level: float
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

# --- [2] 신규: 소음 분석(Analysis) 페이지용 스키마 ---

class HourlyStat(BaseModel):
    """시간대별 기준치 초과 세대 수 차트용"""
    hour: int
    day_excess_count: int   # 주간(07-22시) 기준치(39dB) 초과
    night_excess_count: int  # 야간(22-07시) 기준치(34dB) 초과

class NoiseTypeStat(BaseModel):
    """소음 유형별 점유율 도넛 차트용"""
    category: str
    count: int
    percentage: float

class AnalysisSummary(BaseModel):
    """상단 4개 요약 카드 지표"""
    peak_night_hour: int      # 야간 최다 초과 시간
    peak_night_count: int     # 해당 시간 초과 세대 수
    peak_day_hour: int        # 주간 최다 초과 시간
    peak_day_count: int       # 해당 시간 초과 세대 수
    total_excess_cases: int   # 총 초과 건수
    normal_hours_count: int   # 정상 시간대 (24시간 중 기준 미달 시간)

class AnalysisDashboardResponse(BaseModel):
    """분석 페이지 상단 통합 응답"""
    hourly_stats: List[HourlyStat]
    type_stats: List[NoiseTypeStat]
    summary: AnalysisSummary

class NoiseAnalysisLogResponse(BaseModel):
    """하단 소음 분류 테이블용"""
    timestamp: datetime
    unit_alias: str           # 세대 (예: A동 304호)
    event_type: str           # 분류 (예: 충격음)
    sub_category: str         # 세부 (예: 반복 충격)
    sound_level: float        # 데시벨 (dB)
    duration_min: int         # 지속시간 (분 단위 변환)
    pattern_detail: str       # 패턴 (예: 7회 반복)

    class Config:
        from_attributes = True