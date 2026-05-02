from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from core.security.jwt import authenticate_judge, create_token

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/auth/token", response_model=TokenResponse)
def login(body: LoginRequest):
    if not authenticate_judge(body.username, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    return TokenResponse(access_token=create_token(body.username))
