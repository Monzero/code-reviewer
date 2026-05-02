from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from core.security.jwt import verify_token

_bearer = HTTPBearer(auto_error=True)


def get_current_judge(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    payload = verify_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return payload["sub"]
