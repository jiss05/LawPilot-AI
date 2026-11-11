import getpass

from sqlalchemy import select

from app.db.session import SessionLocal
from app.core.security import hash_password
from app.models.user import User
from app.models.role import Role
from app.models.user_role import UserRole
from app.services.role_service import seed_roles


def create_initial_admin():
    email = input("Enter administrator email: ").strip().lower()
    display_name = input("Enter administrator full name: ").strip()

    if not email or not display_name:
        print("Email and full name are required.")
        return

    password = getpass.getpass("Enter administrator password: ")
    confirm_password = getpass.getpass("Confirm administrator password: ")

    if len(password) < 12:
        print("Password must contain at least 12 characters.")
        return

    if password != confirm_password:
        print("Passwords do not match.")
        return

    db = SessionLocal()

    try:
        # Ensure all four standard roles exist.
        seed_roles(db)

        # Prevent accidental creation of a second administrator.
        existing_admin = db.scalar(
            select(User)
            .join(UserRole, User.id == UserRole.user_id)
            .join(Role, UserRole.role_id == Role.id)
            .where(Role.code == "ADMIN")
        )

        if existing_admin:
            print("An ADMIN account already exists. Setup cancelled.")
            return

        # Do not overwrite or promote an existing account silently.
        existing_user = db.scalar(
            select(User).where(User.email == email)
        )

        if existing_user:
            print("An account with this email already exists.")
            return

        admin_role = db.scalar(
            select(Role).where(Role.code == "ADMIN")
        )

        if admin_role is None:
            print("ADMIN role could not be found.")
            return

        admin = User(
            email=email,
            display_name=display_name,
            password_hash=hash_password(password),
            email_verified=True,
            is_active=True,
        )

        db.add(admin)
        db.flush()

        db.add(
            UserRole(
                user_id=admin.id,
                role_id=admin_role.id,
                assigned_by=None,
            )
        )

        db.commit()

        print("\nInitial administrator created successfully.")
        print(f"Email: {email}")
        print(f"User ID: {admin.id}")
        print("Role: ADMIN")
        print("Email verified: True")
        print("Account active: True")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    create_initial_admin()
