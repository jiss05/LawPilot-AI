
from sqlalchemy import text
from app.db.session import engine

try:
    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT current_database()")
        )

        print("SQLAlchemy connection successful!")
        print("Connected database:", result.scalar())

except Exception as error:
    print("Connection failed:", error)

finally:
    engine.dispose()
