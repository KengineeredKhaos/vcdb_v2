#!/usr/bin/env bash
# scripts/smoke_auth_role_events.sh
set -euo pipefail
BASE="${BASE:-http://127.0.0.1:5000}"

# helper to get http code
function code(){ curl -sk -o /dev/null -w "%{http_code}" "$@"; }

# login as admin
jar=$(mktemp)
csrftoken=$(curl -skc "$jar" "$BASE/auth/login" | sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p')
curl -sk -b "$jar" -c "$jar" -X POST "$BASE/auth/login" -d "email=admin@example.com&password=password&csrf_token=$csrftoken" >/dev/null

# call a dev-only endpoint if you expose one, or manually exercise via Flask shell:
cat <<'SH'
# In a Flask shell, run:
# from app.slices.auth import services as authsvc
# authsvc.assign_role(user_id=2, role_name="user", actor_ulid="ADM1NULIDEXAMPLE", request_id="req-assign-001")
# authsvc.remove_role(user_id=2, role_name="user", actor_ulid="ADM1NULIDEXAMPLE", request_id="req-remove-001")
# Then visit /transactions/ledger to see auth.user_role.* events
SH

echo "Smoke notes printed. Use Flask shell to invoke services and check /transactions/ledger"
