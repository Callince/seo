
from app import db, app  # Ensure you import your Flask app and db instance

with app.app_context():
    db.create_all()
    print("Database tables created!")
