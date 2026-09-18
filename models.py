from datetime import date

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Date,
    Boolean,
    ForeignKey
)
from sqlalchemy.orm import relationship

from database import Base


class Person(Base):
    __tablename__ = "people"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    budget = Column(Float, default=0)

class Income(Base):
    __tablename__ = "income"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=False)

    person_id = Column(Integer, ForeignKey("people.id"))

    date = Column(Date, nullable=False)
    notes = Column(String)

    person = relationship("Person")


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=False)

    person_id = Column(Integer, ForeignKey("people.id"))
    category_id = Column(Integer, ForeignKey("categories.id"))

    date = Column(Date, nullable=False)
    notes = Column(String)

    person = relationship("Person")
    category = relationship("Category")


class UtilityReading(Base):
    __tablename__ = "utility_readings"

    id = Column(Integer, primary_key=True, index=True)
    utility_type = Column(String, nullable=False)
    value = Column(Float, nullable=False)
    date = Column(Date, nullable=False)
    notes = Column(String)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=False)

    due_date = Column(Date, nullable=False)

    recurring = Column(Integer, default=1)

    person_id = Column(Integer, ForeignKey("people.id"))
    category_id = Column(Integer, ForeignKey("categories.id"))

    notes = Column(String)

    person = relationship("Person")
    category = relationship("Category")

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    username = Column(String, unique=True, nullable=False)

    password_hash = Column(String, nullable=False)

class Todo(Base):
    __tablename__ = "todos"

    id = Column(Integer, primary_key=True, index=True)

    task = Column(String, nullable=False)

    assigned_to = Column(String, default="Shared")

    due_date = Column(Date, nullable=True)

    completed = Column(Boolean, default=False)

    created_at = Column(Date, default=date.today)

class ShoppingItem(Base):
    __tablename__ = "shopping_items"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    added_by = Column(String, nullable=False)
    completed = Column(Boolean, default=False)
    created_at = Column(Date, default=date.today)

class Setting(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(String, nullable=False)