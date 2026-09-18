from datetime import date
import models


def get_current_user(request):
    return request.cookies.get("user")


def sync_recurring_payments(db):

    today = date.today()

    payments = (
        db.query(models.Payment)
        .filter(models.Payment.recurring == True)
        .all()
    )

    for payment in payments:

        existing = (
            db.query(models.Expense)
            .filter(
                models.Expense.name == payment.name,
                models.Expense.date == today
            )
            .first()
        )

        if existing:
            continue

        if payment.due_date.day == today.day:

            expense = models.Expense(
                name=payment.name,
                amount=payment.amount,
                date=today,
                person_id=payment.person_id,
                category_id=payment.category_id,
                notes=f"Auto-created from recurring payment: {payment.notes or ''}"
            )

            db.add(expense)

    db.commit()