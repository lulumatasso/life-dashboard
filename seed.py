from app import app
from models import db, Course

with app.app_context():
    db.session.add(Course(name="Intro to Psychology", professor="Dr. Lee", credit_hours=3, term="Fall 2026"))
    db.session.add(Course(name="Calculus II", professor="Dr. Patel", credit_hours=4, term="Fall 2026"))
    db.session.commit()

    print("Courses in database:")
    for course in Course.query.all():
        print(f"  {course.id}: {course.name} ({course.professor}, {course.credit_hours} credits)")
