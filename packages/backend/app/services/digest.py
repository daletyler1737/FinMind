"""Weekly financial digest service."""
from datetime import date, timedelta
from sqlalchemy import extract, func
from ..extensions import db
from ..models import Expense, Category
import logging

logger = logging.getLogger("finmind.digest")


def get_week_range(d: date | None = None) -> tuple[date, date]:
    """Get Monday-Sunday range for the given date (default: today)."""
    d = d or date.today()
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def previous_week_range(monday: date) -> tuple[date, date]:
    """Get Monday-Sunday range for the week before."""
    prev_monday = monday - timedelta(days=7)
    return prev_monday, prev_monday + timedelta(days=6)


def _spend_in_range(uid: int, start: date, end: date) -> float:
    result = (
        db.session.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(
            Expense.user_id == uid,
            Expense.spent_at >= start,
            Expense.spent_at <= end,
            Expense.expense_type != "INCOME",
        )
        .scalar()
    )
    return float(result)


def _income_in_range(uid: int, start: date, end: date) -> float:
    result = (
        db.session.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(
            Expense.user_id == uid,
            Expense.spent_at >= start,
            Expense.spent_at <= end,
            Expense.expense_type == "INCOME",
        )
        .scalar()
    )
    return float(result)


def _category_breakdown(uid: int, start: date, end: date) -> dict:
    rows = (
        db.session.query(
            Expense.category_id, func.coalesce(func.sum(Expense.amount), 0)
        )
        .filter(
            Expense.user_id == uid,
            Expense.spent_at >= start,
            Expense.spent_at <= end,
            Expense.expense_type != "INCOME",
        )
        .group_by(Expense.category_id)
        .all()
    )
    # Resolve category names
    categories = {c.id: c.name for c in Category.query.filter_by(user_id=uid).all()}
    result = {}
    for cat_id, amount in rows:
        name = categories.get(cat_id, "Uncategorized")
        result[name] = round(float(amount), 2)
    return result


def _top_spending(breakdown: dict, n: int = 3) -> list[dict]:
    """Return top N spending categories."""
    sorted_items = sorted(breakdown.items(), key=lambda x: x[1], reverse=True)
    return [{"category": k, "amount": v} for k, v in sorted_items[:n]]


def generate_weekly_digest(uid: int, target_date: date | None = None) -> dict:
    """Generate a weekly financial digest for the given user."""
    monday, sunday = get_week_range(target_date)
    prev_monday, prev_sunday = previous_week_range(monday)

    spend = _spend_in_range(uid, monday, sunday)
    income = _income_in_range(uid, monday, sunday)
    prev_spend = _spend_in_range(uid, prev_monday, prev_sunday)
    breakdown = _category_breakdown(uid, monday, sunday)
    transaction_count = (
        Expense.query.filter(
            Expense.user_id == uid,
            Expense.spent_at >= monday,
            Expense.spent_at <= sunday,
        ).count()
    )

    # Calculate change vs previous week
    spend_change = None
    spend_change_pct = None
    if prev_spend > 0:
        spend_change = round(spend - prev_spend, 2)
        spend_change_pct = round(((spend - prev_spend) / prev_spend) * 100, 1)

    # Generate insights
    insights = []
    if spend > income:
        insights.append("Spending exceeded income this week — review non-essential expenses.")
    elif income > 0 and spend / income < 0.5:
        insights.append("Good savings rate! You spent less than 50% of your income.")
    if spend_change_pct and abs(spend_change_pct) > 20:
        direction = "increased" if spend_change_pct > 0 else "decreased"
        insights.append(f"Spending {direction} significantly ({abs(spend_change_pct)}%) compared to last week.")

    return {
        "week_range": {
            "start": monday.isoformat(),
            "end": sunday.isoformat(),
        },
        "summary": {
            "total_spent": round(spend, 2),
            "total_income": round(income, 2),
            "transaction_count": transaction_count,
            "category_breakdown": breakdown,
            "top_spending": _top_spending(breakdown),
        },
        "comparison": {
            "previous_week_spent": round(prev_spend, 2),
            "change": spend_change,
            "change_pct": spend_change_pct,
        },
        "insights": insights,
    }
