"""认证路由：账号 + 密码。"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.security import create_access_token, hash_password, verify_password
from app.services import login_throttle

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """注册：密码一致性已由 RegisterRequest 校验，这里只查账号是否重复。"""
    exists = db.query(User).filter(User.username == body.username).first()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该账号已被注册")
    user = User(
        username=body.username,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    bucket = login_throttle.key(request.client.host if request.client else "unknown", body.username)
    login_throttle.check(bucket)
    user = db.query(User).filter(User.username == body.username).first()
    if user is None or not verify_password(body.password, user.hashed_password):
        login_throttle.record(bucket, False)
        # 账号不存在与密码错误返回同一提示，避免账号枚举
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号或密码错误")
    login_throttle.record(bucket, True)
    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
