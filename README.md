# 🚀 쿵로그 (KungLog) - AI/IoT 기반 층간소음 중재 시스템

**쿵로그**는 공동주택 내 층간소음 갈등을 데이터와 AI로 해결하기 위한 통합 솔루션입니다.
실시간으로 소음을 감지하고, AI가 자동으로 중재 메시지를 생성하여 관리자와 주민 간의 소통을 효율화합니다.

---

## 🛠 Tech Stack

- **Language**: Python 3.10+
- **Framework**: FastAPI
- **Database**: SQLite + SQLAlchemy (ORM)
- **Validation**: Pydantic
- **AI 연동**: Claude AI (중재 메시지 생성), 자체 AI 서버 (소음 분류/패턴 분석)
- **배포**: Railway

---

## ✨ Key Features

- **Real-time Data Pipeline**: 아두이노 IoT 센서 및 시뮬레이터로 실시간 소음/진동 데이터 수집
- **AI 소음 분류**: AI 서버 연동으로 충격음, 생활소음, 반복진동 등 자동 분류 및 심각도 판단
- **AI 중재 메시지 자동 생성**: 비폭력 대화 원칙 기반 맞춤형 중재 메시지 자동 생성
- **Dashboard Analytics**: 모니터링 세대 현황, 긴급 대응 세대, 시간대별 소음 통계 제공
- **갈등 핫스팟 맵**: 건물별 소음 위험도 (긴급/관찰/정상) 시각화
- **중재 워크플로우**: 소음 감지 → AI 메시지 생성 → 관리자 검토 → 승인 발송 → 완료
- **공지사항 관리**: AI 템플릿 기반 공지사항 작성 및 예약 발송
- **주민/관리자 인증**: 회원가입, 로그인, 프로필 관리

---

## 🏗 System Architecture

```
아두이노 IoT 센서 / 시뮬레이터
        ↓
FastAPI 백엔드 서버 (Railway 배포)
        ↓
AI 서버 (소음 분류 / 패턴 분석)
        ↓
SQLite DB (소음 로그, 중재 데이터, 세대 정보)
        ↓
관리자 웹 (React) / 주민 앱 (Android)
```

---

## 🔗 API Endpoints (v1)

### 인증
| Method | Endpoint | Description |
|:---|:---|:---|
| `POST` | `/api/v1/auth/register` | 관리자 회원가입 |
| `POST` | `/api/v1/auth/login` | 관리자 로그인 |
| `POST` | `/api/v1/auth/logout` | 로그아웃 |
| `PATCH` | `/api/v1/auth/update-password` | 비밀번호 수정 |

### 대시보드
| Method | Endpoint | Description |
|:---|:---|:---|
| `GET` | `/api/v1/dashboard/stats` | 대시보드 통계 조회 |
| `GET` | `/api/v1/dashboard/households` | 전체 모니터링 세대 목록 |
| `GET` | `/api/v1/dashboard/urgent` | 긴급 대응 필요 세대 |
| `GET` | `/api/v1/dashboard/today-events` | 오늘 발생 소음 종합 |
| `GET` | `/api/v1/dashboard/hourly` | 시간대별 소음 발생 현황 |
| `GET` | `/api/v1/dashboard/completed` | 조치 완료 내역 |

### 센서 / 소음
| Method | Endpoint | Description |
|:---|:---|:---|
| `POST` | `/api/v1/sensor-readings` | 센서 데이터 수신 및 AI 분석 |
| `GET` | `/api/v1/sensor-readings/recent` | 최근 센서 데이터 조회 |
| `GET` | `/api/v1/noise-logs` | 소음 로그 목록 조회 |
| `GET` | `/api/v1/noise/distribution` | 소음 분포도 조회 |
| `GET` | `/api/v1/noise/hotspot` | 갈등 핫스팟 맵 조회 |

### 중재
| Method | Endpoint | Description |
|:---|:---|:---|
| `GET` | `/api/v1/mediations` | 중재 메시지 목록 조회 |
| `GET` | `/api/v1/mediations/{med_id}` | 중재 메시지 단건 조회 |
| `PATCH` | `/api/v1/mediations/{med_id}` | 중재 상태 업데이트 |
| `POST` | `/api/v1/mediations/{med_id}/approve` | AI 메시지 승인 및 발송 |
| `POST` | `/api/v1/mediations/request` | 주민 중재 요청 생성 |

### 공지사항
| Method | Endpoint | Description |
|:---|:---|:---|
| `POST` | `/api/v1/notices` | 공지사항 작성 및 발송 |
| `GET` | `/api/v1/notices` | 공지사항 목록 조회 |
| `GET` | `/api/v1/notices/{notice_id}` | 공지사항 단건 조회 |
| `PATCH` | `/api/v1/notices/{notice_id}` | 예약 공지 수정 |
| `DELETE` | `/api/v1/notices/{notice_id}` | 예약 공지 취소 |
| `POST` | `/api/v1/notices/ai-template` | AI 템플릿 추천 |

### 세대 / 주민
| Method | Endpoint | Description |
|:---|:---|:---|
| `GET` | `/api/v1/households/{household_id}/home` | 홈 화면 통합 조회 |
| `GET` | `/api/v1/households/{household_id}/summary` | 세대 소음 요약 조회 |
| `GET` | `/api/v1/households/{household_id}/profile` | 주민 프로필 조회 |
| `PATCH` | `/api/v1/households/{household_id}` | 아파트 정보 수정 |
| `PATCH` | `/api/v1/households/{household_id}/quiet-time` | 조용한 시간대 수정 |
| `DELETE` | `/api/v1/households/{household_id}/withdraw` | 회원 탈퇴 |
| `GET` | `/api/v1/households/{household_id}/noise-stats` | 24시간 소음 데이터 조회 |

---

## 🚀 How to Run

1. **의존성 설치**
```bash
pip install -r requirements.txt
```

2. **환경변수 설정** - `.env` 파일 생성
```
ENABLE_OPENAI=false
AI_SERVICE_URL=http://localhost:8001
```

3. **서버 실행**
```bash
uvicorn main:app --reload
```

4. **시뮬레이터 실행**
```bash
python simulator.py
```

5. **API 문서 확인**
```
http://localhost:8000/docs
```

---

## 🌐 배포

- **서버 주소**: `https://backend-production-815d.up.railway.app`
- **API 문서**: `https://backend-production-815d.up.railway.app/docs`

---
**Project**: 2026 Capstone Design
