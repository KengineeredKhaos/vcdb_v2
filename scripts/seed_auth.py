# scripts/seed_auth.py

from app.slices.auth.policies import load_rbac_policy


def run():
    pol = load_rbac_policy()
    print("auth canonicals seeded")
