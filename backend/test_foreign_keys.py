from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal


def test_foreign_key_constraint():
    db = SessionLocal()

    try:
        fake_user_id = str(uuid4())

        db.execute(
            text("""
                INSERT INTO conversations
                    (id, owner_user_id, role_context, title)
                VALUES
                    (:id, :owner_user_id, :role_context, :title)
            """),
            {
                "id": str(uuid4()),
                "owner_user_id": fake_user_id,
                "role_context": "legal_assistant",
                "title": "Invalid Foreign Key Test"
            }
        )

        db.commit()

        print("FAILED: Database accepted an invalid user reference.")

    except IntegrityError as error:
        db.rollback()

        if getattr(error.orig, "sqlstate", None) == "23503":
            print("SUCCESS: Foreign-key constraint is working!")
            print("PostgreSQL rejected the non-existent user.")
        else:
            raise

    finally:
        db.close()


if __name__ == "__main__":
    test_foreign_key_constraint()