# 🚀 쿵로그 (KungLog) - AI/IoT 기반 층간소음 중재 시스템

**쿵로그**는 공동주택 내 층간소음 갈등을 데이터와 AI로 해결하기 위한 관리자용 솔루션입니다. 실시간으로 소음을 감지하고, AI가 자동으로 중재 메시지를 생성하여 관리자와 주민 간의 소통을 효율화합니다.

## 🛠 Tech Stack
*   **Language**: Python 3.10+
*   **Framework**: FastAPI (Asynchronous Web Framework)
*   **Database**: SQLite with SQLAlchemy (ORM)
*   **Validation**: Pydantic
*   **Communication**: REST API (with Requests for Simulator)

## ✨ Key Features (Back-end)
*   **Real-time Data Pipeline**: 가상 IoT 센서 시뮬레이터를 활용해 실시간 $dB$ 데이터 수집 및 서버 전송 환경 구축.
*   **AI Auto-Mediation**: 특정 임계치(40$dB$ 이상) 감지 시, 해당 세대 정보와 소음 강도를 분석하여 맞춤형 중재 메시지 초안 자동 생성.
*   **Dashboard Analytics**: 단지 내 온라인 센서 현황, 금일 발생 경고 횟수, 실시간 평균 소음 수치 등 핵심 지표를 실시간으로 계산하여 제공.
*   **Admin Management**: 생성된 중재 메시지의 상태(대기/승인/발송완료)를 변경 및 관리할 수 있는 PATCH API 구현.

## 🏗 System Architecture
1.  **IoT Simulator**: 실시간 소음 수치 발생 및 서버 전송.
2.  **FastAPI Server**: 데이터 수신 및 AI 로직 실행.
3.  **Database**: 소음 로그 및 AI 중재 데이터 영구 저장.
4.  **API Endpoints**: 프론트엔드 및 관리자 페이지 연동용 인터페이스 제공.

## 🔗 API Endpoints (v1)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/v1/dashboard/stats` | 대시보드 상단 실시간 통계 수치 조회 |
| `POST` | `/api/v1/noise-logs` | 소음 데이터 수신 및 AI 분석 트리거 |
| `GET` | `/api/v1/mediations` | AI가 생성한 중재 메시지 초안 목록 조회 |
| `PATCH`| `/api/v1/mediations/{med_id}` | 중재 메시지 상태 업데이트 (관리자 승인 등) |

## 🚀 How to Run
1. **의존성 설치**: `pip install -r requirements.txt`
2. **서버 실행**: `uvicorn main:app --reload`
3. **시뮬레이터 실행**: `python simulator.py`

---
**Author**: Seo Mira (Sungshin Women's Univ, AI Convergence Major)
**Project**: 2026 Capstone Design