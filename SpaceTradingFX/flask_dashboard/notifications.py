"""
Notification Service for SpaceTradingFX
Handles in-app notifications and email alerts
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from .extensions import db
from .models import Notification, User, utcnow

logger = logging.getLogger(__name__)

# Email configuration
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "noreply@spacetradingfx.com")
FROM_NAME = os.environ.get("FROM_NAME", "SpaceTradingFX")


def create_notification(
    user_id: str, title: str, message: str, notification_type: str, data: dict | None = None
) -> Notification:
    """Create an in-app notification for a user"""
    try:
        notification = Notification(
            user_id=user_id, title=title, message=message, type=notification_type, data=data or {}, created_at=utcnow()
        )
        db.session.add(notification)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Failed to create in-app notification for user %s", user_id)
        raise

    # Also send email if user has email notifications enabled
    try:
        user = User.query.get(user_id)
        if user and user.email_notifications and user.email:
            send_email_notification(user.email, title, message, notification_type)
    except Exception:
        logger.exception("Failed to dispatch email alert for user %s", user_id)

    return notification


def get_user_notifications(user_id: str, limit: int = 20, unread_only: bool = False):
    """Get notifications for a user"""
    query = Notification.query.filter_by(user_id=user_id)
    if unread_only:
        query = query.filter_by(is_read=False)
    return query.order_by(Notification.created_at.desc()).limit(limit).all()


def get_unread_count(user_id: str) -> int:
    """Get count of unread notifications"""
    return Notification.query.filter_by(user_id=user_id, is_read=False).count()


def mark_as_read(notification_id: int, user_id: str) -> bool:
    """Mark a notification as read"""
    notification = Notification.query.filter_by(id=notification_id, user_id=user_id).first()
    if notification:
        notification.is_read = True
        db.session.commit()
        return True
    return False


def mark_all_as_read(user_id: str) -> int:
    """Mark all notifications as read for a user"""
    count = Notification.query.filter_by(user_id=user_id, is_read=False).update({"is_read": True})
    db.session.commit()
    return count


def send_email_notification(to_email: str, subject: str, message: str, notification_type: str):
    """Send email notification"""
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("Email not configured. Skipping email notification.")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[SpaceTradingFX] {subject}"
        msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
        msg["To"] = to_email

        # Get icon based on type
        icons = {"trade": "📈", "signal": "🔔", "license": "🔑", "system": "⚙️", "referral": "👥"}
        icon = icons.get(notification_type, "📬")

        # Plain text version
        text = f"{icon} {subject}\n\n{message}\n\n---\nSpaceTradingFX Trading Platform"

        # HTML version
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #C84B61; color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .icon {{ font-size: 40px; margin-bottom: 10px; }}
                .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="icon">{icon}</div>
                    <h2>{subject}</h2>
                </div>
                <div class="content">
                    <p>{message}</p>
                </div>
                <div class="footer">
                    <p>SpaceTradingFX Trading Platform</p>
                    <p>You received this email because you enabled notifications.</p>
                </div>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, to_email, msg.as_string())

        logger.info("Email sent successfully", extra={"to_email": to_email, "subject": subject})
        return True

    except Exception:
        logger.exception("Failed to send email notification to recipient", extra={"to_email": to_email})
        return False


# Convenience functions for common notifications
def notify_trade_opened(user_id: str, currency_pair: str, trade_type: str, lot_size: float, entry_price: float):
    """Notify user about a new trade"""
    user = User.query.get(user_id)
    if user and user.trade_alerts:
        create_notification(
            user_id=user_id,
            title=f"{trade_type} Trade Opened",
            message=f"{currency_pair} {trade_type} opened at {entry_price} with {lot_size} lots",
            notification_type="trade",
            data={"currency_pair": currency_pair, "trade_type": trade_type},
        )


def notify_trade_closed(user_id: str, currency_pair: str, trade_type: str, profit_loss: float):
    """Notify user about a closed trade"""
    user = User.query.get(user_id)
    if user and user.trade_alerts:
        pl_text = f"+${profit_loss:.2f}" if profit_loss >= 0 else f"-${abs(profit_loss):.2f}"
        emoji = "🟢" if profit_loss >= 0 else "🔴"
        create_notification(
            user_id=user_id,
            title=f"{emoji} Trade Closed",
            message=f"{currency_pair} {trade_type} closed with {pl_text}",
            notification_type="trade",
            data={"currency_pair": currency_pair, "profit_loss": profit_loss},
        )


def notify_new_signal(user_id: str, currency_pair: str, signal_type: str, strength: float):
    """Notify user about a new trading signal"""
    user = User.query.get(user_id)
    if user and user.signal_alerts:
        emoji = "📈" if signal_type == "BUY" else "📉"
        create_notification(
            user_id=user_id,
            title=f"{emoji} New {signal_type} Signal",
            message=f"Strong {signal_type} signal detected for {currency_pair} (Strength: {strength:.0f}%)",
            notification_type="signal",
            data={"currency_pair": currency_pair, "signal_type": signal_type, "strength": strength},
        )


def notify_license_expiring(user_id: str, days_left: int):
    """Notify user about expiring license"""
    create_notification(
        user_id=user_id,
        title="⚠️ License Expiring Soon",
        message=f"Your license will expire in {days_left} days. Renew now to continue trading.",
        notification_type="license",
        data={"days_left": days_left},
    )


def notify_license_expired(user_id: str):
    """Notify user about expired license"""
    create_notification(
        user_id=user_id,
        title="🔒 License Expired",
        message="Your license has expired. Please renew to continue using trading features.",
        notification_type="license",
    )


def notify_new_referral(mentor_user_id: str, referred_email: str):
    """Notify mentor about a new referral"""
    create_notification(
        user_id=mentor_user_id,
        title="👥 New Referral!",
        message=f"A new user ({referred_email}) signed up using your mentor ID!",
        notification_type="referral",
        data={"referred_email": referred_email},
    )


def notify_commission_earned(mentor_user_id: str, amount: Any, referred_email: str):
    """Notify mentor about earned commission"""
    amt = float(amount)
    create_notification(
        user_id=mentor_user_id,
        title="💰 Commission Earned!",
        message=f"You earned ${amt:.2f} commission from {referred_email}'s license purchase!",
        notification_type="referral",
        data={"amount": str(amount), "referred_email": referred_email},
    )
