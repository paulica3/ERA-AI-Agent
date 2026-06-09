"""Create (or update) a user directly in the database — for local testing.

Bypasses the invite-code / API-key handshake so you can log in immediately.

Usage:
    python seed_user.py <email> <password> [display_name]

Example:
    python seed_user.py admin@era.md parola123 "Paolo"

Honors ERA_DATA_DIR / DATABASE_URL the same way the API does, so it writes to
the same database the server reads.
"""
import sys

from era_agent.db.database import SessionLocal, init_db
from era_agent.db.models import User
from era_agent.auth.security import hash_password
from era_agent.profiles.service import get_or_create_profile


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    email = sys.argv[1].strip().lower()
    password = sys.argv[2]
    display_name = sys.argv[3].strip() if len(sys.argv) > 3 else ""

    if len(password) < 8:
        print("Password must be at least 8 characters.")
        sys.exit(1)

    init_db()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one_or_none()
        if user is None:
            user = User(email=email, password_hash=hash_password(password),
                        display_name=display_name)
            db.add(user)
            action = "created"
        else:
            user.password_hash = hash_password(password)
            if display_name:
                user.display_name = display_name
            action = "updated"
        db.commit()
        db.refresh(user)
        get_or_create_profile(db, user.id)
        print(f"User {action}: {email} (id={user.id})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
