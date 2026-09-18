from datetime import date
from routes.dashboard import router as dashboard_router
import os

from fastapi import FastAPI, Header, HTTPException, Request, Form, Depends
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from app_config import templates
from sqlalchemy.orm import joinedload
from routes.shopping import router as shopping_router


from database import engine, Base, SessionLocal
import models
from notification_service import (
    is_configured,
    send_due_payment_notifications,
    send_push,
)

from fastapi import Response
from jose import jwt, JWTError
from passlib.context import CryptContext


SECRET_KEY = "fanni-istvan-home-manager-secret"
ALGORITHM = "HS256"

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

USERS = {
    "Fanni": pwd_context.hash("1234"),
    "Istvan": pwd_context.hash("1234")
}

# ----------------------
# Adatbázis létrehozása
# ----------------------

from sqlalchemy import text

with engine.connect() as conn:
    try:
        conn.execute(text("DROP TABLE shopping_items"))
        conn.commit()
    except Exception:
        pass

with engine.connect() as conn:
    # Category budget oszlop
    try:
        conn.execute(text("ALTER TABLE categories ADD COLUMN budget FLOAT DEFAULT 0"))
        conn.commit()
    except Exception:
        pass

    # Settings tábla
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE,
            value TEXT
        )
    """))
    conn.commit()

Base.metadata.create_all(bind=engine)


# ----------------------
# Kezdeti adatok
# ----------------------

db = SessionLocal()

# Ha nincs még ember az adatbázisban
if db.query(models.Person).count() == 0:
    db.add_all([
        models.Person(name="István"),
        models.Person(name="Fanni"),
        models.Person(name="Közös")
    ])

# Ha még régi "Girlfriend" van, átnevezzük
girlfriend = db.query(models.Person).filter(
    models.Person.name == "Girlfriend"
).first()

if girlfriend:
    girlfriend.name = "Fanni"

# Ha nincs Közös, hozzáadjuk
if not db.query(models.Person).filter(
    models.Person.name == "Közös"
).first():
    db.add(models.Person(name="Közös"))

# Kategóriák
if db.query(models.Category).count() == 0:
    db.add_all([
    models.Category(name="Housing", type="expense", monthly_budget=5900),
    models.Category(name="Internet", type="expense", monthly_budget=349),
    models.Category(name="Food", type="expense", monthly_budget=2500),
    models.Category(name="Transport", type="expense", monthly_budget=800),
    models.Category(name="Other", type="expense", monthly_budget=1000)
    ])

db.commit()
db.close()


# ----------------------
# FastAPI
# ----------------------

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(dashboard_router)
app.include_router(shopping_router)

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static"
)


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript")


@app.post("/notifications/subscribe", include_in_schema=False)
async def subscribe_to_notifications(request: Request):
    username = get_current_user(request)
    if not username:
        raise HTTPException(status_code=401, detail="Please sign in first.")

    if not is_configured():
        raise HTTPException(status_code=503, detail="Notifications are not configured yet.")

    subscription = await request.json()
    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys", {})
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not endpoint or not p256dh or not auth:
        raise HTTPException(status_code=400, detail="Invalid push subscription.")

    db = SessionLocal()
    saved_subscription = db.query(models.PushSubscription).filter(
        models.PushSubscription.endpoint == endpoint
    ).first()

    if saved_subscription:
        saved_subscription.username = username
        saved_subscription.p256dh = p256dh
        saved_subscription.auth = auth
    else:
        db.add(models.PushSubscription(
            username=username,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
        ))

    db.commit()
    db.close()
    return {"ok": True}


@app.post("/notifications/check-due", include_in_schema=False)
async def check_due_notifications(x_notification_cron_token: str | None = Header(default=None)):
    cron_token = os.getenv("NOTIFICATION_CRON_TOKEN")
    if not cron_token or x_notification_cron_token != cron_token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    db = SessionLocal()
    send_due_payment_notifications(db)
    db.close()
    return {"ok": True}


def create_default_users():

    db = SessionLocal()

    if db.query(models.User).count() == 0:

        users = [
            ("Fanni", "Fanni123!"),
            ("István", "Istvan123!")
        ]

        for username, password in users:

            db.add(
                models.User(
                    username=username,
                    password_hash=pwd_context.hash(password)
                )
            )

        db.commit()

    db.close()


create_default_users()


from datetime import datetime, timedelta

def create_token(username):
    payload = {
        "sub": username,
        "exp": datetime.utcnow() + timedelta(days=30)
    }

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM
    )


def get_current_user(request: Request):
    token = request.cookies.get("token")

    if not token:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None

# ----------------------
# Dashboard
# ----------------------
def sync_recurring_payments(db):

    today = date.today()

    payments = db.query(models.Payment).all()

    for payment in payments:

        # ugyanazon hónap adott napján ismétlődik
        if payment.due_date.day != today.day:
            continue

        already_exists = db.query(models.Expense).filter(
            models.Expense.name == payment.name,
            models.Expense.amount == payment.amount,
            models.Expense.person_id == payment.person_id,
            models.Expense.date == today
        ).first()

        if already_exists:
            continue

        expense = models.Expense(
            name=payment.name,
            amount=payment.amount,
            person_id=payment.person_id,
            category_id=payment.category_id,
            date=today,
            notes=f"Auto-generated from recurring payment"
        )

        db.add(expense)

    db.commit()



# ----------------------
# Add Expense
# ----------------------

@app.post("/expenses/add")
async def add_expense(
    name: str = Form(...),
    amount: float = Form(...),
    person_id: int = Form(...),
    category_id: int = Form(...),
    expense_date: str = Form(...),
    notes: str = Form("")
):

    db = SessionLocal()

    expense = models.Expense(
        name=name,
        amount=amount,
        person_id=person_id,
        category_id=category_id,
        date=date.fromisoformat(expense_date),
        notes=notes
    )

    db.add(expense)
    db.commit()
    db.close()

    return RedirectResponse("/money", status_code=303)


# ----------------------
# Edit Expense oldal
# ----------------------

@app.get("/expenses/edit/{expense_id}", response_class=HTMLResponse)
async def edit_expense_page(
    request: Request,
    expense_id: int
):

    db = SessionLocal()

    expense = (
        db.query(models.Expense)
        .options(joinedload(models.Expense.person))
        .filter(models.Expense.id == expense_id)
        .first()
    )

    people = db.query(models.Person).all()
    categories = db.query(models.Category).all()

    db.close()

    return templates.TemplateResponse(
        request=request,
        name="edit_expense.html",
        context={
            "expense": expense,
            "people": people,
            "categories": categories
        }
    )


# ----------------------
# Edit Expense mentése
# ----------------------

@app.post("/expenses/edit/{expense_id}")
async def edit_expense(
    expense_id: int,
    name: str = Form(...),
    amount: float = Form(...),
    person_id: int = Form(...),
    category_id: int = Form(...),
    expense_date: str = Form(...),
    notes: str = Form("")
):

    db = SessionLocal()

    expense = db.query(models.Expense).filter(
        models.Expense.id == expense_id
    ).first()

    if expense:
        expense.name = name
        expense.amount = amount
        expense.person_id = person_id
        expense.category_id = category_id
        expense.date = date.fromisoformat(expense_date)
        expense.notes = notes

        db.commit()

    db.close()

    return RedirectResponse("/money", status_code=303)


# ----------------------
# Delete Expense
# ----------------------

@app.post("/expenses/delete/{expense_id}")
async def delete_expense(expense_id: int):

    db = SessionLocal()

    expense = db.query(models.Expense).filter(
        models.Expense.id == expense_id
    ).first()

    if expense:
        db.delete(expense)
        db.commit()

    db.close()

    return RedirectResponse(url="/", status_code=303)


# ----------------------
# Add Income
# ----------------------

@app.post("/income/add")
async def add_income(
    name: str = Form(...),
    amount: float = Form(...),
    person_id: int = Form(...),
    income_date: str = Form(...),
    notes: str = Form("")
):

    db = SessionLocal()

    income = models.Income(
        name=name,
        amount=amount,
        person_id=person_id,
        date=date.fromisoformat(income_date),
        notes=notes
    )

    db.add(income)
    db.commit()
    db.close()

    return RedirectResponse("/money", status_code=303)


# ----------------------
# Money oldal
# ----------------------

@app.get("/money", response_class=HTMLResponse)
async def money(request: Request):

    username = get_current_user(request)

    if not username:
        return RedirectResponse("/login", status_code=303)

    db = SessionLocal()
    sync_recurring_payments(db)
    # Income-ok + Person
    incomes = (
        db.query(models.Income)
        .options(joinedload(models.Income.person))
        .all()
    )

    # Expense-ek + Person
    expenses = (
        db.query(models.Expense)
        .options(joinedload(models.Expense.person))
        .all()
    )

    people = db.query(models.Person).all()
    categories = db.query(models.Category).all()

    # ----------------------
    # Összesítések
    # ----------------------

    total_income = sum(i.amount for i in incomes)
    total_expenses = sum(e.amount for e in expenses)
    # Starting balance beolvasása
    balance_setting = db.query(models.Setting).filter(
    models.Setting.key == "starting_balance"
    ).first()

    starting_balance = float(balance_setting.value) if balance_setting else 0

    current_balance = starting_balance + total_income - total_expenses


    # ----------------------
    # Transactions
    # ----------------------

    transactions = []

    for income in incomes:
        transactions.append({
            "type": "income",
            "name": income.name,
            "amount": income.amount,
            "date": income.date,
            "person": income.person.name
        })

    for expense in expenses:
        transactions.append({
            "type": "expense",
            "name": expense.name,
            "amount": expense.amount,
            "date": expense.date,
            "person": expense.person.name
        })

    transactions.sort(
        key=lambda x: x["date"],
        reverse=True
    )

    db.close()

    return templates.TemplateResponse(
        request=request,
        name="money.html",
        context={
            "incomes": incomes,
            "expenses": expenses,
            "people": people,
            "categories": categories,

            "total_income": total_income,
            "total_expenses": total_expenses,
            "current_balance": current_balance,
            "starting_balance": starting_balance,
            "transactions": transactions,
        }
    )
@app.post("/income/delete/{income_id}")
async def delete_income(income_id: int):

    db = SessionLocal()

    income = db.query(models.Income).filter(
        models.Income.id == income_id
    ).first()

    if income:
        db.delete(income)
        db.commit()

    db.close()

    return RedirectResponse(url="/", status_code=303)


@app.get("/income/edit/{income_id}", response_class=HTMLResponse)
async def edit_income_page(request: Request, income_id: int):

        username = get_current_user(request)
        if not username:
            return RedirectResponse("/login", status_code=303)

        db = SessionLocal()

        income = db.query(models.Income).filter(
            models.Income.id == income_id
        ).first()

        people = db.query(models.Person).all()

        response = templates.TemplateResponse(
            request=request,
            name="edit_income.html",
            context={
                "income": income,
                "people": people
            }
        )

        db.close()

        return response


@app.post("/income/edit/{income_id}")
async def edit_income(
    income_id: int,
    name: str = Form(...),
    amount: float = Form(...),
    person_id: int = Form(...),
    income_date: str = Form(...),
    notes: str = Form("")
):

    db = SessionLocal()

    income = db.query(models.Income).filter(
        models.Income.id == income_id
    ).first()

    if income:

        income.name = name
        income.amount = amount
        income.person_id = person_id
        income.date = date.fromisoformat(income_date)
        income.notes = notes

        db.commit()

    db.close()

    return RedirectResponse("/money", status_code=303)

   # ----------------------
# Payments oldal
# ----------------------

@app.get("/payments", response_class=HTMLResponse)
async def payments(request: Request):

    username = get_current_user(request)

    if not username:
        return RedirectResponse("/login", status_code=303)

    db = SessionLocal()

    sync_recurring_payments(db)

    payments = (
        db.query(models.Payment)
        .options(joinedload(models.Payment.person))
        .options(joinedload(models.Payment.category))
        .order_by(models.Payment.due_date)
        .all()
    )

    people = db.query(models.Person).all()
    categories = db.query(models.Category).all()

    response = templates.TemplateResponse(
        request=request,
        name="payments.html",
        context={
            "payments": payments,
            "people": people,
            "categories": categories,
            "today": date.today()
        }
    )

    db.close()

    return response

@app.post("/payments/add")
async def add_payment(
    name: str = Form(...),
    amount: float = Form(...),
    person_id: int = Form(...),
    category_id: int = Form(...),
    due_date: str = Form(...),
    notes: str = Form("")
):

    db = SessionLocal()

    payment = models.Payment(
    name=name,
    amount=amount,
    person_id=person_id,
    category_id=category_id,
    due_date=date.fromisoformat(due_date),
    notes=notes
                            )

    db.add(payment)
    db.commit()
    db.close()

    return RedirectResponse(url="/payments", status_code=303)


@app.post("/payments/delete/{payment_id}")
async def delete_payment(payment_id: int):

    db = SessionLocal()

    payment = db.query(models.Payment).filter(
        models.Payment.id == payment_id
    ).first()

    if payment:
        db.delete(payment)
        db.commit()

    db.close()

    return RedirectResponse(url="/payments", status_code=303)

@app.get("/payments/edit/{payment_id}", response_class=HTMLResponse)
async def edit_payment_page(request: Request, payment_id: int):

    username = get_current_user(request)
    if not username:
        return RedirectResponse("/login", status_code=303)

    db = SessionLocal()

    payment = (
        db.query(models.Payment)
        .filter(models.Payment.id == payment_id)
        .first()
    )

    people = db.query(models.Person).all()
    categories = db.query(models.Category).all()

    response = templates.TemplateResponse(
        request=request,
        name="edit_payment.html",
        context={
            "payment": payment,
            "people": people,
            "categories": categories
        }
    )

    db.close()

    return response


@app.post("/payments/edit/{payment_id}")
async def edit_payment(
    payment_id: int,
    name: str = Form(...),
    amount: float = Form(...),
    person_id: int = Form(...),
    category_id: int = Form(...),
    due_date: str = Form(...),
    notes: str = Form("")
):

    db = SessionLocal()

    payment = db.query(models.Payment).filter(
        models.Payment.id == payment_id
    ).first()

    if payment:

        payment.name = name
        payment.amount = amount
        payment.person_id = person_id
        payment.category_id = category_id
        payment.due_date = date.fromisoformat(due_date)
        payment.notes = notes

        db.commit()

    db.close()

    return RedirectResponse("/payments", status_code=303)

# ----------------------
# Settings
# ----------------------

@app.get("/settings", response_class=HTMLResponse)
async def settings(request: Request):
    username = get_current_user(request)

    if not username:
        return RedirectResponse("/login", status_code=303)
    db = SessionLocal()

    categories = db.query(models.Category).all()
    categories = db.query(models.Category).order_by(models.Category.name).all()
    db.close()

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "categories": categories,
            "push_public_key": os.getenv("VAPID_PUBLIC_KEY", ""),
        }
    )

@app.post("/settings/balance")
async def save_starting_balance(
    request: Request,
    amount: float = Form(...),
    user=Depends(get_current_user)
):
    db = SessionLocal()

    setting = db.query(models.Setting).filter(
        models.Setting.key == "starting_balance"
    ).first()

    if setting:
        setting.value = str(amount)
    else:
        db.add(models.Setting(
            key="starting_balance",
            value=str(amount)
        ))

    db.commit()
    db.close()

    return RedirectResponse("/settings", status_code=303)

@app.post("/settings/budgets")
async def save_budgets(request: Request):

    form = await request.form()

    db = SessionLocal()

    categories = db.query(models.Category).all()

    for category in categories:

        key = f"budget_{category.id}"

        if key in form:
            category.monthly_budget = float(form[key])

    db.commit()
    db.close()

    return RedirectResponse("/settings", status_code=303)

@app.post("/settings/category/{category_id}")
async def update_category(
    category_id: int,
    name: str = Form(...),
    budget: float = Form(...),
    user=Depends(get_current_user)
):
    db = SessionLocal()

    category = db.query(models.Category).get(category_id)

    category.name = name
    category.budget = budget

    db.commit()
    db.close()

    return RedirectResponse("/settings", status_code=303)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    db = SessionLocal()
    users = db.query(models.User).all()
    db.close()

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"users": users}
    )


@app.post("/login")
async def login(
    username: str = Form(...),
    password: str = Form(...),
    remember_me: str = Form(None)
):
    if username not in USERS:
        return RedirectResponse("/login", status_code=303)

    if not pwd_context.verify(password, USERS[username]):
        return RedirectResponse("/login", status_code=303)

    token = create_token(username)

    response = RedirectResponse("/", status_code=303)

    response.set_cookie(
        key="token",
        value=token,
        httponly=True,
        secure=True,   # helyi fejlesztéshez
        samesite="lax",
        path="/",
        max_age=60*60*24*30 if remember_me else None
    )

    return response

@app.get("/logout")
async def logout():

    response = RedirectResponse("/login", status_code=303)

    response.delete_cookie("token")

    return response


# ----------------------------
# TODO PAGE
# ----------------------------

@app.get("/todo", response_class=HTMLResponse)
async def todo_page(request: Request):

    username = get_current_user(request)

    if not username:
        return RedirectResponse("/login", status_code=303)

    db = SessionLocal()

    todos = db.query(models.Todo).order_by(
        models.Todo.completed,
        models.Todo.due_date
    ).all()

    response = templates.TemplateResponse(
        request=request,
        name="todo.html",
        context={
            "todos": todos
        }
    )

    db.close()

    return response


@app.post("/todo/add")
async def add_todo(
    request: Request,
    task: str = Form(...),
    assigned_to: str = Form(...),
    due_date: str = Form("")
):

    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    db = SessionLocal()

    todo = models.Todo(
        task=task,
        assigned_to=assigned_to,
        due_date=date.fromisoformat(due_date) if due_date else None
    )

    db.add(todo)
    db.commit()
    send_push(
        db,
        "New to-do",
        f"{user} added: {task}",
        "/todo",
    )
    db.close()

    return RedirectResponse("/todo", status_code=303)


@app.post("/todo/toggle/{todo_id}")
async def toggle_todo(todo_id: int):

    db = SessionLocal()

    todo = db.query(models.Todo).filter(
        models.Todo.id == todo_id
    ).first()

    if todo:
        todo.completed = not todo.completed
        db.commit()

    db.close()

    return RedirectResponse("/todo", status_code=303)


@app.post("/todo/delete/{todo_id}")
async def delete_todo(todo_id: int):

    db = SessionLocal()

    todo = db.query(models.Todo).filter(
        models.Todo.id == todo_id
    ).first()

    if todo:
        db.delete(todo)
        db.commit()

    db.close()

    return RedirectResponse("/todo", status_code=303)
