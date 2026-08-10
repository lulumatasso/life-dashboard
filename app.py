from datetime import datetime

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


if __name__ == "__main__":
    app.run(debug=True)
