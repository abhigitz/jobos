import logging
import secrets
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.database import get_db
from app.dependencies import get_current_user, limiter
from app.models.password_reset_token import PasswordResetToken
from app.models.profile import ProfileDNA
from app.models.user import RefreshToken, User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
    VerifyEmailRequest,
)
from app.services.email_service import send_password_reset_email

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/hour")
async def register_user(
    request: Request,
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    """
    Register a new user account.

    Creates a new user with email, password, and full name. Also creates an associated
    ProfileDNA record. Email verification is not required.

    **Request:** RegisterRequest (email, password, full_name)
    **Response:** UserOut (user details without password)
    **Errors:** 400 (email already registered, invalid format), 422 (validation errors), 500 (registration failed)
    """
    email = payload.email.lower().strip()
    logger.info(
        "Registration attempt: email=%s full_name=%s",
        email,
        payload.full_name[:20] + "..." if len(payload.full_name or "") > 20 else (payload.full_name or ""),
    )
    try:
        # Check email uniqueness before insert
        existing = await db.execute(select(User).where(func.lower(User.email) == email))
        if existing.scalar_one_or_none() is not None:
            logger.info("Registration rejected: email already registered: %s", email)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        # Hash password (can raise on invalid input, but Pydantic validates first)
        try:
            hashed = hash_password(payload.password)
        except Exception as hash_err:
            logger.exception(
                "Registration password hashing failed: email=%s error=%s",
                email,
                hash_err,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Registration failed, please try again",
            )

        user = User(
            email=email,
            hashed_password=hashed,
            full_name=payload.full_name,
            email_verified=True,
        )
        db.add(user)
        await db.flush()

        profile = ProfileDNA(user_id=user.id)
        db.add(profile)

        await db.commit()
        await db.refresh(user)

        logger.info("Registration success: user_id=%s email=%s", user.id, email)
        return UserOut.model_validate(user)

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        err_msg = str(getattr(e, "orig", e)).lower()
        logger.warning(
            "Registration IntegrityError: email=%s err_msg=%s orig=%s",
            email,
            err_msg,
            repr(getattr(e, "orig", e)),
        )
        if "unique" in err_msg or "duplicate" in err_msg or "already exists" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )
        logger.exception("Registration integrity error (unexpected): %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed, please try again",
        )
    except OperationalError as e:
        await db.rollback()
        logger.exception(
            "Registration database connection error: email=%s error=%s",
            email,
            str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable. Please try again later.",
        )
    except ValueError as e:
        await db.rollback()
        err_str = str(e).lower()
        logger.warning("Registration ValueError: email=%s error=%s", email, e)
        if "email" in err_str or "invalid" in err_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email format",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        await db.rollback()
        tb = traceback.format_exc()
        logger.exception(
            "Registration failed (unhandled): email=%s exception=%s type=%s traceback=%s",
            email,
            str(e),
            type(e).__name__,
            tb,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed, please try again",
        )


@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def login(
    request: Request,
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Authenticate and receive JWT tokens.

    Returns access_token and refresh_token for API authentication.
    Access token expires in 30 minutes; refresh token is valid for 7 days.

    **Request:** LoginRequest (email, password)
    **Response:** TokenResponse (access_token, refresh_token, token_type, expires_in)
    **Errors:** 401 (invalid credentials)
    """
    # #region agent log
    try:
        _log_path = Path(__file__).resolve().parents[2] / ".cursor" / "debug.log"
        _log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(_log_path, "a") as _f:
            import json
            _f.write(json.dumps({"id":"login_entry","timestamp":__import__("time").time()*1000,"location":"auth.py:login","message":"Login attempt","data":{"email":payload.email[:3]+"***"},"hypothesisId":"H1"})+"\n")
    except Exception:
        pass
    # #endregion
    email = payload.email.lower().strip()
    result = await db.execute(select(User).where(func.lower(User.email) == email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    # #region agent log
    try:
        _pw_ok = verify_password(payload.password, user.hashed_password)
    except Exception as _verify_err:
        try:
            _lp = Path(__file__).resolve().parents[2] / ".cursor" / "debug.log"
            with open(_lp, "a") as _f:
                import json
                _f.write(json.dumps({"id":"login_verify_err","timestamp":__import__("time").time()*1000,"location":"auth.py:verify_password","message":"verify_password raised","data":{"err":str(_verify_err),"type":type(_verify_err).__name__},"hypothesisId":"H2"})+"\n")
        except Exception:
            pass
        raise
    # #endregion
    if not _pw_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))

    rt = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(refresh_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(rt)
    await db.commit()

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def refresh_token_endpoint(
    payload: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """
    Exchange refresh token for new access and refresh tokens.

    Rotates refresh token (old one is invalidated). Requires valid refresh_token.
    **Request:** RefreshRequest (refresh_token)
    **Response:** TokenResponse (access_token, refresh_token)
    **Errors:** 401 (invalid or expired refresh token)
    """
    from app.auth.jwt_handler import verify_token

    token = payload.refresh_token
    payload_data = verify_token(token)
    if not payload_data or payload_data.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    user_id = payload_data.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    # Find a matching refresh token record for this raw token
    result_tokens = await db.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))
    tokens = result_tokens.scalars().all()
    matched: Optional[RefreshToken] = None
    for rt in tokens:
        if hash_token(token) == rt.token_hash:
            matched = rt
            break

    if matched is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token not recognized")

    await db.delete(matched)

    new_access = create_access_token(str(user.id))
    new_refresh = create_refresh_token(str(user.id))

    new_rt = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(new_refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(new_rt)
    await db.commit()

    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.get("/me", response_model=UserOut, status_code=status.HTTP_200_OK)
async def get_me(current_user: User = Depends(get_current_user)) -> UserOut:
    """
    Get current authenticated user details.

    Requires Bearer token in Authorization header.
    **Response:** UserOut (id, email, full_name, is_active, etc.)
    **Errors:** 401 (unauthorized)
    """
    return UserOut.model_validate(current_user)


@router.post("/verify-email", response_model=MessageResponse, status_code=status.HTTP_200_OK)
async def verify_email(payload: VerifyEmailRequest, db: AsyncSession = Depends(get_db)) -> MessageResponse:
    """
    Verify email address (legacy/no-op).

    Email verification is no longer required. Returns success message.
    **Request:** VerifyEmailRequest (token, email)
    **Response:** MessageResponse
    """
    return MessageResponse(message="Email verification is no longer required. Please log in.")


@router.post("/resend-verification", response_model=MessageResponse, status_code=status.HTTP_200_OK)
async def resend_verification(
    payload: ResendVerificationRequest, db: AsyncSession = Depends(get_db)
) -> MessageResponse:
    """
    Resend verification email (legacy/no-op).

    Returns success message regardless of account existence (security).
    **Request:** ResendVerificationRequest (email)
    **Response:** MessageResponse
    """
    return MessageResponse(message="If an account exists with that email, a verification link has been sent.")


@router.post("/forgot-password", response_model=MessageResponse, status_code=status.HTTP_200_OK)
@limiter.limit("3/hour")
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """
    Request password reset email.

    Sends reset link to email if account exists. Always returns same message for security.
    Rate limited to 3 requests per hour per IP.
    **Request:** ForgotPasswordRequest (email)
    **Response:** MessageResponse
    """
    generic = MessageResponse(
        message="If an account exists with that email, a password reset link has been sent."
    )

    email = payload.email.lower().strip()
    result = await db.execute(select(User).where(func.lower(User.email) == email))
    user = result.scalar_one_or_none()
    if user is None:
        return generic

    count_result = await db.execute(
        select(func.count())
        .select_from(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.created_at > datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    if count_result.scalar() >= 3:
        return generic

    token = secrets.token_urlsafe(32)
    reset_token = PasswordResetToken(
        user_id=user.id,
        token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(reset_token)
    await db.commit()

    await send_password_reset_email(to_email=user.email, token=token)

    return generic


@router.post("/reset-password", response_model=MessageResponse, status_code=status.HTTP_200_OK)
@limiter.limit("3/hour")
async def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """
    Reset password using token from email.

    Invalidates the reset token and all refresh tokens for the user.
    **Request:** ResetPasswordRequest (token, new_password)
    **Response:** MessageResponse
    **Errors:** 400 (invalid or expired token)
    """
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token == payload.token)
    )
    token_row = result.scalar_one_or_none()
    if token_row is None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    if token_row.expires_at < datetime.now(timezone.utc):
        await db.delete(token_row)
        await db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    result = await db.execute(select(User).where(User.id == token_row.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user.hashed_password = hash_password(payload.new_password)
    await db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))
    await db.commit()

    return MessageResponse(message="Password has been reset successfully. Please log in with your new password.")
