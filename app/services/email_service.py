"""Email service using Resend for transactional emails."""

import logging
from urllib.parse import quote

import resend

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
resend.api_key = settings.resend_api_key


async def send_verification_email(to_email: str, token: str, full_name: str) -> bool:
    """Send an email verification link to the user.

    Args:
        to_email: Recipient email address.
        token: Verification token.
        full_name: User's full name for the greeting.

    Returns:
        True if the email was sent successfully, False otherwise.
    """
    verification_url = (
        f"{settings.frontend_url}/verify-email"
        f"?token={quote(token)}&email={quote(to_email)}"
    )

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px;">
        <h2 style="color: #111827; margin-bottom: 16px;">Verify your email</h2>
        <p style="color: #374151; font-size: 16px; line-height: 1.6;">
            Hi {full_name},
        </p>
        <p style="color: #374151; font-size: 16px; line-height: 1.6;">
            Thanks for signing up for <strong>JobOS</strong>. Please verify your email
            address by clicking the button below.
        </p>
        <div style="text-align: center; margin: 32px 0;">
            <a href="{verification_url}"
               style="background-color: #2563eb; color: #ffffff; padding: 12px 32px;
                      border-radius: 6px; text-decoration: none; font-weight: 600;
                      display: inline-block;">
                Verify Email Address
            </a>
        </div>
        <p style="color: #6b7280; font-size: 14px; line-height: 1.5;">
            If the button doesn't work, copy and paste this link into your browser:
        </p>
        <p style="color: #6b7280; font-size: 14px; word-break: break-all;">
            {verification_url}
        </p>
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;" />
        <p style="color: #9ca3af; font-size: 12px;">
            If you didn't create a JobOS account, you can safely ignore this email.
        </p>
    </div>
    """

    try:
        resend.Emails.send(
            {
                "from": settings.email_from,
                "to": [to_email],
                "subject": "Verify your JobOS account",
                "html": html,
            }
        )
        logger.info("Verification email sent to %s", to_email)
        return True
    except Exception as e:
        logger.error("Failed to send verification email to %s: %s", to_email, e)
        return False


async def send_password_reset_email(to_email: str, token: str) -> bool:
    """Send a password reset link to the user.

    Args:
        to_email: Recipient email address.
        token: Password reset token.

    Returns:
        True if the email was sent successfully, False otherwise.
    """
    reset_url = f"{settings.frontend_url}/reset-password?token={quote(token)}"

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 560px; margin: 0 auto; padding: 32px;">
        <h2 style="color: #111827; margin-bottom: 16px;">Reset your password</h2>
        <p style="color: #374151; font-size: 16px; line-height: 1.6;">
            We received a request to reset your <strong>JobOS</strong> password.
            Click the button below to choose a new one.
        </p>
        <div style="text-align: center; margin: 32px 0;">
            <a href="{reset_url}"
               style="background-color: #2563eb; color: #ffffff; padding: 12px 32px;
                      border-radius: 6px; text-decoration: none; font-weight: 600;
                      display: inline-block;">
                Reset Password
            </a>
        </div>
        <p style="color: #6b7280; font-size: 14px; line-height: 1.5;">
            If the button doesn't work, copy and paste this link into your browser:
        </p>
        <p style="color: #6b7280; font-size: 14px; word-break: break-all;">
            {reset_url}
        </p>
        <p style="color: #dc2626; font-size: 14px; font-weight: 600; margin-top: 16px;">
            This link expires in 1 hour.
        </p>
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;" />
        <p style="color: #9ca3af; font-size: 12px;">
            If you didn't request a password reset, you can safely ignore this email.
            Your password will remain unchanged.
        </p>
    </div>
    """

    try:
        resend.Emails.send(
            {
                "from": settings.email_from,
                "to": [to_email],
                "subject": "Reset your JobOS password",
                "html": html,
            }
        )
        logger.info("Password reset email sent to %s", to_email)
        return True
    except Exception as e:
        logger.error("Failed to send password reset email to %s: %s", to_email, e)
        return False

