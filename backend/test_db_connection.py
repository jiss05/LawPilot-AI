
import os
import traceback

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load environment variables from backend/.env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is missing from .env")

print("Testing PostgreSQL connection...")

try:
    engine = create_engine(DATABASE_URL)

    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT current_database(), current_user")
        )

        database, user = result.fetchone()

        print("\nDatabase connection successful!")
        print(f"Database: {database}")
        print(f"User: {user}")

    engine.dispose()

except Exception:
    print("\nDatabase connection failed!")
    traceback.print_exc()