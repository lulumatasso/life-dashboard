from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


GRADING_MODES = ["percentage", "points"]


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    professor = db.Column(db.String(100))
    credit_hours = db.Column(db.Integer)
    term = db.Column(db.String(50))
    syllabus_filename = db.Column(db.String(255))
    syllabus_original_name = db.Column(db.String(255))
    syllabus_url = db.Column(db.String(500))
    grading_mode = db.Column(db.String(12), default="percentage")

    assignments = db.relationship(
        "Assignment", backref="course", lazy=True, cascade="all, delete-orphan"
    )
    categories = db.relationship(
        "AssignmentCategory", backref="course", lazy=True, cascade="all, delete-orphan"
    )
    events = db.relationship(
        "Event", backref="course", lazy=True, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Course {self.name}>"

    @property
    def current_grade(self):
        graded = [a for a in self.assignments if a.status == "Graded" and a.grade is not None]
        if not graded:
            return None
        if self.grading_mode == "points":
            total_possible = sum(a.effective_weight or 0 for a in graded)
            if total_possible == 0:
                return None
            return sum(a.grade or 0 for a in graded) / total_possible * 100
        total_weight = sum(a.effective_weight or 0 for a in graded)
        if total_weight == 0:
            return None
        return sum((a.grade or 0) * (a.effective_weight or 0) for a in graded) / total_weight

    @property
    def points_summary(self):
        if self.grading_mode != "points":
            return None
        graded = [a for a in self.assignments if a.status == "Graded" and a.grade is not None]
        possible = sum(a.effective_weight or 0 for a in graded)
        if possible == 0:
            return None
        return {"earned": sum(a.grade or 0 for a in graded), "possible": possible}


DEFAULT_CATEGORY_COLOR = "#5c7285"


class AssignmentCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    value = db.Column(db.Float, nullable=False)
    color = db.Column(db.String(7), default=DEFAULT_CATEGORY_COLOR)

    assignments = db.relationship("Assignment", backref="category", lazy=True)

    def __repr__(self):
        return f"<AssignmentCategory {self.name}>"

    @property
    def per_item_value(self):
        count = len(self.assignments)
        return self.value / count if count else None


STATUS_CHOICES = ["Not started", "In progress", "Submitted", "Graded"]


class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("assignment_category.id"))
    name = db.Column(db.String(150), nullable=False)
    due_date = db.Column(db.Date)
    weight = db.Column(db.Float)
    status = db.Column(db.String(20), default="Not started")
    grade = db.Column(db.Float)

    def __repr__(self):
        return f"<Assignment {self.name}>"

    @property
    def effective_weight(self):
        """The weight/points actually used in grade math: auto-split from the category if assigned, else the manual value."""
        if self.category_id and self.category:
            return self.category.per_item_value
        return self.weight


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
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"))
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


class Habit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    completions = db.relationship(
        "HabitCompletion", backref="habit", lazy=True, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Habit {self.name}>"


class HabitCompletion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    habit_id = db.Column(db.Integer, db.ForeignKey("habit.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)

    __table_args__ = (db.UniqueConstraint("habit_id", "date", name="uq_habit_date"),)
