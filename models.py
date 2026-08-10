from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    professor = db.Column(db.String(100))
    credit_hours = db.Column(db.Integer)
    term = db.Column(db.String(50))

    assignments = db.relationship(
        "Assignment", backref="course", lazy=True, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Course {self.name}>"

    @property
    def current_grade(self):
        graded = [a for a in self.assignments if a.status == "Graded" and a.grade is not None]
        total_weight = sum(a.weight or 0 for a in graded)
        if total_weight == 0:
            return None
        return sum((a.grade or 0) * (a.weight or 0) for a in graded) / total_weight


STATUS_CHOICES = ["Not started", "In progress", "Submitted", "Graded"]


class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    due_date = db.Column(db.Date)
    weight = db.Column(db.Float)
    status = db.Column(db.String(20), default="Not started")
    grade = db.Column(db.Float)

    def __repr__(self):
        return f"<Assignment {self.name}>"
