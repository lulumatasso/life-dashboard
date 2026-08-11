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


APPLICATION_STATUS_CHOICES = ["Applied", "Phone Screen", "Interview", "Offer", "Rejected", "Closed"]


class Application(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(120), nullable=False)
    date_applied = db.Column(db.Date)
    source = db.Column(db.String(200))
    status = db.Column(db.String(20), default="Applied")
    follow_up_date = db.Column(db.Date)
    notes = db.Column(db.Text)

    def __repr__(self):
        return f"<Application {self.company} - {self.role}>"


TRANSACTION_TYPES = ["Income", "Expense"]
TRANSACTION_CATEGORIES = [
    "Rent", "Food", "Subscriptions", "Transportation",
    "Entertainment", "Utilities", "Income", "Other",
]


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(150), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    type = db.Column(db.String(10), nullable=False, default="Expense")
    category = db.Column(db.String(30), default="Other")
    date = db.Column(db.Date, nullable=False)
    is_recurring = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<Transaction {self.description} {self.amount}>"


EVENT_CATEGORIES = ["personal", "academic", "professional", "financial"]


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    date = db.Column(db.Date, nullable=False)
    category = db.Column(db.String(20), default="personal")
    notes = db.Column(db.Text)

    def __repr__(self):
        return f"<Event {self.title}>"


class Todo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(200), nullable=False)
    done = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def __repr__(self):
        return f"<Todo {self.text}>"
