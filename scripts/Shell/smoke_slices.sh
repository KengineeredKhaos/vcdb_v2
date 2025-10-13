#!/usr/bin/env bash
# scripts/smoke_slices.sh
# Quick end-to-end smoke of auth + slice /hello routes with CSRF-aware login/logout.
# Usage: BASE=http://127.0.0.1:5000 bash scripts/smoke_slices.sh

set -eo pipefail

: "${BASE:=http://127.0.0.1:5000}"
: "${USER_JAR:=/tmp/vcdb.user.cookies}"
: "${ADMIN_JAR:=/tmp/vcdb.admin.cookies}"

# --- helpers ---------------------------------------------------------------

hdr() { echo -e "\033[1m$*\033[0m"; }
ok()  { echo "ok: $*"; }
fail(){ echo "FAIL: $*" >&2; exit 1; }

# extract csrf_token from a GET page using sed (works with our templates)
csrf_from() {
  local path="$1"
  curl -s -c "$USER_JAR" -b "$USER_JAR" "$BASE$path" \
    | sed -n 's/.*name="csrf_token" value="\([^"]*\)".*/\1/p' | head -n1
}

expect_code() {
  local expected="$1"; shift
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" "$@")
  [[ "$code" == "$expected" ]] || fail "$* expected $expected got $code"
}

expect_code_with_data() {
  local expected="$1"; shift
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" "$@")
  [[ "$code" == "$expected" ]] || fail "POST expected $expected got $code"
}

login_user() {
  local csrf
  csrf=$(csrf_from "/auth/login") || true
  [[ -n "$csrf" ]] || fail "couldn't scrape CSRF from /auth/login"
  expect_code_with_data 302 \
    -c "$USER_JAR" -b "$USER_JAR" -X POST \
    -d "login=user@example.com" \
    -d "password=password" \
    -d "csrf_token=$csrf" \
    "$BASE/auth/login"
  ok "logged in as user@example.com"
}

logout_user() {
  local csrf
  csrf=$(csrf_from "/") || true
  [[ -n "$csrf" ]] || fail "couldn't scrape CSRF for logout"
  expect_code_with_data 302 \
    -c "$USER_JAR" -b "$USER_JAR" -X POST \
    -d "csrf_token=$csrf" \
    "$BASE/auth/logout"
  ok "logout (302)"
}

# --- run -------------------------------------------------------------------

hdr "Hitting $BASE/healthz and / ..."
expect_code 200 "$BASE/healthz";  ok "healthz (200)"
expect_code 200 "$BASE/";         ok "root (200)"

hdr "Unauthenticated slice /hello should redirect to login..."
for s in customers resources sponsors inventory transactions calendar governance; do
  expect_code 302 "$BASE/$s/hello"; ok "$s unauth (302)"
done

hdr "Logging in as user@example.com..."
login_user

hdr "Authenticated /hello should be 200 for user-level slices, 403 for admin-only..."
for s in customers resources sponsors inventory transactions calendar; do
  expect_code 200 -b "$USER_JAR" "$BASE/$s/hello"; ok "$s auth (200)"
done
# governance is admin-only; user should be forbidden
expect_code 403 -b "$USER_JAR" "$BASE/governance/hello"; ok "governance auth (as user) (403)"

hdr "Logging out (POST with CSRF) and verifying redirects again..."
logout_user
for s in customers resources sponsors inventory transactions calendar governance; do
  expect_code 302 "$BASE/$s/hello"; ok "$s post-logout (302)"
done

echo "All good."

# best-effort cleanup
rm -f "$USER_JAR" 2>/dev/null || true
