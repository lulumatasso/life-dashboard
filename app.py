from flask import Flask, render_template, request, redirect, url_for
from models import db, Course

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


if __name__ == "__main__":
    app.run(debug=True)
