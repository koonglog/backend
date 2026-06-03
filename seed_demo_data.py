from seed_dummy_households import seed_dummy_households
from seed_dummy_notices import seed_dummy_notices


def seed_demo_data() -> None:
    print("=== Seed dummy households ===")
    seed_dummy_households()
    print()
    print("=== Seed dummy notices ===")
    seed_dummy_notices()
    print()
    print("Demo data seeding complete.")


if __name__ == "__main__":
    seed_demo_data()
