import calendar as cal_module
import os
from datetime import date, datetime

from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session
from models import (
    db,
    Course,
    Assignment,
    STATUS_CHOICES,
    Application,
    APPLICATION_STATUS_CHOICES,
    Transaction,
    TRANSACTION_TYPES,
    TRANSACTION_CATEGORIES,
    Todo,
)
import syllabus

load_dotenv()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///dashboard.db"
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-secret-for-local-use")
db.init_app(app)

with app.app_context():
    db.create_all()


def get_month_calendar(year, month):
    """Aggregate events from every module into one month's calendar grid."""
    weeks = cal_module.Calendar(firstweekday=6).monthdayscalendar(year, month)
    days_in_month = cal_module.monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year, month, days_in_month)

    events_by_day = {}

    assignments = Assignment.query.filter(Assignment.due_date >= start, Assignment.due_date <= end).all()
    for a in assignments:
        events_by_day.setdefault(a.due_date.day, []).append(
            {
                "title": f"{a.name} — {a.course.name}",
                "category": "academic",
                "url": url_for("course_detail", course_id=a.course_id),
            }
        )

    followups = Application.query.filter(
        Application.follow_up_date >= start, Application.follow_up_date <= end
    ).all()
    for a in followups:
        events_by_day.setdefault(a.follow_up_date.day, []).append(
            {
                "title": f"Follow up: {a.company}",
                "category": "professional",
                "url": url_for("application_detail", application_id=a.id),
            }
        )

    bills = Transaction.query.filter(
        Transaction.is_recurring.is_(True), Transaction.date >= start, Transaction.date <= end
    ).all()
    for t in bills:
        events_by_day.setdefault(t.date.day, []).append(
            {
                "title": t.description,
                "category": "financial",
                "url": url_for("budget", year=year, month=month),
            }
        )

    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    next_month, next_year = (1, year + 1) if month == 12 else (month + 1, year)

    return {
        "weeks": weeks,
        "events_by_day": events_by_day,
        "month_name": cal_module.month_name[month],
        "year": year,
        "month": month,
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
    }


@app.route("/")
def home():
    today = date.today()
    courses = Course.query.all()
    upcoming_assignments = (
        Assignment.query.filter(Assignment.due_date >= today)
        .order_by(Assignment.due_date)
        .limit(5)
        .all()
    )
    recent_applications = Application.query.order_by(Application.date_applied.desc()).limit(5).all()
    active_applications = Application.query.filter(
        Application.status.notin_(["Rejected", "Closed"])
    ).count()
    todos = Todo.query.order_by(Todo.created_at).all()
    month_ctx = get_month_calendar(today.year, today.month)
    return render_template(
        "home.html",
        name="AvaLucia",
        today=today,
        courses=courses,
        upcoming_assignments=upcoming_assignments,
        recent_applications=recent_applications,
        active_applications=active_applications,
        todos=todos,
        **month_ctx,
    )


@app.route("/classes")
def classes():
    courses = Course.query.all()
    return render_template("classes.html", courses=courses)


@app.route("/classes/new", methods=["GET", "POST"])
def new_class():
    if request.method == "POST":
        course = Course(
            name=request.form["name"],
            professor=request.form.get("professor"),
            credit_hours=request.form.get("credit_hours") or None,
            term=request.form.get("term"),
        )
        db.session.add(course)
        db.session.commit()
        return redirect(url_for("classes"))
    return render_template("new_class.html")


@app.route("/classes/<int:course_id>")
def course_detail(course_id):
    course = Course.query.get_or_404(course_id)
    return render_template("course_detail.html", course=course)


@app.route("/classes/<int:course_id>/assignments/new", methods=["GET", "POST"])
def new_assignment(course_id):
    course = Course.query.get_or_404(course_id)
    if request.method == "POST":
        due_date_raw = request.form.get("due_date")
        weight_raw = request.form.get("weight")
        grade_raw = request.form.get("grade")
        assignment = Assignment(
            course_id=course.id,
            name=request.form["name"],
            due_date=datetime.strptime(due_date_raw, "%Y-%m-%d").date() if due_date_raw else None,
            weight=float(weight_raw) if weight_raw else None,
            status=request.form.get("status") or "Not started",
            grade=float(grade_raw) if grade_raw else None,
        )
        db.session.add(assignment)
        db.session.commit()
        return redirect(url_for("course_detail", course_id=course.id))
    return render_template("new_assignment.html", course=course, status_choices=STATUS_CHOICES)


@app.route("/classes/<int:course_id>/syllabus/upload", methods=["GET", "POST"])
def upload_syllabus(course_id):
    course = Course.query.get_or_404(course_id)
    if request.method == "POST":
        file = request.files.get("syllabus")
        if not file or not file.filename:
            return render_template("upload_syllabus.html", course=course, error="Please choose a file.")
        try:
            text = syllabus.extract_text(file)
            if not text.strip():
                raise ValueError("Couldn't find any text in that file — is it a scanned image?")
            items = syllabus.extract_assignments(text)
        except Exception as exc:
            return render_template("upload_syllabus.html", course=course, error=str(exc))

        session["syllabus_course_id"] = course.id
        session["syllabus_items"] = items
        return redirect(url_for("review_syllabus", course_id=course.id))
    return render_template("upload_syllabus.html", course=course, error=None)


@app.route("/classes/<int:course_id>/syllabus/review", methods=["GET", "POST"])
def review_syllabus(course_id):
    course = Course.query.get_or_404(course_id)
    items = session.get("syllabus_items")
    if session.get("syllabus_course_id") != course.id or not items:
        return redirect(url_for("upload_syllabus", course_id=course.id))

    if request.method == "POST":
        added = 0
        for i in range(len(items)):
            if not request.form.get(f"include_{i}"):
                continue
            name = request.form.get(f"name_{i}", "").strip()
            if not name:
                continue
            due_date_raw = request.form.get(f"due_date_{i}")
            weight_raw = request.form.get(f"weight_{i}")
            db.session.add(
                Assignment(
                    course_id=course.id,
                    name=name,
                    due_date=datetime.strptime(due_date_raw, "%Y-%m-%d").date() if due_date_raw else None,
                    weight=float(weight_raw) if weight_raw else None,
                    status="Not started",
                )
            )
            added += 1
        db.session.commit()
        session.pop("syllabus_items", None)
        session.pop("syllabus_course_id", None)
        return redirect(url_for("course_detail", course_id=course.id))

    return render_template("review_syllabus.html", course=course, items=list(enumerate(items)))


@app.route("/calendar")
def calendar_view():
    today = date.today()
    year = request.args.get("year", type=int) or today.year
    month = request.args.get("month", type=int) or today.month
    month_ctx = get_month_calendar(year, month)
    return render_template("calendar.html", today=today, **month_ctx)


@app.route("/applications")
def applications():
    status_filter = request.args.get("status")
    query = Application.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    apps = query.order_by(Application.date_applied.desc()).all()
    return render_template(
        "applications.html",
        applications=apps,
        status_choices=APPLICATION_STATUS_CHOICES,
        status_filter=status_filter,
    )


@app.route("/applications/new", methods=["GET", "POST"])
def new_application():
    if request.method == "POST":
        date_applied_raw = request.form.get("date_applied")
        follow_up_raw = request.form.get("follow_up_date")
        application = Application(
            company=request.form["company"],
            role=request.form["role"],
            date_applied=datetime.strptime(date_applied_raw, "%Y-%m-%d").date() if date_applied_raw else None,
            source=request.form.get("source"),
            status=request.form.get("status") or "Applied",
            follow_up_date=datetime.strptime(follow_up_raw, "%Y-%m-%d").date() if follow_up_raw else None,
            notes=request.form.get("notes"),
        )
        db.session.add(application)
        db.session.commit()
        return redirect(url_for("applications"))
    return render_template("new_application.html", status_choices=APPLICATION_STATUS_CHOICES)


@app.route("/applications/<int:application_id>", methods=["GET", "POST"])
def application_detail(application_id):
    application = Application.query.get_or_404(application_id)
    if request.method == "POST":
        follow_up_raw = request.form.get("follow_up_date")
        application.status = request.form.get("status") or application.status
        application.notes = request.form.get("notes")
        application.follow_up_date = datetime.strptime(follow_up_raw, "%Y-%m-%d").date() if follow_up_raw else None
        db.session.commit()
        return redirect(url_for("application_detail", application_id=application.id))
    return render_template("application_detail.html", application=application, status_choices=APPLICATION_STATUS_CHOICES)


@app.route("/budget", methods=["GET", "POST"])
def budget():
    if request.method == "POST":
        transaction = Transaction(
            description=request.form["description"],
            amount=float(request.form["amount"]),
            type=request.form.get("type") or "Expense",
            category=request.form.get("category") or "Other",
            date=datetime.strptime(request.form["date"], "%Y-%m-%d").date(),
            is_recurring=bool(request.form.get("is_recurring")),
        )
        db.session.add(transaction)
        db.session.commit()
        return redirect(url_for("budget", year=transaction.date.year, month=transaction.date.month))

    today = date.today()
    year = request.args.get("year", type=int) or today.year
    month = request.args.get("month", type=int) or today.month
    days_in_month = cal_module.monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year, month, days_in_month)

    transactions = (
        Transaction.query.filter(Transaction.date >= start, Transaction.date <= end)
        .order_by(Transaction.date.desc())
        .all()
    )
    income_total = sum(t.amount for t in transactions if t.type == "Income")
    expense_total = sum(t.amount for t in transactions if t.type == "Expense")

    category_totals = {}
    for t in transactions:
        if t.type == "Expense":
            category_totals[t.category] = category_totals.get(t.category, 0) + t.amount
    category_breakdown = sorted(category_totals.items(), key=lambda item: -item[1])
    max_category_total = category_breakdown[0][1] if category_breakdown else 0

    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    next_month, next_year = (1, year + 1) if month == 12 else (month + 1, year)

    return render_template(
        "budget.html",
        today=today,
        transactions=transactions,
        income_total=income_total,
        expense_total=expense_total,
        remaining=income_total - expense_total,
        category_breakdown=category_breakdown,
        max_category_total=max_category_total,
        month_name=cal_module.month_name[month],
        year=year,
        month=month,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
        types=TRANSACTION_TYPES,
        categories=TRANSACTION_CATEGORIES,
    )


@app.route("/todos/new", methods=["POST"])
def new_todo():
    text = request.form.get("text", "").strip()
    if text:
        db.session.add(Todo(text=text))
        db.session.commit()
    return redirect(url_for("home"))


@app.route("/todos/<int:todo_id>/toggle", methods=["POST"])
def toggle_todo(todo_id):
    todo = Todo.query.get_or_404(todo_id)
    todo.done = not todo.done
    db.session.commit()
    return redirect(url_for("home"))


@app.route("/todos/<int:todo_id>/delete", methods=["POST"])
def delete_todo(todo_id):
    todo = Todo.query.get_or_404(todo_id)
    db.session.delete(todo)
    db.session.commit()
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True)
