from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.user import User
from app.models.role import Role
from app.models.user_role import UserRole
from app.services.role_service import seed_roles


def promote_client_to_admin():
    email = input("Enter existing CLIENT email: ").strip().lower()

    if not email:
        print("Email is required.")
        return

    db = SessionLocal()

    try:
        user = db.scalar(
            select(User).where(User.email == email)
        )

        if user is None:
            print("User account not found.")
            return

        if not user.email_verified:
            print("Account email is not verified.")
            return

        if not user.is_active:
            print("Account is not active.")
            return

        seed_roles(db)

        admin_role = db.scalar(
            select(Role).where(Role.code == "ADMIN")
        )

        if admin_role is None:
            print("ADMIN role not found.")
            return

        existing_assignment = db.scalar(
            select(UserRole).where(
                UserRole.user_id == user.id,
                UserRole.role_id == admin_role.id,
            )
        )

        if existing_assignment:
            print("User already has ADMIN role.")
            return

        db.add(
            UserRole(
                user_id=user.id,
                role_id=admin_role.id,
                assigned_by=None,
            )
        )

        db.commit()

        print("\nAccount successfully promoted!")
        print(f"Email: {user.email}")
        print("CLIENT role: Preserved")
        print("ADMIN role: Assigned")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    promote_client_to_admin()
