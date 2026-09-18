from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import joinedload

import models
from database import SessionLocal
from utils import get_current_user, sync_recurring_payments
from app_config import templates
from datetime import date, timedelta
import calendar

router = APIRouter()

@router.get("/", response_class=HTMLResponse)

async def home(request: Request):

    username = get_current_user(request)

    if not username:
        return RedirectResponse("/login", status_code=303)

    db = SessionLocal()

    sync_recurring_payments(db)

    expenses = (
        db.query(models.Expense)
        .options(joinedload(models.Expense.category))
        .all()
    )

    incomes = db.query(models.Income).all()
    categories = db.query(models.Category).all()

    total_expenses = sum(e.amount for e in expenses)
    total_income = sum(i.amount for i in incomes)
    balance_setting = db.query(models.Setting).filter(
    models.Setting.key == "starting_balance"
    ).first()

    starting_balance = float(balance_setting.value) if balance_setting else 0

    current_balance = starting_balance + total_income - total_expenses
    income_count = len(incomes)
    average_expense = total_expenses / len(expenses) if expenses else 0


    today = date.today()
    days_in_month = calendar.monthrange(today.year, today.month)[1]

    daily_average = total_expenses / days_in_month if days_in_month else 0

    biggest_expense = max(expenses, key=lambda e: e.amount) if expenses else None

    transactions_this_month = len(expenses) + len(incomes)

    savings_rate = (
        (current_balance / total_income) * 100
        if total_income > 0 else 0
    )   

    budget_data = []

    for category in categories:

        spent = sum(
            e.amount
            for e in expenses
            if e.category_id == category.id
        )

        budget_amount = category.budget or 0

        percent = (spent / budget_amount * 100) if budget_amount > 0 else 0
        remaining = budget_amount - spent
        over_budget = budget_amount > 0 and spent > budget_amount

        if budget_amount == 0:
            color = "gray"
        elif percent < 80:
            color = "green"
        elif percent < 100:
            color = "orange"
        else:
            color = "red"

        budget_data.append({
            "name": category.name,
            "budget": budget_amount,
            "spent": spent,
            "percent": min(percent, 100),
            "remaining": remaining,
            "over_budget": over_budget,
            "color": color
        })

    category_totals = {}

    for expense in expenses:
        category_name = expense.category.name if expense.category else "Other"
        category_totals[category_name] = (
            category_totals.get(category_name, 0)
            + expense.amount
        )

        category_labels = list(category_totals.keys())
    category_values = list(category_totals.values())

    if not category_labels:
        category_labels = ["No expenses yet"]
        category_values = [1]

    # Next payment countdown
    today = date.today()

    upcoming_payments = (
        db.query(models.Payment)
        .filter(models.Payment.due_date >= today)
        .order_by(models.Payment.due_date)
        .limit(5)
        .all()
    )

    for payment in upcoming_payments:
        payment.days_left = (payment.due_date - today).days

    db.close()
    
    shopping_items = (
    db.query(models.ShoppingItem)
    .filter(models.ShoppingItem.completed == False)
    .order_by(models.ShoppingItem.id.desc())
    .limit(5)
    .all()
    )
    
    from collections import defaultdict

    today = date.today()

    # ---------- D (Today) ----------
    day_data = defaultdict(float)

    for e in expenses:
        if e.date == today:
            day_data["Today"] += e.amount

    trend_day_labels = list(day_data.keys()) or ["Today"]
    trend_day_values = [day_data[k] for k in trend_day_labels] or [0]

    # ---------- W (Last 7 days) ----------
    week_data = defaultdict(float)

    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        week_data[d.strftime("%a")] = 0

    for e in expenses:
        if today - timedelta(days=6) <= e.date <= today:
            week_data[e.date.strftime("%a")] += e.amount

    trend_week_labels = list(week_data.keys())
    trend_week_values = list(week_data.values())

    # ---------- M (Last 30 days) ----------
    month_data = defaultdict(float)

    for i in range(29, -1, -1):
        d = today - timedelta(days=i)
        month_data[d.strftime("%d %b")] = 0

    for e in expenses:
        if today - timedelta(days=29) <= e.date <= today:
            month_data[e.date.strftime("%d %b")] += e.amount

    trend_month_labels = list(month_data.keys())
    trend_month_values = list(month_data.values())

    # ---------- 3 Months ----------
    m3_data = defaultdict(float)

    for e in expenses:
        if e.date >= today - timedelta(days=90):
            m3_data[e.date.strftime("%b")] += e.amount

    trend_3m_labels = list(m3_data.keys())
    trend_3m_values = list(m3_data.values())

    # ---------- 6 Months ----------
    m6_data = defaultdict(float)

    for e in expenses:
        if e.date >= today - timedelta(days=180):
            m6_data[e.date.strftime("%b")] += e.amount

    trend_6m_labels = list(m6_data.keys())
    trend_6m_values = list(m6_data.values())

    # ---------- Y (This Year) ----------
    year_data = defaultdict(float)

    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

    for m in months:
        year_data[m] = 0

    for e in expenses:
        if e.date.year == today.year:
            year_data[e.date.strftime("%b")] += e.amount

    trend_year_labels = list(year_data.keys())
    trend_year_values = list(year_data.values())

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": username,
            "expenses": expenses,
            "total_expenses": total_expenses,
            "total_income": total_income,
            "current_balance": current_balance,
            "starting_balance": starting_balance,
            "income_count": income_count,
            "average_expense": average_expense,
            "daily_average": daily_average,
            "biggest_expense": biggest_expense,
            "transactions_this_month": transactions_this_month,
            "savings_rate": savings_rate,
            "budget_data": budget_data,
            "category_labels": category_labels,
            "category_values": category_values,
            "shopping_items": shopping_items,
            "upcoming_payments": upcoming_payments,

            "trend_day_labels": trend_day_labels,
            "trend_day_values": trend_day_values,

            "trend_week_labels": trend_week_labels,
            "trend_week_values": trend_week_values,

            "trend_month_labels": trend_month_labels,
            "trend_month_values": trend_month_values,

            "trend_3m_labels": trend_3m_labels,
            "trend_3m_values": trend_3m_values,

            "trend_6m_labels": trend_6m_labels,
            "trend_6m_values": trend_6m_values,

            "trend_year_labels": trend_year_labels,
            "trend_year_values": trend_year_values
        }
    )