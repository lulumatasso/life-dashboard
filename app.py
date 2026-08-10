import calendar as cal_module
from datetime import date, datetime

from flask import Flask, render_template, request, redirect, url_for
from models import db, Course, Assignment, STATUS_CHOICES, Application, APPLICATION_STATUS_CHOICES

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

    followups = Application.query.filter(
        Application.follow_up_date >= date(year, month, 1),
        Application.follow_up_date <= date(year, month, days_in_month),
    ).all()
    for a in followups:
        events_by_day.setdefault(a.follow_up_date.day, []).append(
            {
                "title": f"Follow up: {a.company}",
                "category": "professional",
                "url": url_for("application_detail", application_id=a.id),
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


if __name__ == "__main__":
    app.run(debug=True)
