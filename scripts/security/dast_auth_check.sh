#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:?base URL is required}"
DAST_PASSWORD="${2:?DAST password is required}"
ZAP_DIR="${3:?ZAP writable directory is required}"

USER_ONE="zap_dast_user_one"
USER_TWO="zap_dast_user_two"
JOB_ONE="10000000-0000-4000-8000-000000000001"
JOB_TWO="20000000-0000-4000-8000-000000000002"

login() {
  local username="$1" jar="$2" csrf status session
  curl --silent --show-error --fail --cookie-jar "$jar" "$BASE_URL/accounts/login/" --output /dev/null
  csrf="$(awk '$6 == "csrftoken" { value=$7 } END { print value }' "$jar")"
  if [[ -z "$csrf" ]]; then echo "Could not obtain CSRF cookie for $username" >&2; return 1; fi
  status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --cookie "$jar" --cookie-jar "$jar" --header "Referer: $BASE_URL/accounts/login/" --data-urlencode "username=$username" --data-urlencode "password=$DAST_PASSWORD" --data-urlencode "csrfmiddlewaretoken=$csrf" "$BASE_URL/accounts/login/")"
  if [[ "$status" != "302" ]]; then echo "Login failed for $username (HTTP $status)" >&2; return 1; fi
  session="$(awk '$6 == "sessionid" { value=$7 } END { print value }' "$jar")"
  if [[ -z "$session" ]]; then echo "No authenticated session cookie for $username" >&2; return 1; fi
  status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --cookie "$jar" "$BASE_URL/app/")"
  if [[ "$status" != "200" ]]; then echo "Authenticated dashboard check failed for $username (HTTP $status)" >&2; return 1; fi
  printf '%s|%s' "$csrf" "$session"
}

mkdir -p "$ZAP_DIR"
chmod 777 "$ZAP_DIR"
JAR_ONE="$ZAP_DIR/user-one.cookies"
JAR_TWO="$ZAP_DIR/user-two.cookies"
trap 'rm -f "$JAR_ONE" "$JAR_TWO"' EXIT
AUTH_ONE="$(login "$USER_ONE" "$JAR_ONE")"
AUTH_TWO="$(login "$USER_TWO" "$JAR_TWO")"
CSRF_ONE="${AUTH_ONE%%|*}"
SESSION_ONE="${AUTH_ONE#*|}"

# Verify that each account can read its own record but cannot read the other account's record.
own_status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --cookie "$JAR_ONE" "$BASE_URL/api/v1/transfers/$JOB_ONE/")"
foreign_status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --cookie "$JAR_ONE" "$BASE_URL/api/v1/transfers/$JOB_TWO/")"
foreign_report_status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --cookie "$JAR_ONE" "$BASE_URL/api/v1/transfers/$JOB_TWO/report/")"
other_owner_status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --cookie "$JAR_TWO" "$BASE_URL/api/v1/transfers/$JOB_TWO/")"
if [[ "$own_status" != "200" || "$other_owner_status" != "200" || "$foreign_status" != "404" || "$foreign_report_status" != "404" ]]; then
  printf 'Access-control regression: own=%s other_own=%s foreign=%s foreign_report=%s\n' "$own_status" "$other_owner_status" "$foreign_status" "$foreign_report_status" >&2
  exit 1
fi

cat > "$ZAP_DIR/zap-auth.conf" <<EOF
replacer.full_list(0).description=CI authenticated session cookie
replacer.full_list(0).enabled=true
replacer.full_list(0).matchtype=REQ_HEADER
replacer.full_list(0).matchstr=Cookie
replacer.full_list(0).regex=false
replacer.full_list(0).replacement=csrftoken=$CSRF_ONE; sessionid=$SESSION_ONE
replacer.full_list(1).description=CI CSRF request header
replacer.full_list(1).enabled=true
replacer.full_list(1).matchtype=REQ_HEADER
replacer.full_list(1).matchstr=X-CSRFToken
replacer.full_list(1).regex=false
replacer.full_list(1).replacement=$CSRF_ONE
EOF
chmod 644 "$ZAP_DIR/zap-auth.conf"
echo "Authenticated DAST login and cross-account access checks passed"
