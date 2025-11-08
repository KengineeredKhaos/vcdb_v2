# app/seeds/demo.py
from app.extensions import db
from .core import seed_minimal_customer

def seed_demo_dataset():
    # call core seeds multiple times, maybe with different data
    for i in range(3):
        seed_minimal_customer(first=f"DEMO{i}", last="USER")
    db.session.commit()
