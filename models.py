from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    professor = db.Column(db.String(100))
    credit_hours = db.Column(db.Integer)
    term = db.Column(db.String(50))

    def __repr__(self):
        return f"<Course {self.name}>"
