# scripts/verify_ledger.py
from app.slices.ledger.services import verify_chain


def run():
    print(verify_chain())
