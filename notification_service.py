"""Push notification helpers for the Home Manager web app (Web Push)."""

import json
import os
from datetime import date, timedelta

from pywebpush import WebPushException, webpush

import models


def is_configured():
    return bool(os.getenv("VAPID_PRIVATE_KEY") and os.getenv("VAPID_PUBLIC_KEY"))


def _send(subscription, title, body, url="/"):
    if not is_configured():
        return False

    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps({"title": title, "body": body, "url": url}),
            vapid_private_key=os.environ["VAPID_PRIVATE_KEY"],
            vapid_claims={
                "sub": os.getenv("VAPID_SUBJECT", "mailto:home-manager@example.com")
            },
        )
        return True
    except WebPushException as error:
        # Expired/invalid subscriptions must not prevent the rest from receiving a push.
        if error.response is not None and error.response.status_code in (404, 410):
            return "expired"
        return False


def send_push(db, title, body, url="/", exclude_username=None):
    """Send a notification to all subscribed household devices."""
    subscriptions = db.query(models.PushSubscription).all()

    for subscription in subscriptions:
        if exclude_username and subscription.username == exclude_username:
            continue

        result = _send(subscription, title, body, url)
        if result == "expired":
            db.delete(subscription)

    db.commit()


def send_due_payment_notifications(db):
    """Send each due-date reminder once, for payments due in one or three days."""
    if not is_configured():
        return

    today = date.today()

    for days_left in (3, 1):
        due_date = today + timedelta(days=days_left)
        payments = db.query(models.Payment).filter(
            models.Payment.due_date == due_date
        ).all()

        for payment in payments:
            event_key = f"payment:{payment.id}:{due_date.isoformat()}:{days_left}"
            already_sent = db.query(models.NotificationLog).filter(
                models.NotificationLog.event_key == event_key
            ).first()

            if already_sent:
                continue

            day_label = "tomorrow" if days_left == 1 else "in 3 days"
            send_push(
                db,
                "Upcoming payment",
                f"{payment.name}: {payment.amount:.0f} kr is due {day_label}.",
                "/payments",
            )
            db.add(models.NotificationLog(event_key=event_key))
            db.commit()
