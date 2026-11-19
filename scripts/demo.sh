#!/usr/bin/env bash
# ============================================================
# 数据库蜜罐系统一键演示脚本（中文说明）
#
# 流程：环境检查 → 迁移/种子提示 → 导入 demo_basic → 检查/启动诱饵 →
#       运行授权模拟器 → 打印控制台概览摘要。
#
# 安全约定：
# - 默认**不重置**数据库；仅当显式传入 --reset 时才调用 reset_demo（会清空观测数据）。
# - 只自动启动本机回环地址上的诱饵服务；API 未启动时仅提示，不擅自拉起。
# - 不执行任何未在 .env 中声明的目标连接；不修改数据库结构。
#
# 用法：
#   ./scripts/demo.sh                 # 默认 3 轮模拟
#   ./scripts/demo.sh --rounds 1      # 指定模拟轮数
#   ./scripts/demo.sh --reset         # 先重置演示数据再开始（危险，显式确认）
#   ./scripts/demo.sh --no-autostart  # 不自动启动诱饵服务，仅提示
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PY="${ROOT}/backend/.venv/bin/python"
API_BASE="http://127.0.0.1:8000"
HONEYPOT_HOST="127.0.0.1"
HONEYPOT_PORT="3307"

ROUNDS=3
DO_RESET=0
AUTO_START=1
HONEYPOT_PID=""
HONEYPOT_LOG=""

usage() {
  sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rounds)
      ROUNDS="${2:-}"
      shift 2
      ;;
    --reset)
      DO_RESET=1
      shift
      ;;
    --no-autostart)
      AUTO_START=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数：$1（使用 --help 查看用法）" >&2
      exit 2
      ;;
  esac
done

if ! [[ "${ROUNDS}" =~ ^[0-9]+$ ]] || (( ROUNDS < 1 || ROUNDS > 20 )); then
  echo "--rounds 必须是 1..20 的整数，当前：${ROUNDS}" >&2
  exit 2
fi

# 脚本退出时清理自动启动的诱饵进程（只清理本脚本拉起的 PID）
cleanup() {
  if [[ -n "${HONEYPOT_PID}" ]] && kill -0 "${HONEYPOT_PID}" 2>/dev/null; then
    echo "正在停止本脚本启动的诱饵服务（PID ${HONEYPOT_PID}）…"
    kill "${HONEYPOT_PID}" 2>/dev/null || true
    wait "${HONEYPOT_PID}" 2>/dev/null || true
  fi
  [[ -n "${HONEYPOT_LOG}" && -f "${HONEYPOT_LOG}" ]] && rm -f "${HONEYPOT_LOG}"
}
trap cleanup EXIT

section() {
  echo
  echo "============================================================"
  echo "$1"
  echo "============================================================"
}

port_open() {
  local host="$1" port="$2"
  (exec 3<>"/dev/tcp/${host}/${port}") 2>/dev/null || return 1
  exec 3>&- 2>/dev/null || true
  return 0
}

section "0. 环境检查"
if [[ ! -f "${ROOT}/.env" ]]; then
  echo "未找到 .env，请先执行：cp .env.example .env" >&2
  exit 1
fi
echo ".env 已就绪：${ROOT}/.env"
if [[ ! -x "${PY}" ]]; then
  echo "未找到后端虚拟环境：${PY}" >&2
  echo "请先执行：make setup" >&2
  exit 1
fi
echo "Python：$(${PY} --version 2>/dev/null || echo 未知)"

if ! (cd "${ROOT}/backend" && "${PY}" - <<'PY' >/dev/null 2>&1
import asyncio

from sqlalchemy import text

from app.db.session import get_rw_engine, get_rw_factory


async def main() -> None:
    async with get_rw_factory()() as db:
        count = (await db.execute(text("SELECT COUNT(*) FROM detection_rules"))).scalar_one()
    await get_rw_engine().dispose()
    if int(count or 0) < 5:
        raise SystemExit(1)


asyncio.run(main())
PY
); then
  echo "数据库不可达，或迁移/种子未执行。" >&2
  echo "请先执行：make db-up && make migrate && make seed" >&2
  exit 1
fi
echo "数据库连接正常，检测规则已就绪。"
echo "提示：若首次运行，请确认已执行 make migrate && make seed（本脚本不会自动迁移）。"

if (( DO_RESET == 1 )); then
  section "1. 重置演示数据（显式 --reset）"
  echo "警告：将清空 alerts/rule_hits/attack_log/attacker_intent/attacker_profile/sessions。"
  (cd "${ROOT}/backend" && "${PY}" -m app.cli.reset_demo --yes) || {
    echo "重置失败，终止演示。" >&2
    exit 1
  }
else
  section "1. 演示数据重置（跳过）"
  echo "默认不重置数据；如需从空库演示，请追加 --reset 参数（会清空观测数据）。"
fi

section "2. 导入固定合成样本 demo_basic"
IMPORT_LOG="$(mktemp /tmp/dbhoneypot-import.XXXXXX.json)"
if (cd "${ROOT}/backend" && "${PY}" -m app.cli.import_samples --set demo_basic >"${IMPORT_LOG}"); then
  "${PY}" - "${IMPORT_LOG}" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(
    "导入完成：sessions={s} events={e} rule_hits={h} alerts={a}；去重 events={d}".format(
        s=payload["imported"]["sessions"],
        e=payload["imported"]["events"],
        h=payload["imported"]["rule_hits"],
        a=payload["imported"]["alerts"],
        d=payload["deduped"]["events"],
    )
)
for item in payload["samples"]:
    print(
        "  {sample}: 命中 {hits}，风险分 {score}（{level}），告警 {alerts}".format(
            sample=item["sample"],
            hits=",".join(item["rule_hits"]) or "无",
            score=item["risk_score"],
            level=item["risk_level"],
            alerts=item["alert_count"],
        )
    )
PY
else
  echo "样本导入失败，终止演示。" >&2
  rm -f "${IMPORT_LOG}"
  exit 1
fi
rm -f "${IMPORT_LOG}"

section "3. 诱饵服务检查（${HONEYPOT_HOST}:${HONEYPOT_PORT}）"
if port_open "${HONEYPOT_HOST}" "${HONEYPOT_PORT}"; then
  echo "诱饵服务已在运行：${HONEYPOT_HOST}:${HONEYPOT_PORT}"
else
  if (( AUTO_START == 1 )); then
    HONEYPOT_LOG="$(mktemp /tmp/dbhoneypot-server.XXXXXX.log)"
    echo "诱饵服务未运行，正在后台启动（日志：${HONEYPOT_LOG}）…"
    (cd "${ROOT}/backend" && nohup "${PY}" -m app.honeypot.server >"${HONEYPOT_LOG}" 2>&1 &
     echo $! >"/tmp/dbhoneypot-server.$$.pid")
    HONEYPOT_PID="$(cat "/tmp/dbhoneypot-server.$$.pid" 2>/dev/null || true)"
    rm -f "/tmp/dbhoneypot-server.$$.pid"
    for _ in $(seq 1 15); do
      port_open "${HONEYPOT_HOST}" "${HONEYPOT_PORT}" && break
      sleep 1
    done
    if port_open "${HONEYPOT_HOST}" "${HONEYPOT_PORT}"; then
      echo "诱饵服务启动成功（PID ${HONEYPOT_PID:-未知}），脚本退出时会自动停止。"
    else
      echo "诱饵服务启动失败，请查看日志：${HONEYPOT_LOG}" >&2
    fi
  else
    echo "诱饵服务未运行；请另开终端执行 make honeypot（--no-autostart 已禁用自动启动）。"
  fi
fi

section "4. 运行授权模拟器（${ROUNDS} 轮）"
if port_open "${HONEYPOT_HOST}" "${HONEYPOT_PORT}"; then
  if ! (cd "${ROOT}/backend" && "${PY}" -m app.cli.simulate_traffic \
      --target "${HONEYPOT_HOST}:${HONEYPOT_PORT}" --rounds "${ROUNDS}"); then
    echo "模拟器执行失败（可能是运行环境问题，演示继续）。" >&2
  fi
else
  echo "跳过模拟器：诱饵服务未运行。"
fi

section "5. 控制台概览摘要"
if port_open 127.0.0.1 8000; then
  echo "API 已运行：${API_BASE}"
  echo -n "健康检查："
  curl -s --max-time 5 "${API_BASE}/api/health" || echo "（请求失败）"
  echo
  echo -n "概览："
  curl -s --max-time 5 "${API_BASE}/api/overview" || echo "（请求失败）"
  echo
  echo -n "攻击者 Top1："
  curl -s --max-time 5 "${API_BASE}/api/attackers?page=1&page_size=1&sort=risk_score" \
    || echo "（请求失败）"
  echo
  echo -n "最新告警："
  curl -s --max-time 5 "${API_BASE}/api/alerts?page=1&page_size=3" || echo "（请求失败）"
  echo
else
  echo "API 未运行；请另开终端执行 make api，然后访问 ${API_BASE} 或 make frontend-build。"
fi

section "演示完成"
echo "提示：EXPLAIN 对比可执行：cd backend && .venv/bin/python -m app.cli.explain_diff"
echo "提示：重置演示数据可执行：cd backend && .venv/bin/python -m app.cli.reset_demo --yes"
