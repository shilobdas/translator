from sqlalchemy import inspect

try:
    from .database import SessionLocal, engine
    from .models import User
except ImportError:
    from database import SessionLocal, engine
    from models import User


def main():
    db = SessionLocal()
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print(f"Tables found: {tables}")

        if "users" not in tables:
            print("'users' table not found.")
            return

        print("'users' table exists.")
        user_count = db.query(User).count()
        print(f"Total users in DB: {user_count}")

        print("--- User List ---")
        for user in db.query(User).all():
            print(f"ID: {user.id} | Username: {user.username} | Admin: {user.is_admin}")
    except Exception as exc:
        print(f"Error: {exc}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
