from sqlalchemy import select
from app.db.session import SessionLocal
from app.models import User, Matter, Conversation, Message

def test_database_operations():
    db = SessionLocal()

    try:
        # 1. CREATE: Insert a user
        user = User(
            email="schema_test@example.com",
            password_hash="test_hash",
            display_name="Schema Test User"
        )

        db.add(user)
        db.flush()

        print("User created:", user.id)

        # 2. CREATE: Insert a matter
        matter = Matter(
            title="Database Schema Test",
            owner_user_id=user.id
        )

        db.add(matter)
        db.flush()

        print("Matter created:", matter.id)

        # 3. CREATE: Insert a conversation
        conversation = Conversation(
    owner_user_id=user.id,
    role_context="legal_assistant",
    matter_id=matter.id,
    title="Test Conversation"
        )

        db.add(conversation)
        db.flush()

        print("Conversation created:", conversation.id)

        # 4. CREATE: Insert a message
        message = Message(
            conversation_id=conversation.id,
            sender_type="user",
            content="This is a database test message.",
            status="completed"
        )

        db.add(message)
        db.flush()

        print("Message created:", message.id)

        # 5. READ: Retrieve the message
        saved_message = db.execute(
            select(Message).where(Message.id == message.id)
        ).scalar_one()

        print("Retrieved message:", saved_message.content)

        # 6. UPDATE: Modify the message
        saved_message.content = "Updated database test message."
        db.flush()

        print("Updated message:", saved_message.content)

        # Roll back so test records are not permanently saved
        db.rollback()

        print("\nSUCCESS: Database CRUD operations passed!")

    except Exception as error:
        db.rollback()
        print("\nDATABASE TEST FAILED:")
        print(error)
        raise

    finally:
        db.close()


if __name__ == "__main__":
    test_database_operations()