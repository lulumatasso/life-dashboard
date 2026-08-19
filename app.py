import calendar as cal_module
import io
import os
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from werkzeug.utils import secure_filename
from models import (
    db,
    Course,
    GRADING_MODES,
    Assignment,
    AssignmentCategory,
    DEFAULT_CATEGORY_COLOR,
    STATUS_CHOICES,
    Application,
    APPLICATION_STATUS_CHOICES,
    Transaction,
    TRANSACTION_TYPES,
    TRANSACTION_CATEGORIES,
    Todo,
    Event,
    EVENT_CATEGORIES,
    Habit,
    HabitCompletion,
    ClassMeeting,
    WEEKDAYS,
)
import syllabus

load_dotenv()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///dashboard.db"
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-secret-for-local-use")
app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "uploads", "syllabi")
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
db.init_app(app)

class InMemoryUpload:
    """Mimics just enough of Flask's FileStorage so syllabus.extract_text can read bytes we already saved to disk."""

    def __init__(self, filename, data):
        self.filename = filename
        self.stream = io.BytesIO(data)


def ensure_columns(inspector, conn, table_name, columns):
    """One-time upgrade helper: add any columns a table is missing (SQLite has no ALTER-safe migrations built in)."""
    existing = {col["name"] for col in inspector.get_columns(table_name)}
    for column_name, column_type in columns.items():
        if column_name not in existing:
            conn.execute(db.text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))


with app.app_context():
    db.create_all()

    inspector = db.inspect(db.engine)
    with db.engine.connect() as conn:
        ensure_columns(
            inspector,
            conn,
            "course",
            {
                "syllabus_filename": "VARCHAR(255)",
                "syllabus_original_name": "VARCHAR(255)",
                "syllabus_url": "VARCHAR(500)",
                "grading_mode": "VARCHAR(12)",
            },
        )
        ensure_columns(inspector, conn, "assignment", {"category_id": "INTEGER"})
        ensure_columns(inspector, conn, "assignment_category", {"color": "VARCHAR(7)"})
        ensure_columns(inspector, conn, "event", {"course_id": "INTEGER", "start_time": "TIME", "end_time": "TIME"})
        conn.execute(
            db.text("UPDATE assignment_category SET color = :color WHERE color IS NULL"),
            {"color": DEFAULT_CATEGORY_COLOR},
        )
        conn.commit()


EVENT_CATEGORY_COLORS = {
    "academic": DEFAULT_CATEGORY_COLOR,
    "professional": "#7a9171",
    "financial": "#c08a44",
    "personal": "#b97b7e",
}

CATEGORY_COLOR_PALETTE = [
    "#5c7285",  # dusty blue-gray
    "#7a9171",  # sage
    "#c08a44",  # ochre
    "#b97b7e",  # dusty rose
    "#8a6fa8",  # soft plum
    "#4d8a8a",  # soft teal
    "#b5654a",  # terracotta
    "#6b7c4f",  # olive
]


def course_color(course):
    return CATEGORY_COLOR_PALETTE[course.id % len(CATEGORY_COLOR_PALETTE)]


def build_meetings_by_day():
    """Every class's recurring weekly meetings, grouped by day (0=Monday ... 6=Sunday)."""
    courses = Course.query.all()
    meetings_by_day = {i: [] for i in range(7)}
    for course in courses:
        for m in course.meetings:
            meetings_by_day[m.day_of_week].append(
                {
                    "course": course,
                    "meeting": m,
                    "time_label": format_time_range(m.start_time, m.end_time),
                    "color": course_color(course),
                }
            )
    for day_meetings in meetings_by_day.values():
        day_meetings.sort(key=lambda row: row["meeting"].start_time)
    return meetings_by_day


def parse_time(raw):
    return datetime.strptime(raw, "%H:%M").time() if raw else None


def format_time_range(start_time, end_time):
    if not start_time:
        return None
    label = start_time.strftime("%I:%M %p").lstrip("0")
    if end_time:
        label += "–" + end_time.strftime("%I:%M %p").lstrip("0")
    return label


def gather_events_by_date(start, end):
    """Aggregate events from every module into a dict keyed by date, for the inclusive range [start, end]."""
    events_by_date = {}

    assignments = Assignment.query.filter(Assignment.due_date >= start, Assignment.due_date <= end).all()
    for a in assignments:
        color = (a.category.color if a.category else None) or EVENT_CATEGORY_COLORS["academic"]
        events_by_date.setdefault(a.due_date, []).append(
            {
                "title": f"{a.name} — {a.course.name}",
                "category": "academic",
                "color": color,
                "url": url_for("course_detail", course_id=a.course_id),
            }
        )

    followups = Application.query.filter(
        Application.follow_up_date >= start, Application.follow_up_date <= end
    ).all()
    for a in followups:
        events_by_date.setdefault(a.follow_up_date, []).append(
            {
                "title": f"Follow up: {a.company}",
                "category": "professional",
                "color": EVENT_CATEGORY_COLORS["professional"],
                "url": url_for("application_detail", application_id=a.id),
            }
        )

    bills = Transaction.query.filter(
        Transaction.is_recurring.is_(True), Transaction.date >= start, Transaction.date <= end
    ).all()
    for t in bills:
        events_by_date.setdefault(t.date, []).append(
            {
                "title": t.description,
                "category": "financial",
                "color": EVENT_CATEGORY_COLORS["financial"],
                "url": url_for("budget", year=t.date.year, month=t.date.month),
            }
        )

    custom_events = Event.query.filter(Event.date >= start, Event.date <= end).all()
    for e in custom_events:
        events_by_date.setdefault(e.date, []).append(
            {
                "title": e.title,
                "time_label": format_time_range(e.start_time, e.end_time),
                "category": e.category,
                "color": EVENT_CATEGORY_COLORS.get(e.category, DEFAULT_CATEGORY_COLOR),
                "url": url_for("edit_event", event_id=e.id),
            }
        )

    return events_by_date


def get_month_calendar(year, month):
    """Aggregate events from every module into one month's calendar grid."""
    weeks = cal_module.Calendar(firstweekday=6).monthdayscalendar(year, month)
    days_in_month = cal_module.monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year, month, days_in_month)

    events_by_date = gather_events_by_date(start, end)
    events_by_day = {d.day: events for d, events in events_by_date.items()}

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


def get_week_calendar(anchor):
    """Aggregate events into a Sunday-start week view containing the anchor date."""
    offset = (anchor.weekday() + 1) % 7  # Python: Mon=0..Sun=6; we want the week to start Sunday
    week_start = anchor - timedelta(days=offset)
    week_dates = [week_start + timedelta(days=i) for i in range(7)]
    events_by_date = gather_events_by_date(week_dates[0], week_dates[-1])

    return {
        "days": [{"date": d, "events": events_by_date.get(d, [])} for d in week_dates],
        "week_start": week_dates[0],
        "week_end": week_dates[-1],
        "prev_week_date": (anchor - timedelta(days=7)).isoformat(),
        "next_week_date": (anchor + timedelta(days=7)).isoformat(),
    }


def habit_streak(habit, today):
    """Count consecutive completed days ending today (or yesterday, if today isn't done yet)."""
    completed_dates = {c.date for c in habit.completions}
    streak = 0
    day = today if today in completed_dates else today - timedelta(days=1)
    while day in completed_dates:
        streak += 1
        day -= timedelta(days=1)
    return streak


def habit_history(habit, today, days=7):
    """Last N days as a list of (date, completed) for a simple dot history."""
    completed_dates = {c.date for c in habit.completions}
    return [(today - timedelta(days=i), (today - timedelta(days=i)) in completed_dates) for i in range(days - 1, -1, -1)]


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
    all_habits = Habit.query.order_by(Habit.created_at).all()
    habit_rows = [
        {
            "habit": h,
            "streak": habit_streak(h, today),
            "history": habit_history(h, today, days=7),
            "done_today": today in {c.date for c in h.completions},
        }
        for h in all_habits
    ]
    month_ctx = get_month_calendar(today.year, today.month)

    upcoming_events = []
    for day, day_events in month_ctx["events_by_day"].items():
        if day >= today.day:
            for e in day_events:
                upcoming_events.append({**e, "date": date(today.year, today.month, day)})
    upcoming_events.sort(key=lambda e: e["date"])

    cal_view = request.args.get("cal_view", "month")
    meetings_by_day = build_meetings_by_day()

    return render_template(
        "home.html",
        name="AvaLucia",
        today=today,
        courses=courses,
        upcoming_assignments=upcoming_assignments,
        recent_applications=recent_applications,
        active_applications=active_applications,
        cal_view=cal_view,
        meetings_by_day=meetings_by_day,
        weekdays=WEEKDAYS,
        todos=todos,
        habit_rows=habit_rows,
        upcoming_events=upcoming_events,
        **month_ctx,
    )


@app.route("/classes")
def classes():
    courses = Course.query.all()
    total_credit_hours = sum(c.credit_hours or 0 for c in courses)
    graded = [c.current_grade for c in courses if c.current_grade is not None]
    average_grade = sum(graded) / len(graded) if graded else None
    return render_template(
        "classes.html",
        courses=courses,
        total_credit_hours=total_credit_hours,
        average_grade=average_grade,
    )


@app.route("/classes/new", methods=["GET", "POST"])
def new_class():
    if request.method == "POST":
        course = Course(
            name=request.form["name"],
            professor=request.form.get("professor"),
            credit_hours=request.form.get("credit_hours") or None,
            term=request.form.get("term"),
            grading_mode=request.form.get("grading_mode") or "percentage",
        )
        db.session.add(course)
        db.session.commit()
        return redirect(url_for("classes"))
    return render_template("new_class.html", grading_modes=GRADING_MODES)


@app.route("/classes/<int:course_id>/edit", methods=["GET", "POST"])
def edit_class(course_id):
    course = Course.query.get_or_404(course_id)
    if request.method == "POST":
        course.name = request.form["name"]
        course.professor = request.form.get("professor")
        course.credit_hours = request.form.get("credit_hours") or None
        course.term = request.form.get("term")
        course.grading_mode = request.form.get("grading_mode") or "percentage"
        db.session.commit()
        return redirect(url_for("course_detail", course_id=course.id))
    sorted_meetings = sorted(course.meetings, key=lambda m: (m.day_of_week, m.start_time))
    return render_template(
        "edit_class.html",
        course=course,
        grading_modes=GRADING_MODES,
        palette=CATEGORY_COLOR_PALETTE,
        meetings=sorted_meetings,
        weekdays=WEEKDAYS,
    )


@app.route("/classes/<int:course_id>/delete", methods=["POST"])
def delete_class(course_id):
    course = Course.query.get_or_404(course_id)
    db.session.delete(course)
    db.session.commit()
    return redirect(url_for("classes"))


@app.route("/classes/<int:course_id>")
def course_detail(course_id):
    course = Course.query.get_or_404(course_id)
    today = date.today()
    sorted_assignments = sorted(course.assignments, key=lambda a: (a.due_date is None, a.due_date or date.max))

    year = request.args.get("year", type=int) or today.year
    month = request.args.get("month", type=int) or today.month
    weeks = cal_module.Calendar(firstweekday=6).monthdayscalendar(year, month)
    days_in_month = cal_module.monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year, month, days_in_month)

    events_by_day = {}
    for a in course.assignments:
        if a.due_date and start <= a.due_date <= end:
            color = (a.category.color if a.category else None) or EVENT_CATEGORY_COLORS["academic"]
            events_by_day.setdefault(a.due_date.day, []).append(
                {
                    "title": a.name,
                    "color": color,
                    "url": url_for("edit_assignment", course_id=course.id, assignment_id=a.id),
                }
            )
    for e in course.events:
        if start <= e.date <= end:
            events_by_day.setdefault(e.date.day, []).append(
                {
                    "title": e.title,
                    "time_label": format_time_range(e.start_time, e.end_time),
                    "color": EVENT_CATEGORY_COLORS["personal"],
                    "url": url_for("edit_event", event_id=e.id),
                }
            )

    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    next_month, next_year = (1, year + 1) if month == 12 else (month + 1, year)

    meetings_by_weekday = {i: [] for i in range(5)}
    for m in sorted(course.meetings, key=lambda m: (m.day_of_week, m.start_time)):
        if m.day_of_week < 5:
            meetings_by_weekday[m.day_of_week].append(m)

    return render_template(
        "course_detail.html",
        course=course,
        assignments=sorted_assignments,
        status_choices=STATUS_CHOICES,
        meetings_by_weekday=meetings_by_weekday,
        has_meetings=bool(course.meetings),
        weekdays=WEEKDAYS,
        today=today,
        weeks=weeks,
        events_by_day=events_by_day,
        month_name=cal_module.month_name[month],
        year=year,
        month=month,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
        palette=CATEGORY_COLOR_PALETTE,
    )


@app.route("/classes/<int:course_id>/meetings/new", methods=["POST"])
def new_class_meeting(course_id):
    course = Course.query.get_or_404(course_id)
    start_time = parse_time(request.form.get("start_time"))
    day_raw = request.form.get("day_of_week")
    if start_time and day_raw is not None and day_raw != "":
        db.session.add(
            ClassMeeting(
                course_id=course.id,
                day_of_week=int(day_raw),
                start_time=start_time,
                end_time=parse_time(request.form.get("end_time")),
                location=request.form.get("location") or None,
            )
        )
        db.session.commit()
    return redirect(url_for("edit_class", course_id=course.id))


@app.route("/classes/<int:course_id>/meetings/<int:meeting_id>/delete", methods=["POST"])
def delete_class_meeting(course_id, meeting_id):
    meeting = ClassMeeting.query.filter_by(id=meeting_id, course_id=course_id).first_or_404()
    db.session.delete(meeting)
    db.session.commit()
    return redirect(url_for("edit_class", course_id=course_id))


@app.route("/classes/<int:course_id>/assignments/<int:assignment_id>/status", methods=["POST"])
def update_assignment_status(course_id, assignment_id):
    assignment = Assignment.query.filter_by(id=assignment_id, course_id=course_id).first_or_404()
    new_status = request.form.get("status")
    if new_status in STATUS_CHOICES:
        assignment.status = new_status
        db.session.commit()
    base = request.referrer or url_for("course_detail", course_id=course_id)
    parts = urlsplit(base)
    target = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, f"assignment-{assignment_id}"))
    return redirect(target)


@app.route("/classes/<int:course_id>/assignments/new", methods=["GET", "POST"])
def new_assignment(course_id):
    course = Course.query.get_or_404(course_id)
    if request.method == "POST":
        due_date_raw = request.form.get("due_date")
        weight_raw = request.form.get("weight")
        grade_raw = request.form.get("grade")
        category_raw = request.form.get("category_id")
        assignment = Assignment(
            course_id=course.id,
            category_id=int(category_raw) if category_raw else None,
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


@app.route("/classes/<int:course_id>/assignments/<int:assignment_id>/edit", methods=["GET", "POST"])
def edit_assignment(course_id, assignment_id):
    course = Course.query.get_or_404(course_id)
    assignment = Assignment.query.filter_by(id=assignment_id, course_id=course.id).first_or_404()
    if request.method == "POST":
        due_date_raw = request.form.get("due_date")
        weight_raw = request.form.get("weight")
        grade_raw = request.form.get("grade")
        category_raw = request.form.get("category_id")
        assignment.name = request.form["name"]
        assignment.due_date = datetime.strptime(due_date_raw, "%Y-%m-%d").date() if due_date_raw else None
        assignment.category_id = int(category_raw) if category_raw else None
        assignment.weight = float(weight_raw) if weight_raw else None
        assignment.status = request.form.get("status") or assignment.status
        assignment.grade = float(grade_raw) if grade_raw else None
        db.session.commit()
        return redirect(url_for("course_detail", course_id=course.id))
    return render_template(
        "edit_assignment.html", course=course, assignment=assignment, status_choices=STATUS_CHOICES
    )


@app.route("/classes/<int:course_id>/assignments/<int:assignment_id>/delete", methods=["POST"])
def delete_assignment(course_id, assignment_id):
    assignment = Assignment.query.filter_by(id=assignment_id, course_id=course_id).first_or_404()
    db.session.delete(assignment)
    db.session.commit()
    return redirect(url_for("course_detail", course_id=course_id))


@app.route("/classes/<int:course_id>/categories/new", methods=["POST"])
def new_category(course_id):
    course = Course.query.get_or_404(course_id)
    name = request.form.get("name", "").strip()
    value_raw = request.form.get("value")
    color = request.form.get("color") or DEFAULT_CATEGORY_COLOR
    if name and value_raw:
        db.session.add(AssignmentCategory(course_id=course.id, name=name, value=float(value_raw), color=color))
        db.session.commit()
    return redirect(url_for("edit_class", course_id=course.id))


@app.route("/classes/<int:course_id>/categories/<int:category_id>/delete", methods=["POST"])
def delete_category(course_id, category_id):
    category = AssignmentCategory.query.filter_by(id=category_id, course_id=course_id).first_or_404()
    for assignment in category.assignments:
        assignment.category_id = None
    db.session.delete(category)
    db.session.commit()
    return redirect(url_for("edit_class", course_id=course_id))


@app.route("/classes/<int:course_id>/categories/<int:category_id>/edit", methods=["POST"])
def edit_category(course_id, category_id):
    category = AssignmentCategory.query.filter_by(id=category_id, course_id=course_id).first_or_404()
    category.name = request.form.get("name", category.name).strip() or category.name
    value_raw = request.form.get("value")
    if value_raw:
        category.value = float(value_raw)
    category.color = request.form.get("color") or category.color
    db.session.commit()
    return redirect(url_for("edit_class", course_id=course_id))


@app.route("/classes/<int:course_id>/dates/new", methods=["GET", "POST"])
def new_course_date(course_id):
    course = Course.query.get_or_404(course_id)
    if request.method == "POST":
        event_date = datetime.strptime(request.form["date"], "%Y-%m-%d").date()
        db.session.add(
            Event(
                course_id=course.id,
                title=request.form["title"],
                date=event_date,
                start_time=parse_time(request.form.get("start_time")),
                end_time=parse_time(request.form.get("end_time")),
                category="academic",
            )
        )
        db.session.commit()
        return redirect(url_for("course_detail", course_id=course.id, year=event_date.year, month=event_date.month))
    default_date = request.args.get("date", date.today().isoformat())
    return render_template("new_course_date.html", course=course, default_date=default_date)


@app.route("/classes/<int:course_id>/syllabus/upload", methods=["GET", "POST"])
def upload_syllabus(course_id):
    course = Course.query.get_or_404(course_id)
    if request.method == "POST":
        file = request.files.get("syllabus")
        if not file or not file.filename:
            return render_template("upload_syllabus.html", course=course, error="Please choose a file.")

        file_bytes = file.read()
        stored_name = f"{course.id}_{uuid4().hex}_{secure_filename(file.filename)}"
        with open(os.path.join(app.config["UPLOAD_FOLDER"], stored_name), "wb") as f:
            f.write(file_bytes)
        course.syllabus_filename = stored_name
        course.syllabus_original_name = file.filename
        course.syllabus_url = None
        db.session.commit()

        try:
            file_copy = InMemoryUpload(file.filename, file_bytes)
            items = syllabus.extract_assignments_from_upload(file_copy, file_bytes)
        except Exception as exc:
            return render_template("upload_syllabus.html", course=course, error=str(exc))

        session["syllabus_course_id"] = course.id
        session["syllabus_items"] = items
        return redirect(url_for("review_syllabus", course_id=course.id))
    return render_template("upload_syllabus.html", course=course, error=None)


@app.route("/classes/<int:course_id>/syllabus/file")
def download_syllabus(course_id):
    course = Course.query.get_or_404(course_id)
    if not course.syllabus_filename:
        return redirect(url_for("course_detail", course_id=course.id))
    return send_from_directory(
        app.config["UPLOAD_FOLDER"], course.syllabus_filename, download_name=course.syllabus_original_name
    )


@app.route("/classes/<int:course_id>/syllabus/link", methods=["GET", "POST"])
def add_syllabus_link(course_id):
    course = Course.query.get_or_404(course_id)
    if request.method == "POST":
        course.syllabus_url = request.form.get("url", "").strip() or None
        course.syllabus_filename = None
        course.syllabus_original_name = None
        db.session.commit()
        return redirect(url_for("course_detail", course_id=course.id))
    return render_template("add_syllabus_link.html", course=course)


@app.route("/classes/<int:course_id>/syllabus/remove", methods=["POST"])
def remove_syllabus(course_id):
    course = Course.query.get_or_404(course_id)
    if course.syllabus_filename:
        old_path = os.path.join(app.config["UPLOAD_FOLDER"], course.syllabus_filename)
        if os.path.exists(old_path):
            os.remove(old_path)
    course.syllabus_filename = None
    course.syllabus_original_name = None
    course.syllabus_url = None
    db.session.commit()
    return redirect(url_for("course_detail", course_id=course.id))


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
    view = request.args.get("view", "month")
    if view == "week":
        anchor_raw = request.args.get("date")
        anchor = datetime.strptime(anchor_raw, "%Y-%m-%d").date() if anchor_raw else today
        week_ctx = get_week_calendar(anchor)
        return render_template("calendar.html", today=today, view=view, **week_ctx)
    year = request.args.get("year", type=int) or today.year
    month = request.args.get("month", type=int) or today.month
    month_ctx = get_month_calendar(year, month)
    return render_template("calendar.html", today=today, view=view, **month_ctx)


@app.route("/calendar/schedule")
def academic_schedule():
    return render_template("academic_schedule.html", meetings_by_day=build_meetings_by_day(), weekdays=WEEKDAYS)


@app.route("/calendar/events/new", methods=["GET", "POST"])
def new_event():
    if request.method == "POST":
        event_date = datetime.strptime(request.form["date"], "%Y-%m-%d").date()
        event = Event(
            title=request.form["title"],
            date=event_date,
            start_time=parse_time(request.form.get("start_time")),
            end_time=parse_time(request.form.get("end_time")),
            category=request.form.get("category") or "personal",
            notes=request.form.get("notes"),
        )
        db.session.add(event)
        db.session.commit()
        return redirect(url_for("calendar_view", year=event_date.year, month=event_date.month))
    default_date = request.args.get("date", date.today().isoformat())
    return render_template("new_event.html", categories=EVENT_CATEGORIES, default_date=default_date)


@app.route("/calendar/events/<int:event_id>/edit", methods=["GET", "POST"])
def edit_event(event_id):
    event = Event.query.get_or_404(event_id)
    if request.method == "POST":
        event.title = request.form["title"]
        event.date = datetime.strptime(request.form["date"], "%Y-%m-%d").date()
        event.start_time = parse_time(request.form.get("start_time"))
        event.end_time = parse_time(request.form.get("end_time"))
        event.category = request.form.get("category") or event.category
        event.notes = request.form.get("notes")
        db.session.commit()
        return redirect(url_for("calendar_view", year=event.date.year, month=event.date.month))
    return render_template("edit_event.html", event=event, categories=EVENT_CATEGORIES)


@app.route("/calendar/events/<int:event_id>/delete", methods=["POST"])
def delete_event(event_id):
    event = Event.query.get_or_404(event_id)
    year, month = event.date.year, event.date.month
    db.session.delete(event)
    db.session.commit()
    return redirect(url_for("calendar_view", year=year, month=month))


@app.route("/applications")
def applications():
    status_filter = request.args.get("status")
    query = Application.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    apps = query.order_by(Application.date_applied.desc()).all()
    status_counts = {
        choice: Application.query.filter_by(status=choice).count() for choice in APPLICATION_STATUS_CHOICES
    }
    return render_template(
        "applications.html",
        applications=apps,
        status_choices=APPLICATION_STATUS_CHOICES,
        status_filter=status_filter,
        status_counts=status_counts,
        total_applications=Application.query.count(),
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

    monthly_trend = []
    trend_month, trend_year = month, year
    for _ in range(6):
        t_days_in_month = cal_module.monthrange(trend_year, trend_month)[1]
        t_start = date(trend_year, trend_month, 1)
        t_end = date(trend_year, trend_month, t_days_in_month)
        t_transactions = Transaction.query.filter(Transaction.date >= t_start, Transaction.date <= t_end).all()
        t_income = sum(t.amount for t in t_transactions if t.type == "Income")
        t_expense = sum(t.amount for t in t_transactions if t.type == "Expense")
        monthly_trend.append(
            {"label": cal_module.month_abbr[trend_month], "net": t_income - t_expense}
        )
        trend_month, trend_year = (12, trend_year - 1) if trend_month == 1 else (trend_month - 1, trend_year)
    monthly_trend.reverse()
    max_abs_net = max((abs(m["net"]) for m in monthly_trend), default=0) or 1

    return render_template(
        "budget.html",
        today=today,
        transactions=transactions,
        income_total=income_total,
        expense_total=expense_total,
        remaining=income_total - expense_total,
        category_breakdown=category_breakdown,
        max_category_total=max_category_total,
        monthly_trend=monthly_trend,
        max_abs_net=max_abs_net,
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


@app.route("/habits")
def habits():
    today = date.today()
    all_habits = Habit.query.order_by(Habit.created_at).all()
    habit_rows = [
        {
            "habit": h,
            "streak": habit_streak(h, today),
            "history": habit_history(h, today, days=14),
            "done_today": today in {c.date for c in h.completions},
        }
        for h in all_habits
    ]
    return render_template("habits.html", habit_rows=habit_rows, today=today)


@app.route("/habits/new", methods=["POST"])
def new_habit():
    name = request.form.get("name", "").strip()
    if name:
        db.session.add(Habit(name=name))
        db.session.commit()
    return redirect(url_for("habits"))


@app.route("/habits/<int:habit_id>/toggle_today", methods=["POST"])
def toggle_habit_today(habit_id):
    habit = Habit.query.get_or_404(habit_id)
    today = date.today()
    existing = HabitCompletion.query.filter_by(habit_id=habit.id, date=today).first()
    if existing:
        db.session.delete(existing)
    else:
        db.session.add(HabitCompletion(habit_id=habit.id, date=today))
    db.session.commit()
    return redirect(request.referrer or url_for("habits"))


@app.route("/habits/<int:habit_id>/delete", methods=["POST"])
def delete_habit(habit_id):
    habit = Habit.query.get_or_404(habit_id)
    db.session.delete(habit)
    db.session.commit()
    return redirect(url_for("habits"))


if __name__ == "__main__":
    app.run(debug=True)
