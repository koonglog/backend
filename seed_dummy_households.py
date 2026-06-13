import hashlib
import secrets

import models
from database import SessionLocal, engine


DEFAULT_PASSWORD = "resident1234"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000,
    )
    return f"pbkdf2_sha256${salt}${digest.hex()}"


DUMMY_HOUSEHOLDS = [
    {
        "username": "resident_a301",
        "email": "a301@koonglog.com",
        "apartment_name": "KoongLog Apt",
        "building_name": "A",
        "unit_number": "301",
        "floor": 3,
        "alias": "A-301",
        "resident_name": "김민준",
        "phone_number": "010-2001-0301",
        "quiet_start_time": "22:00",
        "quiet_end_time": "07:00",
    },
    {
        "username": "resident_a302",
        "email": "a302@koonglog.com",
        "apartment_name": "KoongLog Apt",
        "building_name": "A",
        "unit_number": "302",
        "floor": 3,
        "alias": "A-302",
        "resident_name": "이서연",
        "phone_number": "010-2001-0302",
        "quiet_start_time": "23:00",
        "quiet_end_time": "06:30",
    },
    {
        "username": "resident_a401",
        "email": "a401@koonglog.com",
        "apartment_name": "KoongLog Apt",
        "building_name": "A",
        "unit_number": "401",
        "floor": 4,
        "alias": "A-401",
        "resident_name": "박지훈",
        "phone_number": "010-2001-0401",
    },
    {
        "username": "resident_a402",
        "email": "a402@koonglog.com",
        "apartment_name": "KoongLog Apt",
        "building_name": "A",
        "unit_number": "402",
        "floor": 4,
        "alias": "A-402",
        "resident_name": "최유진",
        "phone_number": "010-2001-0402",
        "quiet_start_time": "21:30",
        "quiet_end_time": "06:00",
    },
    {
        "username": "resident_b201",
        "email": "b201@koonglog.com",
        "apartment_name": "KoongLog Apt",
        "building_name": "B",
        "unit_number": "201",
        "floor": 2,
        "alias": "B-201",
        "resident_name": "정하늘",
        "phone_number": "010-2002-0201",
        "quiet_start_time": "22:00",
        "quiet_end_time": "08:00",
    },
    {
        "username": "resident_b202",
        "email": "b202@koonglog.com",
        "apartment_name": "KoongLog Apt",
        "building_name": "B",
        "unit_number": "202",
        "floor": 2,
        "alias": "B-202",
        "resident_name": "강도윤",
        "phone_number": "010-2002-0202",
    },
    {
        "username": "resident_b301",
        "email": "b301@koonglog.com",
        "apartment_name": "KoongLog Apt",
        "building_name": "B",
        "unit_number": "301",
        "floor": 3,
        "alias": "B-301",
        "resident_name": "조수빈",
        "phone_number": "010-2002-0301",
        "quiet_start_time": "23:30",
        "quiet_end_time": "07:30",
    },
    {
        "username": "resident_b302",
        "email": "b302@koonglog.com",
        "apartment_name": "KoongLog Apt",
        "building_name": "B",
        "unit_number": "302",
        "floor": 3,
        "alias": "B-302",
        "resident_name": "윤서준",
        "phone_number": "010-2002-0302",
        "quiet_start_time": "22:00",
        "quiet_end_time": "06:00",
    },
    {
        "username": "resident_c101",
        "email": "c101@koonglog.com",
        "apartment_name": "KoongLog Apt",
        "building_name": "C",
        "unit_number": "101",
        "floor": 1,
        "alias": "C-101",
        "resident_name": "장예린",
        "phone_number": "010-2003-0101",
    },
    {
        "username": "resident_c102",
        "email": "c102@koonglog.com",
        "apartment_name": "KoongLog Apt",
        "building_name": "C",
        "unit_number": "102",
        "floor": 1,
        "alias": "C-102",
        "resident_name": "임지호",
        "phone_number": "010-2003-0102",
        "quiet_start_time": "21:00",
        "quiet_end_time": "06:00",
    },
    {
        "username": "resident_c201",
        "email": "c201@koonglog.com",
        "apartment_name": "KoongLog Apt",
        "building_name": "C",
        "unit_number": "201",
        "floor": 2,
        "alias": "C-201",
        "resident_name": "한지민",
        "phone_number": "010-2003-0201",
        "quiet_start_time": "22:30",
        "quiet_end_time": "07:00",
    },
    {
        "username": "resident_c202",
        "email": "c202@koonglog.com",
        "apartment_name": "KoongLog Apt",
        "building_name": "C",
        "unit_number": "202",
        "floor": 2,
        "alias": "C-202",
        "resident_name": "오세훈",
        "phone_number": "010-2003-0202",
    },
    {
        "username": "resident_d101",
        "email": "d101@koonglog.com",
        "apartment_name": "KoongLog Apt",
        "building_name": "D",
        "unit_number": "101",
        "floor": 1,
        "alias": "D-101",
        "resident_name": "신유나",
        "phone_number": "010-2004-0101",
        "quiet_start_time": "23:00",
        "quiet_end_time": "08:00",
    },
    {
        "username": "resident_d102",
        "email": "d102@koonglog.com",
        "apartment_name": "KoongLog Apt",
        "building_name": "D",
        "unit_number": "102",
        "floor": 1,
        "alias": "D-102",
        "resident_name": "서지우",
        "phone_number": "010-2004-0102",
        "quiet_start_time": "22:00",
        "quiet_end_time": "07:00",
    },
    {
        "username": "resident_d201",
        "email": "d201@koonglog.com",
        "apartment_name": "KoongLog Apt",
        "building_name": "D",
        "unit_number": "201",
        "floor": 2,
        "alias": "D-201",
        "resident_name": "권민서",
        "phone_number": "010-2004-0201",
    },
]


def seed_dummy_households() -> None:
    models.Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        password_hash = hash_password(DEFAULT_PASSWORD)
        added = []
        updated = []

        for item in DUMMY_HOUSEHOLDS:
            exists = (
                db.query(models.Household)
                .filter(
                    (models.Household.username == item["username"])
                    | (models.Household.email == item["email"])
                )
                .first()
            )
            if exists:
                changed = False
                for key, value in item.items():
                    if getattr(exists, key, None) != value:
                        setattr(exists, key, value)
                        changed = True
                if not exists.password_hash:
                    exists.password_hash = password_hash
                    changed = True
                if exists.is_active is None:
                    exists.is_active = True
                    changed = True
                if changed:
                    updated.append(item["username"])
                continue

            household = models.Household(
                **item,
                password_hash=password_hash,
                is_active=True,
            )
            db.add(household)
            added.append(item["username"])

        db.commit()
        total = db.query(models.Household).count()

        print(f"Added households: {len(added)}")
        print(f"Updated households: {len(updated)}")
        print(f"Total households: {total}")
        if added:
            print("Added usernames:")
            for username in added:
                print(f"- {username}")
        print(f"Default password: {DEFAULT_PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    seed_dummy_households()
