import json
import sqlite3
from datetime import datetime, timedelta


BASE_TIME = datetime(2026, 6, 3, 10, 0, 0)

DUMMY_NOTICES = [
    {
        "title": "야간 소음 자제 안내",
        "content": "밤 10시 이후 생활 소음으로 인한 불편이 증가하고 있습니다. 청소기, 세탁기 사용을 자제하고 실내화 착용을 권장드립니다.",
        "notice_type": "life_etiquette",
        "target_type": "all",
        "target_households": None,
        "status": "sent",
        "sent_at": BASE_TIME - timedelta(hours=2),
    },
    {
        "title": "월간 소음 현황 안내",
        "content": "이번 달 우리 단지의 층간소음 발생 현황을 안내드립니다. 쾌적한 주거 환경을 위해 입주민 여러분의 협조를 부탁드립니다.",
        "notice_type": "general_notice",
        "target_type": "all",
        "target_households": None,
        "status": "sent",
        "sent_at": BASE_TIME - timedelta(days=1, hours=1),
    },
    {
        "title": "IoT 센서 정기 점검 안내",
        "content": "층간소음 측정 센서의 정기 점검이 예정되어 있습니다. 대상 세대는 점검에 협조 부탁드립니다.",
        "notice_type": "equipment_check",
        "target_type": "selected",
        "target_households": [1, 2, 3, 4],
        "status": "sent",
        "sent_at": BASE_TIME - timedelta(days=1, hours=5),
    },
    {
        "title": "반복 소음 주의 안내",
        "content": "최근 일부 세대에서 반복 소음이 감지되었습니다. 층간소음 예방을 위해 생활 소음에 유의해 주세요.",
        "notice_type": "urgent_alert",
        "target_type": "selected",
        "target_households": [1, 5],
        "status": "sent",
        "sent_at": BASE_TIME - timedelta(days=2),
    },
    {
        "title": "층간소음 예방 캠페인",
        "content": "이번 주부터 층간소음 예방 캠페인을 진행합니다. 실내 슬리퍼 착용과 야간 시간대 소음 자제를 부탁드립니다.",
        "notice_type": "general_notice",
        "target_type": "all",
        "target_households": None,
        "status": "sent",
        "sent_at": BASE_TIME - timedelta(days=3, hours=3),
    },
    {
        "title": "발소리 완화 가이드",
        "content": "발걸음 소리 완화를 위해 실내화 착용과 매트 사용을 권장드립니다.",
        "notice_type": "life_etiquette",
        "target_type": "all",
        "target_households": None,
        "status": "sent",
        "sent_at": BASE_TIME - timedelta(days=3, hours=8),
    },
    {
        "title": "센서 배터리 교체 안내",
        "content": "일부 세대의 센서 배터리 교체가 필요합니다. 안정적인 측정을 위해 점검에 협조 부탁드립니다.",
        "notice_type": "equipment_check",
        "target_type": "selected",
        "target_households": [6, 7, 8],
        "status": "sent",
        "sent_at": BASE_TIME - timedelta(days=4, hours=2),
    },
    {
        "title": "긴급 소음 발생 알림",
        "content": "기준치를 초과하는 소음이 감지되었습니다. 해당 세대는 즉시 확인 후 소음 저감에 협조 부탁드립니다.",
        "notice_type": "urgent_alert",
        "target_type": "selected",
        "target_households": [9],
        "status": "sent",
        "sent_at": BASE_TIME - timedelta(days=5, hours=4),
    },
    {
        "title": "주말 생활 소음 안내",
        "content": "주말 오전과 야간 시간대에는 생활 소음이 크게 전달될 수 있습니다. 입주민 여러분의 배려를 부탁드립니다.",
        "notice_type": "life_etiquette",
        "target_type": "all",
        "target_households": None,
        "status": "sent",
        "sent_at": BASE_TIME - timedelta(days=6, hours=1),
    },
    {
        "title": "관리사무소 협조 요청",
        "content": "층간소음 민원 예방을 위해 관리사무소 안내에 협조 부탁드립니다. 모두가 편안한 주거 환경을 만들기 위한 안내입니다.",
        "notice_type": "general_notice",
        "target_type": "all",
        "target_households": None,
        "status": "sent",
        "sent_at": BASE_TIME - timedelta(days=6, hours=7),
    },
]


def seed_dummy_notices() -> None:
    conn = sqlite3.connect("kunglog.db")
    cur = conn.cursor()

    # Remove only broken dummy rows created by console encoding issues.
    cur.execute("DELETE FROM notices WHERE title LIKE '%?%'")

    added = []
    for item in DUMMY_NOTICES:
        exists = cur.execute(
            "SELECT id FROM notices WHERE title = ?",
            (item["title"],),
        ).fetchone()
        if exists:
            continue

        target_households = item["target_households"]
        target_json = json.dumps(target_households, ensure_ascii=False) if target_households else None
        sent_at = item["sent_at"].isoformat(sep=" ")

        cur.execute(
            """
            INSERT INTO notices
                (title, content, notice_type, target_type, target_households, status, sent_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["title"],
                item["content"],
                item["notice_type"],
                item["target_type"],
                target_json,
                item["status"],
                sent_at,
                sent_at,
            ),
        )
        added.append(item["title"])

    conn.commit()
    total = cur.execute("SELECT COUNT(*) FROM notices").fetchone()[0]
    recent = cur.execute(
        """
        SELECT id, title, notice_type, target_type, status, sent_at
        FROM notices
        ORDER BY created_at DESC
        LIMIT 10
        """
    ).fetchall()

    print(f"Added notices: {len(added)}")
    print(f"Total notices: {total}")
    for row in recent:
        print(row)

    conn.close()


if __name__ == "__main__":
    seed_dummy_notices()
