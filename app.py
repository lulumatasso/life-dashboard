import calendar as cal_module
from datetime import date, datetime

from flask import Flask, render_template, request, redirect, url_for
from models import db, Course, Assignment, STATUS_CHOICES

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///dashboard.db"
db.init_app(app)

with app.app_context():
    db.create_all()


@app.route("/")
def home():
    return render_template("home.html", name="AvaLucia")


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


@app.route("/calendar")
def calendar_view():
    today = date.today()
    year = request.args.get("year", type=int) or today.year
    month = request.args.get("month", type=int) or today.month

    weeks = cal_module.Calendar(firstweekday=6).monthdayscalendar(year, month)
    days_in_month = cal_module.monthrange(year, month)[1]

    assignments = Assignment.query.filter(
        Assignment.due_date >= date(year, month, 1),
        Assignment.due_date <= date(year, month, days_in_month),
    ).all()

    events_by_day = {}
    for a in assignments:
        events_by_day.setdefault(a.due_date.day, []).append(
            {
                "title": f"{a.name} — {a.course.name}",
                "category": "academic",
                "url": url_for("course_detail", course_id=a.course_id),
            }
        )

    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    next_month, next_year = (1, year + 1) if month == 12 else (month + 1, year)

    return render_template(
        "calendar.html",
        weeks=weeks,
        events_by_day=events_by_day,
        month_name=cal_module.month_name[month],
        year=year,
        month=month,
        today=today,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
    )


if __name__ == "__main__":
    app.run(debug=True)
