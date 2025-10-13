#!/usr/bin/env bash
set -euo pipefail
BASE="${BASE:-http://127.0.0.1:5000}"

function httpc(){ curl -sk -o /dev/null -w "%{http_code}" "$@"; }

# viewer should get 403
jar=$(mktemp)
csrftoken=$(curl -skc "$jar" "$BASE/auth/login" | sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p')
curl -sk -b "$jar" -c "$jar" -X POST "$BASE/auth/login" \
  -d "email=viewer@example.com&password=password&csrf_token=$csrftoken" -i >/dev/null
code=$(httpc -b "$jar" "$BASE/governance/hello"); [[ "$code" == "403" ]] && echo "ok: viewer forbidden (403)" || { echo "FAIL viewer governance expect 403 got $code"; exit 1; }

# admin should get 200
jar2=$(mktemp)
csrftoken2=$(curl -skc "$jar2" "$BASE/auth/login" | sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p')
curl -sk -b "$jar2" -c "$jar2" -X POST "$BASE/auth/login" \
  -d "email=admin@example.com&password=password&csrf_token=$csrftoken2" -i >/dev/null
code=$(httpc -b "$jar2" "$BASE/governance/hello"); [[ "$code" == "200" ]] && echo "ok: admin allowed (200)" || { echo "FAIL admin governance expect 200 got $code"; exit 1; }

echo "Governance RBAC smoke passed."
