from dataclasses import dataclass

from passlib.context import CryptContext

from .database import Base, SessionLocal, engine
from .models import User


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@dataclass
class AdminCommandResult:
    username: str
    action: str


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_or_update_admin(username: str, password: str) -> AdminCommandResult:
    username = username.strip()
    if not username:
        raise ValueError("Username is required.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            user = User(
                username=username,
                hashed_password=hash_password(password),
                is_active=True,
                is_admin=True,
            )
            db.add(user)
            action = "created"
        else:
            user.hashed_password = hash_password(password)
            user.is_active = True
            user.is_admin = True
            action = "updated"
        db.commit()
        return AdminCommandResult(username=username, action=action)
    finally:
        db.close()
