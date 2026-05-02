from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.hash import bcrypt
from core.config import config


def create_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=config.security.jwt_expire_minutes
    )
    return jwt.encode(
        {"sub": username, "exp": expire},
        config.security.jwt_secret,
        algorithm=config.security.jwt_algorithm,
    )


def verify_token(token: str) -> dict | None:
    try:
        return jwt.decode(
            token,
            config.security.jwt_secret,
            algorithms=[config.security.jwt_algorithm],
        )
    except JWTError:
        return None


def authenticate_judge(username: str, password: str) -> bool:
    for judge in config.judges:
        if judge.username == username:
            return bcrypt.verify(password, judge.password_hash)
    return False
