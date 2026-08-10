from flask import Flask, render_template
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


if __name__ == "__main__":
    app.run(debug=True)
