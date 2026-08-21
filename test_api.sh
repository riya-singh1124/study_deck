#!/usr/bin/env bash
# Smoke test for the Study Desk API.
# Usage: ./test_api.sh [BASE_URL]   (default http://localhost:8000)

set -euo pipefail
BASE="${1:-http://localhost:8000}"
pass() { echo "  ✅ $1"; }
fail() { echo "  ❌ $1"; exit 1; }
jsonget() { python3 -c "import sys,json;print(json.load(sys.stdin)$1)"; }

# Unique emails so re-runs don't 409.
STAMP=$(date +%s)
A="alice+${STAMP}@test.com"
B="bob+${STAMP}@test.com"

echo "▶ health"
curl -sf "$BASE/health" > /dev/null && pass "GET /health"

echo "▶ auth"
ATOK=$(curl -sf -X POST "$BASE/auth/signup" -H 'Content-Type: application/json' \
       -d "{\"email\":\"$A\",\"password\":\"secret1\"}" | jsonget "['access_token']")
pass "signup alice → token"

BTOK=$(curl -sf -X POST "$BASE/auth/signup" -H 'Content-Type: application/json' \
       -d "{\"email\":\"$B\",\"password\":\"secret2\"}" | jsonget "['access_token']")
pass "signup bob → token"

code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/auth/signup" \
       -H 'Content-Type: application/json' -d "{\"email\":\"$A\",\"password\":\"x\"}")
[ "$code" = "409" ] && pass "duplicate signup → 409" || fail "duplicate signup got $code"

code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/me")
[ "$code" = "401" ] && pass "no token → 401" || fail "no token got $code"

code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/auth/login" \
       -d "username=$A&password=WRONG" -H 'Content-Type: application/x-www-form-urlencoded')
[ "$code" = "401" ] && pass "bad password → 401" || fail "bad password got $code"

curl -sf -X POST "$BASE/auth/login" -d "username=$A&password=secret1" \
     -H 'Content-Type: application/x-www-form-urlencoded' > /dev/null
pass "form login (OAuth2 password flow)"

echo "▶ decks & cards"
DECK=$(curl -sf -X POST "$BASE/decks" -H "Authorization: Bearer $ATOK" \
       -H 'Content-Type: application/json' \
       -d '{"title":"Physics","description":"Kinematics"}')
DECK_ID=$(echo "$DECK" | jsonget "['id']")
pass "create deck"

curl -sf -X POST "$BASE/decks/$DECK_ID/cards" -H "Authorization: Bearer $ATOK" \
     -H 'Content-Type: application/json' \
     -d '{"question":"Newton 2nd law?","answer":"F=ma","code":"","equation":"F = m*a"}' > /dev/null
pass "add card"

count=$(curl -sf "$BASE/decks/$DECK_ID/cards" -H "Authorization: Bearer $ATOK" \
        | python3 -c "import sys,json;print(len(json.load(sys.stdin)))")
[ "$count" = "1" ] && pass "list cards (1)" || fail "expected 1 card, got $count"

echo "▶ sharing & permissions"
count=$(curl -sf "$BASE/decks" -H "Authorization: Bearer $BTOK" \
        | python3 -c "import sys,json;print(len(json.load(sys.stdin)))")
[ "$count" = "0" ] && pass "bob sees no decks yet" || fail "bob sees $count decks"

curl -sf -X POST "$BASE/decks/$DECK_ID/share" -H "Authorization: Bearer $ATOK" \
     -H 'Content-Type: application/json' -d "{\"email\":\"$B\"}" > /dev/null
pass "share deck with bob"

count=$(curl -sf "$BASE/decks" -H "Authorization: Bearer $BTOK" \
        | python3 -c "import sys,json;print(len(json.load(sys.stdin)))")
[ "$count" = "1" ] && pass "bob now sees shared deck" || fail "bob sees $count decks"

code=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE/decks/$DECK_ID" \
       -H "Authorization: Bearer $BTOK")
[ "$code" = "403" ] && pass "bob delete → 403" || fail "bob delete got $code"

code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/decks/$DECK_ID/cards" \
       -H "Authorization: Bearer $BTOK" -H 'Content-Type: application/json' \
       -d '{"question":"x"}')
[ "$code" = "403" ] && pass "bob add card → 403" || fail "bob add card got $code"

echo "▶ search"
hits=$(curl -sf "$BASE/search?q=newton" -H "Authorization: Bearer $BTOK" \
       | python3 -c "import sys,json;print(len(json.load(sys.stdin)))")
[ "$hits" -ge 1 ] && pass "search finds card" || fail "search got $hits hits"

echo
echo "🎉 All API tests passed."
