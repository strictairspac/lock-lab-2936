#!/usr/bin/env bash
# 全生命周期联调：升级期整数 -> 回填续跑 -> 双接口切换 -> 小数 -> 回退。
set -u
BASE=http://127.0.0.1:19242
PY=/workspace/.venv/bin/python

login() { curl -s -X POST "$BASE/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$1\",\"password\":\"Demo2026!\"}" | $PY -c 'import sys,json;print(json.load(sys.stdin)["token"])'; }
ADMIN="Authorization: Bearer $(login admin@qingyu.test)"
OP="Authorization: Bearer $(login operator@qingyu.test)"
VIEWER="Authorization: Bearer $(login viewer@qingyu.test)"

check() { # desc expected actual
  if [ "$2" = "$3" ]; then echo "PASS: $1 ($3)"; else echo "FAIL: $1 expected=$2 actual=$3"; exit 1; fi
}

echo '== 1. 升级后旧接口按整数办理，拒绝小数 =='
code=$(curl -s -o /tmp/r1.json -w '%{http_code}' -X POST "$BASE/samples" -H "$OP" -H 'Content-Type: application/json' \
  -d '{"code":"E2E-INT","title":"整数样本","quantity":42,"location":"A-1"}')
check "v1 整数写入 201" 201 "$code"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/samples" -H "$OP" -H 'Content-Type: application/json' \
  -d '{"code":"E2E-BAD","title":"小数","quantity":42.5,"location":"A-1"}')
check "v1 拒绝小数 422" 422 "$code"

echo '== 2. 切换前置：回填未完成时切换失败，沿用整数 =='
code=$(curl -s -o /tmp/r2.json -w '%{http_code}' -X POST "$BASE/interface/switch-decimal" -H "$ADMIN")
check "回填前切换被拒 409" 409 "$code"
cat /tmp/r2.json; echo
mode=$(curl -s "$BASE/interface/current" -H "$VIEWER" | $PY -c 'import sys,json;print(json.load(sys.stdin)["mode"])')
check "模式仍为 integer" integer "$mode"

echo '== 3. 分批回填（多轮请求直到完成，验证可轮询/续跑）=='
for i in 1 2 3 4 5; do
  snap=$(curl -s -X POST "$BASE/backfill/run" -H "$ADMIN")
  echo "  batch $i: $snap"
  echo "$snap" | $PY -c 'import sys,json;d=json.load(sys.stdin);sys.exit(0 if d["all_completed"] else 1)' && break
done
st=$(curl -s "$BASE/backfill/status" -H "$ADMIN")
echo "  status: $st"
echo "$st" | $PY -c 'import sys,json;d=json.load(sys.stdin);assert d["all_completed"],d' && echo "PASS: 回填全部完成"

echo '== 4. 两个接口一起切换 =='
code=$(curl -s -o /tmp/r4.json -w '%{http_code}' -X POST "$BASE/interface/switch-decimal" -H "$ADMIN")
check "切换 200" 200 "$code"
mode=$(curl -s "$BASE/interface/current" -H "$VIEWER" | $PY -c 'import sys,json;print(json.load(sys.stdin)["mode"])')
check "模式变为 decimal" decimal "$mode"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/interface/switch-decimal" -H "$OP")
check "操作员不能切换 403" 403 "$code"

echo '== 5. 小数写入与两位小数校验 =='
code=$(curl -s -o /tmp/r5.json -w '%{http_code}' -X POST "$BASE/v2/samples" -H "$OP" -H 'Content-Type: application/json' \
  -d '{"code":"E2E-DEC","title":"小数样本","quantity":100.25,"location":"A-2"}')
check "v2 样本两位小数 201" 201 "$code"
sid=$($PY -c 'import json;print(json.load(open("/tmp/r5.json"))["id"])')
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/v2/samples" -H "$OP" -H 'Content-Type: application/json' \
  -d '{"code":"E2E-DEC3","title":"三位小数","quantity":1.234,"location":"A-2"}')
check "v2 拒绝三位小数 422" 422 "$code"
code=$(curl -s -o /tmp/r6.json -w '%{http_code}' -X POST "$BASE/v2/transfers" -H "$OP" -H 'Content-Type: application/json' \
  -d "{\"code\":\"E2E-T1\",\"sample_id\":$sid,\"destination\":\"理化检测室\",\"quantity\":30.5}")
check "v2 移交小数 201" 201 "$code"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/v2/transfers" -H "$OP" -H 'Content-Type: application/json' \
  -d "{\"code\":\"E2E-T2\",\"sample_id\":$sid,\"destination\":\"理化检测室\",\"quantity\":100.26}")
check "移交超当次样本量 422" 422 "$code"

echo '== 6. 小数并发演练：真实 worker + 数量守恒 =='
# 用上一步成功的移交 E2E-T1
tfer=$(curl -s "$BASE/transfers" -H "$OP" | $PY -c 'import sys,json;d=json.load(sys.stdin);print(next(x["id"] for x in d if x["code"]=="E2E-T1"))')
curl -s -X POST "$BASE/trials" -H "$OP" -H 'Content-Type: application/json' \
  -d "{\"name\":\"e2e-decimal-trial\",\"transfer_id\":$tfer,\"timeout_ms\":250}" > /tmp/r7.json
trial_id=$($PY -c 'import json;print(json.load(open("/tmp/r7.json"))["id"])')
for i in $(seq 1 30); do
  stt=$(curl -s "$BASE/trials/$trial_id" -H "$OP")
  echo "$stt" | $PY -c 'import sys,json;t=json.load(sys.stdin);sys.exit(0 if t["status"] in ("completed","failed") else 1)' && break
  sleep 0.5
done
echo "$stt" | $PY -c 'import sys,json;t=json.load(sys.stdin);r=t["result"];assert t["status"]=="completed",t;assert r["invariant_passed"],r;assert r["remaining"]==69.75 and r["received"]==30.5 and r["receipt_count"]==1,r;print("PASS: 小数演练守恒",r["remaining"],"+",r["received"],"=",r["initial"])'

echo '== 7. 回退后小数写入被拒，旧接口仍按整数办理 =='
code=$(curl -s -o /tmp/r8.json -w '%{http_code}' -X POST "$BASE/interface/rollback-integer" -H "$ADMIN")
check "回退 200" 200 "$code"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/v2/samples" -H "$OP" -H 'Content-Type: application/json' \
  -d '{"code":"E2E-AFTER","title":"回退后小数","quantity":1.5,"location":"A-2"}')
check "回退后 v2 写入 409" 409 "$code"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/samples" -H "$OP" -H 'Content-Type: application/json' \
  -d '{"code":"E2E-INT2","title":"回退后整数","quantity":9,"location":"A-2"}')
check "回退后 v1 整数仍可办 201" 201 "$code"
echo
echo 'ALL E2E CHECKS PASSED'
