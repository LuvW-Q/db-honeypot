#!/usr/bin/env bash
# ============================================================
# 部署验收主脚本（contracts/deployment-verify.md §3 的 13 步实现）
#
# 位置：shared/deploy/verify_deploy.sh
#
# 设计原则：
# - 在**真实部署路径**上验收：生产构建产物 → 后端统一托管 → 单地址；
# - 一条命令可重复执行，失败即停，并打印 `[k/13] PASS|FAIL 名称` 与复现命令；
# - 统一使用仓库根 `.venv`（可用 PYTHON 环境变量覆盖），模块通过 PYTHONPATH 显式
#   加入，不依赖 editable 安装的 .pth；
# - 关键产物写入 modules/m5-views-console/evidence/deploy/run-N/；
# - 结束时停止后端、恢复 MySQL 容器（--keep 除外），不修改仓库源码。
#
# 用法（仓库根执行）：
#   bash shared/deploy/verify_deploy.sh [选项]
#
# 选项：
#   --base-url URL      验收地址（指定后不再启动后端），默认 http://127.0.0.1:8000
#   --port PORT         未指定 --base-url 时启动后端的端口，默认 8000
#   --repeat N          连续执行 N 轮（SC-024 要求 3），默认 1
#   --skip-build        复用已有 dist（调试用；正式验收禁用）
#   --offline           断网验证（外部断网后加此参数；跳过需要下载的步骤）
#   --keep              结束后保留后端进程与容器（调试）
#   --json              额外在 stdout 末尾输出机器可读摘要
#   --evidence-dir DIR  证据根目录，默认 modules/m5-views-console/evidence/deploy
#   --visual            verify2 模式：两分辨率四页截图 + 令牌审计 + 区域清单
#   --compare-seed      verify3 模式附加项：比对多轮固定种子数据的确定性摘要
#   --summary-only      verify-evidence：仅从已有 run-N/ 重建 summary.md
#   -h, --help          显示帮助
#
# 退出码：0 全通过；1 检查/步骤失败；2 前置条件缺失。
# ============================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

FRONTEND_DIR="${ROOT}/modules/m5-views-console/frontend"
WEB_DIST_DIR="${ROOT}/modules/m5-views-console/frontend/dist"
DEFAULT_EVIDENCE="${ROOT}/modules/m5-views-console/evidence/deploy"
VISUAL_EVIDENCE="${ROOT}/modules/m5-views-console/evidence/visual"

# 统一 PYTHONPATH：仓库根 + 四个包目录（M3 无运行时包）
export PYTHONPATH="${ROOT}:${ROOT}/modules/m1-transaction-integration:${ROOT}/modules/m2-decoy-capture:${ROOT}/modules/m4-rules-derived:${ROOT}/modules/m5-views-console${PYTHONPATH:+:${PYTHONPATH}}"

# Playwright 浏览器缓存：本机 iCloud/沙箱环境下 ~/Library/Caches 可能不可写，
# 默认落在 /tmp（与前端负责人的验收环境保持一致）；可用同名变量覆盖。
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/tmp/pw-browsers}"
# corepack 缓存：沙箱下 HOME 缓存目录可能 EPERM，默认落到 /tmp；可用同名变量覆盖。
export COREPACK_HOME="${COREPACK_HOME:-/tmp/dbh-corepack}"

PY="${PYTHON:-}"
if [[ -z "${PY}" ]]; then
  if [[ -x "${ROOT}/.venv/bin/python" ]]; then
    PY="${ROOT}/.venv/bin/python"
  else
    PY="$(command -v python3 || true)"
  fi
fi

# ---- 默认参数 ----
BASE_URL=""
PORT=8000
REPEAT=1
SKIP_BUILD=0
OFFLINE=0
KEEP=0
JSON_OUT=0
MODE="full"          # full | visual | summary
COMPARE_SEED=0
EVIDENCE_DIR="${DEFAULT_EVIDENCE}"

# ---- 运行时状态 ----
BACKEND_PID=""
BACKEND_LOG=""
MYSQL_STOPPED=0
ROUND=0
RUN_DIR=""
STATE_DIR="$(mktemp -d /tmp/dbhoneypot-verify.XXXXXX)"
STARTED_AT="$(date '+%Y-%m-%dT%H:%M:%S%z')"
OVERALL_RESULT="pass"
STEP_INDEX=0
TOTAL_STEPS=13

usage() {
  sed -n '2,34p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url)
      BASE_URL="${2:-}"
      shift 2
      ;;
    --port)
      PORT="${2:-}"
      shift 2
      ;;
    --repeat)
      REPEAT="${2:-}"
      shift 2
      ;;
    --skip-build)
      SKIP_BUILD=1
      shift
      ;;
    --offline)
      OFFLINE=1
      shift
      ;;
    --keep)
      KEEP=1
      shift
      ;;
    --json)
      JSON_OUT=1
      shift
      ;;
    --evidence-dir)
      EVIDENCE_DIR="${2:-}"
      shift 2
      ;;
    --visual)
      MODE="visual"
      shift
      ;;
    --compare-seed)
      COMPARE_SEED=1
      shift
      ;;
    --summary-only)
      MODE="summary"
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

if ! [[ "${REPEAT}" =~ ^[0-9]+$ ]] || (( REPEAT < 1 || REPEAT > 5 )); then
  echo "--repeat 必须是 1..5 的整数，当前：${REPEAT}" >&2
  exit 2
fi
if ! [[ "${PORT}" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then
  echo "--port 必须是 1..65535 的整数，当前：${PORT}" >&2
  exit 2
fi

case "${MODE}" in
  full) TOTAL_STEPS=13 ;;
  # 视觉模式同样打印 13 步编号，其中 10/11 标记为跳过，便于对照契约步骤编号
  visual) TOTAL_STEPS=13 ;;
  summary) TOTAL_STEPS=1 ;;
esac

# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

section() {
  echo
  echo "============================================================"
  echo "$1"
  echo "============================================================"
}

print_step() {
  local idx="$1" status="$2" name="$3" detail="${4:-}"
  local suffix=""
  [[ -n "${detail}" ]] && suffix="（${detail}）"
  echo "[${idx}/${TOTAL_STEPS}] ${status} ${name}${suffix}"
}

record_step() {
  local idx="$1" page_name="$2" status="$3" detail="${4:-}"
  printf '%s\t%s\t%s\t%s\n' "${idx}" "${page_name}" "${status}" "${detail}" >>"${RUN_DIR}/steps.tsv"
}

pass_step() {
  local idx="$1" name="$2" detail="${3:-}"
  print_step "${idx}" "PASS" "${name}" "${detail}"
  record_step "${idx}" "${name}" "ok" "${detail}"
}

skip_step() {
  local idx="$1" name="$2" detail="${3:-}"
  print_step "${idx}" "SKIP" "${name}" "${detail}"
  record_step "${idx}" "${name}" "skip" "${detail}"
}

repro_for() {
  case "$1" in
    1) echo "cp .env.example .env && make db-up && make install && make frontend-install" ;;
    2) echo "docker compose up -d mysql && docker compose ps" ;;
    3) echo "make migrate" ;;
    4) echo "make seed" ;;
    5) echo "make frontend-build" ;;
    6) echo "make api" ;;
    7) echo "curl -sS ${BASE_URL}/api/health -i" ;;
    8) echo "make frontend-build && make verify（浏览器检查：corepack pnpm --dir modules/m5-views-console/frontend exec node verify/run-check.mjs --base-url ${BASE_URL}）" ;;
    9) echo "make token-audit" ;;
    10) echo "make verify（页面-数据库核对：${PY} -m m5_views_console.cli.verify_views --check-pages）" ;;
    11) echo "docker compose stop mysql && curl -sS ${BASE_URL}/api/health -i && docker compose start mysql" ;;
    12) echo "make evidence" ;;
    13) echo "make verify" ;;
    *) echo "make verify" ;;
  esac
}

tail_log() {
  local log="$1"
  if [[ -f "${log}" ]]; then
    echo "---- ${log}（末 30 行）----"
    tail -n 30 "${log}" || true
    echo "----"
  fi
}

cleanup() {
  local rc=$?
  if (( KEEP == 0 )); then
    stop_backend || true
  fi
  if (( MYSQL_STOPPED == 1 )); then
    echo "恢复 MySQL 容器（降级验证清理）…"
    ( cd "${ROOT}" && docker compose start mysql >/dev/null 2>&1 ) || true
    MYSQL_STOPPED=0
  fi
  rm -f "${STATE_DIR}/backend.pid" 2>/dev/null || true
  rm -rf "${STATE_DIR}" 2>/dev/null || true
  return "${rc}"
}
trap cleanup EXIT

stop_backend() {
  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    echo "停止后端进程（PID ${BACKEND_PID}）…"
    kill "${BACKEND_PID}" 2>/dev/null || true
    for _ in $(seq 1 10); do
      kill -0 "${BACKEND_PID}" 2>/dev/null || break
      sleep 0.3
    done
    kill -9 "${BACKEND_PID}" 2>/dev/null || true
    wait "${BACKEND_PID}" 2>/dev/null || true
  fi
  BACKEND_PID=""
}

http_code() {
  curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$1" 2>/dev/null || echo "000"
}

http_content_type() {
  curl -sS -o /dev/null -w '%{content_type}' --max-time 10 "$1" 2>/dev/null || echo ""
}

wait_http_code() {
  local url="$1" expected="$2" timeout="$3" elapsed=0
  while (( elapsed < timeout )); do
    if [[ "$(http_code "${url}")" == "${expected}" ]]; then
      return 0
    fi
    sleep 1
    elapsed=$(( elapsed + 1 ))
  done
  return 1
}

run_logged() {
  local log="$1"
  shift
  local rc=0
  "$@" >"${log}" 2>&1 || rc=$?
  return "${rc}"
}

run_with_timeout() {
  # 用法：run_with_timeout 秒数 日志 命令...
  local secs="$1" log="$2"
  shift 2
  local rc=0
  "$@" >"${log}" 2>&1 &
  local pid=$!
  local waited=0
  while kill -0 "${pid}" 2>/dev/null; do
    if (( waited >= secs )); then
      echo "命令超时（${secs}s），终止进程 ${pid}" >>"${log}"
      kill -TERM "${pid}" 2>/dev/null || true
      sleep 1
      kill -9 "${pid}" 2>/dev/null || true
      wait "${pid}" 2>/dev/null || true
      return 124
    fi
    sleep 1
    waited=$(( waited + 1 ))
  done
  wait "${pid}" 2>/dev/null || rc=$?
  return "${rc}"
}

write_record() {
  local result="$1"
  if [[ -z "${RUN_DIR}" || ! -d "${RUN_DIR}" ]]; then
    return 0
  fi
  FINISHED_AT="$(date '+%Y-%m-%dT%H:%M:%S%z')"
  "${PY}" - "${RUN_DIR}" "${BASE_URL}" "${STARTED_AT}" "${FINISHED_AT}" "${result}" \
    <<'PY' >"${RUN_DIR}/deploy-record.json" 2>/dev/null || true
import json
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])
base_url, started_at, finished_at, result = sys.argv[2:6]

steps = []
steps_file = run_dir / "steps.tsv"
if steps_file.is_file():
    for line in steps_file.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 4:
            steps.append(
                {"name": parts[1], "status": parts[2], "detail": parts[3], "index": int(parts[0])}
            )


def load(name):
    path = run_dir / name
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


browser = load("browser.json") or {}
token = load("token-audit.json") or {}
sql_ui = load("sql-ui.json") or {}
pages = []
for page in browser.get("pages", []) if isinstance(browser, dict) else []:
    console_errors = page.get("console_errors") or []
    failed_requests = page.get("failed_requests") or []
    http_errors = page.get("http_errors") or []
    external_requests = page.get("external_requests") or []
    status = page.get("status")
    if not status:
        status = (
            "ok"
            if not (console_errors or failed_requests or http_errors or external_requests)
            else "fail"
        )
    pages.append(
        {
            "route": page.get("route"),
            "page": page.get("page"),
            "status": status,
            "viewport": page.get("viewport"),
            "console_errors": len(console_errors),
            "failed_requests": len(failed_requests),
            "http_errors": len(http_errors),
            "external_requests": len(external_requests),
            "horizontal_overflow": bool(page.get("overflow")),
            "fonts_ready": bool(page.get("fonts_ready")),
            "screenshots": [page.get("screenshot")] if page.get("screenshot") else [],
        }
    )

payload = {
    "started_at": started_at,
    "finished_at": finished_at,
    "base_url": base_url,
    "steps": steps,
    "pages": pages,
    "token_audit": {
        "violations": len(token.get("violations") or []),
        "checked_files": token.get("checked_files", 0),
    },
    "sql_ui": {
        "result": sql_ui.get("result"),
        "assertions_total": (sql_ui.get("summary") or {}).get("assertions_total"),
        "assertions_passed": (sql_ui.get("summary") or {}).get("assertions_passed"),
        "page_checks_total": (sql_ui.get("summary") or {}).get("page_checks_total"),
        "page_checks_passed": (sql_ui.get("summary") or {}).get("page_checks_passed"),
        "failed": (sql_ui.get("summary") or {}).get("failed") or [],
        "page_errors": sql_ui.get("page_errors") or [],
    },
    "result": result,
}
(run_dir / "deploy-record.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
)
PY
}

fail_step() {
  local idx="$1" name="$2"
  local repro
  repro="$(repro_for "${idx}")"
  print_step "${idx}" "FAIL" "${name}"
  record_step "${idx}" "${name}" "fail" "见复现命令"
  echo "复现命令：${repro}"
  tail_log "${BACKEND_LOG:-/dev/null}"
  if [[ -f "${RUN_DIR}/browser.log" ]]; then tail_log "${RUN_DIR}/browser.log"; fi
  if [[ -f "${RUN_DIR}/token-audit.log" ]]; then tail_log "${RUN_DIR}/token-audit.log"; fi
  OVERALL_RESULT="fail"
  write_record "fail"
  exit 1
}

die_precondition() {
  echo "[0/${TOTAL_STEPS}] FAIL 前置条件：$1" >&2
  echo "修复建议：$2" >&2
  exit 2
}

load_env() {
  if [[ ! -f "${ROOT}/.env" ]]; then
    die_precondition "缺少仓库根 .env" "cp .env.example .env 后按注释确认 TEST-ONLY 占位值"
  fi
  set -a
  # shellcheck disable=SC1091
  . "${ROOT}/.env"
  set +a
}

# ---------------------------------------------------------------------------
# 各步骤实现
# ---------------------------------------------------------------------------

check_preconditions() {
  load_env
  [[ -n "${DATABASE_URL:-}" ]] || die_precondition ".env 缺少 DATABASE_URL" "按 .env.example 补齐数据库连接串"
  command -v docker >/dev/null 2>&1 || die_precondition "未找到 docker 命令" "安装 Docker Desktop 并启动"
  ( cd "${ROOT}" && docker compose version >/dev/null 2>&1 ) \
    || die_precondition "Docker Compose v2 不可用" "确认 docker compose version 可用"
  ( cd "${ROOT}" && docker compose ps >/dev/null 2>&1 ) \
    || die_precondition "Docker daemon 不可用" "启动 Docker Desktop 后重试"
  [[ -x "${PY}" ]] || die_precondition "未找到 Python 解释器：${PY}" "make install（或 PYTHON=/path/to/python）"
  "${PY}" -c "import shared, m1_transaction_integration, m2_decoy_capture, m4_rules_derived, m5_views_console" \
    >/dev/null 2>&1 \
    || die_precondition "Python 依赖/包导入失败" "make install（uv sync --extra dev）"
  command -v node >/dev/null 2>&1 || die_precondition "未找到 node（需要 Node 24）" "安装 Node 24 并确保 node 在 PATH"
  command -v corepack >/dev/null 2>&1 || die_precondition "未找到 corepack" "Node 24 自带 corepack；确认 node 安装完整"
  [[ -d "${FRONTEND_DIR}/node_modules" ]] \
    || die_precondition "前端依赖未安装" "make frontend-install"
  if [[ -f "${FRONTEND_DIR}/verify/run-check.mjs" ]]; then
    ( cd "${FRONTEND_DIR}" && corepack pnpm exec playwright --version >/dev/null 2>&1 ) \
      || die_precondition "Playwright 不可用" "corepack pnpm --dir modules/m5-views-console/frontend exec playwright install chromium"
  fi
  if [[ "${MANAGED_BACKEND}" == "1" ]]; then
    if ! "${PY}" - "${PORT}" <<'PY' >/dev/null 2>&1
import socket
import sys

sock = socket.socket()
try:
    sock.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
    then
      die_precondition "端口 ${PORT} 不可用" "关闭占用进程或使用 --port 指定其他端口"
    fi
  fi
  mkdir -p "${EVIDENCE_DIR}"
  pass_step 1 "前置检查" "docker/python/node/playwright/端口就绪"
}

step_db_up() {
  local log="${RUN_DIR}/db-up.log"
  if ! run_logged "${log}" bash -c "cd '${ROOT}' && docker compose up -d mysql"; then
    fail_step 2 "启动数据库"
  fi
  local elapsed=0
  while (( elapsed < 60 )); do
    if ( cd "${ROOT}" && docker compose exec -T mysql mysqladmin ping -h 127.0.0.1 -uroot \
        -p"${MYSQL_ROOT_PASSWORD}" --silent >/dev/null 2>&1 ); then
      pass_step 2 "启动数据库" "MySQL 健康"
      return 0
    fi
    sleep 2
    elapsed=$(( elapsed + 2 ))
  done
  tail_log "${log}"
  fail_step 2 "启动数据库"
}

step_migrate() {
  local log="${RUN_DIR}/migrate.log"
  ( cd "${ROOT}" && "${PY}" -m alembic upgrade head ) >"${log}" 2>&1 || fail_step 3 "数据库迁移"
  pass_step 3 "数据库迁移" "alembic upgrade head"
}

seed_digest() {
  # 用固定种子序列的 JSON 摘要计算确定性指纹（reset 的删除行数不参与）
  "${PY}" - "${RUN_DIR}/seed-gen.json" "${RUN_DIR}/seed-import.json" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

# 只保留可复现的数据事实：剔除生成时间、耗时、连接信息等每次运行都会变化的字段，
# 否则跨轮摘要比对（make verify3 --compare-seed）会误报不一致。
VOLATILE_KEYS = {
    "generated_at",
    "started_at",
    "finished_at",
    "timestamp",
    "elapsed_ms",
    "duration_ms",
    "database",
    # 告警主键是自增 ID，每次重建都会变化；告警数量由 alert_count 体现
    "alerts",
    "new_alerts",
    "alert_ids",
}


def canonical(value):
    if isinstance(value, dict):
        return {
            key: canonical(item)
            for key, item in value.items()
            if key not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [canonical(item) for item in value]
    return value


digest = hashlib.sha256()
for name in sys.argv[1:]:
    path = Path(name)
    if not path.is_file():
        raise SystemExit(1)
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = json.dumps(canonical(payload), ensure_ascii=False, sort_keys=True)
    digest.update(body.encode("utf-8"))
print(digest.hexdigest())
PY
}

step_seed() {
  local log="${RUN_DIR}/seed.log"
  : >"${log}"
  if ! "${PY}" -m m1_transaction_integration.cli.reset_demo --yes >>"${log}" 2>&1; then
    tail_log "${log}"
    fail_step 4 "固定种子数据"
  fi
  if ! "${PY}" -m m2_decoy_capture.cli.gen_demo_data --sessions 200 --events 2400 \
      >"${RUN_DIR}/seed-gen.json" 2>>"${log}"; then
    tail_log "${log}"
    fail_step 4 "固定种子数据"
  fi
  if ! "${PY}" -m m2_decoy_capture.cli.import_samples --set demo_basic \
      >"${RUN_DIR}/seed-import.json" 2>>"${log}"; then
    tail_log "${log}"
    fail_step 4 "固定种子数据"
  fi
  local digest=""
  digest="$(seed_digest 2>>"${log}" || true)"
  if [[ -z "${digest}" ]]; then
    tail_log "${log}"
    fail_step 4 "固定种子数据"
  fi
  printf '%s\n' "${digest}" >"${RUN_DIR}/seed-digest.txt"
  pass_step 4 "固定种子数据" "reset → gen(200/2400) → demo_basic；digest=${digest:0:12}…"
}

step_build_frontend() {
  local log="${RUN_DIR}/frontend-build.log"
  if (( SKIP_BUILD == 1 )); then
    [[ -f "${WEB_DIST_DIR}/index.html" ]] \
      || fail_step 5 "构建前端（复用 dist）"
    skip_step 5 "构建前端" "复用已有 dist（--skip-build，调试模式）"
  else
    if ! run_logged "${log}" bash -c \
        "cd '${FRONTEND_DIR}' && corepack pnpm build"; then
      tail_log "${log}"
      fail_step 5 "构建前端"
    fi
    [[ -f "${WEB_DIST_DIR}/index.html" ]] || fail_step 5 "构建前端（产物缺失）"
    pass_step 5 "构建前端" "vite build → ${WEB_DIST_DIR#"${ROOT}/"}"
  fi
  # 离线资源检查（ui-contracts §9 / SC-026）
  local offline_log="${RUN_DIR}/offline-assets.json"
  if ! ( cd "${ROOT}" && "${PY}" -m shared.deploy.offline_assets --dist "${WEB_DIST_DIR}" \
      --json ) >"${offline_log}" 2>&1; then
    cat "${offline_log}" >&2 || true
    fail_step 5 "离线资源检查（dist 含外链）"
  fi
}

step_start_backend() {
  if [[ "${MANAGED_BACKEND}" == "0" ]]; then
    skip_step 6 "启动后端" "使用外部 --base-url，不托管进程"
    return 0
  fi
  BACKEND_LOG="${RUN_DIR}/backend.log"
  : >"${BACKEND_LOG}"
  ( cd "${ROOT}" && "${PY}" -m uvicorn \
      m1_transaction_integration.api.app:create_app --factory \
      --host 127.0.0.1 --port "${PORT}" ) >"${BACKEND_LOG}" 2>&1 &
  BACKEND_PID=$!
  # 启动等待上限可用 BACKEND_WAIT_SECONDS 覆盖（iCloud 卷首次物化较慢）；
  # elapsed 以 0.5s 为步长累加，故循环上限为秒数 × 2。
  local wait_seconds="${BACKEND_WAIT_SECONDS:-90}"
  local elapsed=0
  while (( elapsed < wait_seconds * 2 )); do
    if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
      tail_log "${BACKEND_LOG}"
      fail_step 6 "启动后端（进程退出）"
    fi
    if "${PY}" - "${PORT}" <<'PY' >/dev/null 2>&1
import socket
import sys

sock = socket.socket()
sock.settimeout(0.5)
try:
    sock.connect(("127.0.0.1", int(sys.argv[1])))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
    then
      pass_step 6 "启动后端" "uvicorn factory（PID ${BACKEND_PID}）"
      return 0
    fi
    sleep 0.5
    elapsed=$(( elapsed + 1 ))
  done
  tail_log "${BACKEND_LOG}"
  fail_step 6 "启动后端（${wait_seconds}s 内未监听）"
}

step_health_and_static() {
  local health_url="${BASE_URL}/api/health"
  if ! wait_http_code "${health_url}" 200 30; then
    tail_log "${BACKEND_LOG:-/dev/null}"
    fail_step 7 "健康检查（/api/health 非 200）"
  fi
  local home_code
  home_code="$(http_code "${BASE_URL}/")"
  if [[ "${home_code}" != "200" ]]; then
    fail_step 7 "SPA 入口（/ 非 200，HTTP ${home_code}）"
  fi
  curl -sS --max-time 10 "${BASE_URL}/" >"${RUN_DIR}/index.html" 2>/dev/null || true
  # 静态资源：index.html 内引用的本地资源全部 200 且 content-type 正确
  local refs
  refs="$("${PY}" - "${RUN_DIR}/index.html" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
refs = []
for match in re.finditer(r'(?:src|href)\s*=\s*"([^"]+)"', text):
    value = match.group(1)
    if value.startswith(("/", "assets/")) and re.search(
        r"\.(?:js|mjs|css|svg|png|ico|woff2?)$", value
    ):
        refs.append(value if value.startswith("/") else f"/{value}")
print("\n".join(sorted(set(refs))))
PY
)"
  local asset
  while IFS= read -r asset; do
    [[ -z "${asset}" ]] && continue
    local code ctype expected
    code="$(http_code "${BASE_URL}${asset}")"
    ctype="$(http_content_type "${BASE_URL}${asset}")"
    expected=""
    case "${asset}" in
      *.js|*.mjs) expected="javascript" ;;
      *.css) expected="text/css" ;;
      *.svg) expected="image/svg+xml" ;;
      *.woff2|*.woff) expected="font" ;;
      *.png) expected="image/png" ;;
      *.ico) expected="image/" ;;
    esac
    if [[ "${code}" != "200" ]]; then
      fail_step 7 "静态资源 ${asset}（HTTP ${code}）"
    fi
    if [[ -n "${expected}" && "${ctype}" != *"${expected}"* ]]; then
      fail_step 7 "静态资源 content-type（${asset} → ${ctype}）"
    fi
  done <<<"${refs}"
  # 四页 favicon（本地 SVG）与 SPA 入口：hash 路由由浏览器检查断言页面渲染
  local favicon
  for favicon in favicon-overview.svg favicon-attackers.svg favicon-detail.svg favicon-alerts.svg; do
    local fcode
    fcode="$(http_code "${BASE_URL}/${favicon}")"
    if [[ "${fcode}" != "200" ]]; then
      fail_step 7 "四页 favicon（${favicon} → HTTP ${fcode}）"
    fi
  done
  pass_step 7 "健康检查与静态资源" "health 200；SPA 入口 + 本地资源 200/content-type；四页 favicon 200"
}

step_browser_check() {
  local out="${RUN_DIR}/browser.json"
  local script="${FRONTEND_DIR}/verify/run-check.mjs"
  if [[ ! -f "${script}" ]]; then
    fail_step 8 "浏览器检查（前端 verify/run-check.mjs 未交付）"
  fi
  # iCloud 卷偶发 ETIMEDOUT（读取 node_modules/playwright-core 时超时）。
  # 先做 require 预热（把模块读进系统缓存），再重跑完整断言；每次失败都留证据。
  local warm
  for warm in 1 2 3; do
    ( cd "${FRONTEND_DIR}" && corepack pnpm exec node -e "require('@playwright/test')" ) \
      >"${RUN_DIR}/browser-prewarm.log" 2>&1 && break
    sleep 5
  done
  local attempts="${BROWSER_CHECK_ATTEMPTS:-2}"
  local attempt=1
  while (( attempt <= attempts )); do
    if run_with_timeout 180 "${RUN_DIR}/browser.log" \
        bash -c "cd '${FRONTEND_DIR}' && corepack pnpm exec node verify/run-check.mjs \
          --base-url '${BASE_URL}' --out '${RUN_DIR}'" \
       && "${PY}" - "${out}" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload.get("result") != "pass":
    raise SystemExit(1)
if not (payload.get("pages") or []):
    raise SystemExit(1)
PY
    then
      pass_step 8 "浏览器检查" "四页 × 两视口；browser.json result=pass（第 ${attempt} 次尝试）"
      return 0
    fi
    cp "${RUN_DIR}/browser.log" "${RUN_DIR}/browser-attempt${attempt}.log" 2>/dev/null || true
    cp "${out}" "${RUN_DIR}/browser-attempt${attempt}.json" 2>/dev/null || true
    echo "[WARN] 浏览器检查第 ${attempt}/${attempts} 次未通过，已保存 browser-attempt${attempt}.log，继续完整重跑..." >&2
    attempt=$(( attempt + 1 ))
  done
  tail_log "${RUN_DIR}/browser.log"
  cat "${out}" >&2 || true
  fail_step 8 "浏览器检查（${attempts} 次完整重跑均未通过：脚本失败/超时或 result != pass）"
}

step_token_audit() {
  local out="${RUN_DIR}/token-audit.json"
  local script="${FRONTEND_DIR}/verify/token-audit.mjs"
  if [[ ! -f "${script}" ]]; then
    fail_step 9 "令牌审计（前端 verify/token-audit.mjs 未交付）"
  fi
  if ! run_with_timeout 120 "${RUN_DIR}/token-audit.log" \
      bash -c "cd '${FRONTEND_DIR}' && corepack pnpm exec node verify/token-audit.mjs \
        --out '${RUN_DIR}'"; then
    tail_log "${RUN_DIR}/token-audit.log"
    fail_step 9 "令牌审计（脚本失败/超时）"
  fi
  if ! "${PY}" - "${out}" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload.get("violations"):
    raise SystemExit(1)
if payload.get("result") != "pass":
    raise SystemExit(1)
print(payload.get("checked_files", 0))
PY
  then
    cat "${out}" >&2 || true
    fail_step 9 "令牌审计（存在违规）"
  fi
  pass_step 9 "令牌审计" "violations=0"
}

step_sql_ui() {
  if ! "${PY}" -c "import m5_views_console.cli.verify_views" >/dev/null 2>&1; then
    fail_step 10 "页面-数据库抽样（M5 verify_views 未交付）"
  fi
  local out="${RUN_DIR}/sql-ui.json"
  if ! ( cd "${ROOT}" && "${PY}" -m m5_views_console.cli.verify_views \
      --check-pages --json --base-url "${BASE_URL}" ) \
      >"${out}" 2>"${RUN_DIR}/sql-ui.log"; then
    tail_log "${RUN_DIR}/sql-ui.log"
    fail_step 10 "页面-数据库抽样"
  fi
  local detail=""
  detail="$("${PY}" - "${out}" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
summary = payload.get("summary") or {}
failed = summary.get("failed") or []
page_errors = payload.get("page_errors") or []
if payload.get("result") != "pass" or failed or page_errors:
    raise SystemExit(1)
print(
    "视图断言 {}/{}，页面核对 {}/{}".format(
        summary.get("assertions_passed", 0),
        summary.get("assertions_total", 0),
        summary.get("page_checks_passed", 0),
        summary.get("page_checks_total", 0),
    )
)
PY
)" || {
    tail_log "${RUN_DIR}/sql-ui.log"
    fail_step 10 "页面-数据库抽样（断言或页面核对未通过）"
  }
  pass_step 10 "页面-数据库抽样" "${detail}"
}

step_degrade() {
  MYSQL_STOPPED=1
  if ! run_logged "${RUN_DIR}/degrade-stop.log" bash -c "cd '${ROOT}' && docker compose stop mysql"; then
    MYSQL_STOPPED=0
    fail_step 11 "降级验证（无法停止 MySQL）"
  fi
  if ! wait_http_code "${BASE_URL}/api/health" 503 30; then
    ( cd "${ROOT}" && docker compose start mysql >/dev/null 2>&1 ) || true
    MYSQL_STOPPED=0
    fail_step 11 "降级验证（数据库停止后 health 未返回 503）"
  fi
  local home_code
  home_code="$(http_code "${BASE_URL}/")"
  if [[ "${home_code}" != "200" ]]; then
    ( cd "${ROOT}" && docker compose start mysql >/dev/null 2>&1 ) || true
    MYSQL_STOPPED=0
    fail_step 11 "降级验证（降级时 SPA 入口非 200）"
  fi
  if ! run_logged "${RUN_DIR}/degrade-start.log" bash -c "cd '${ROOT}' && docker compose start mysql"; then
    fail_step 11 "降级验证（MySQL 恢复失败）"
  fi
  local elapsed=0
  while (( elapsed < 60 )); do
    if ( cd "${ROOT}" && docker compose exec -T mysql mysqladmin ping -h 127.0.0.1 -uroot \
        -p"${MYSQL_ROOT_PASSWORD}" --silent >/dev/null 2>&1 ); then
      break
    fi
    sleep 2
    elapsed=$(( elapsed + 2 ))
  done
  MYSQL_STOPPED=0
  if ! wait_http_code "${BASE_URL}/api/health" 200 60; then
    fail_step 11 "降级验证（MySQL 恢复后 health 未恢复 200）"
  fi
  pass_step 11 "降级验证" "停库 → health 503 + SPA 可打开 → 恢复 → health 200；视觉降级条由第 8 步浏览器断言"
}

step_write_evidence() {
  if [[ "${MODE}" == "visual" ]]; then
    if [[ ! -f "${VISUAL_EVIDENCE}/region-checklist.md" ]]; then
      fail_step 12 "区域清单（evidence/visual/region-checklist.md 未交付）"
    fi
  fi
  write_record "pass"
  local copy_dir="${ROOT}/docs/screenshots"
  if [[ -d "${copy_dir}" && -d "${RUN_DIR}/screenshots" ]]; then
    local shot
    for shot in "${RUN_DIR}/screenshots"/*-1440x900.png; do
      [[ -f "${shot}" ]] || continue
      local page
      page="$(basename "${shot}" -1440x900.png)"
      if [[ ! -f "${copy_dir}/${page}.png" ]]; then
        cp "${shot}" "${copy_dir}/${page}.png" 2>/dev/null || true
      fi
    done
  fi
  pass_step 12 "写证据" "${RUN_DIR#"${ROOT}/"}"
}

step_cleanup() {
  if (( KEEP == 1 && ROUND == REPEAT )); then
    skip_step 13 "清理" "--keep：保留后端与容器（PID ${BACKEND_PID:-无}）"
    return 0
  fi
  stop_backend
  if (( MYSQL_STOPPED == 1 )); then
    ( cd "${ROOT}" && docker compose start mysql >/dev/null 2>&1 ) || true
    MYSQL_STOPPED=0
  fi
  pass_step 13 "清理" "后端已停止；MySQL 保持运行"
}

write_summary() {
  local target_dir="$1"
  local title="$2"
  "${PY}" - "${target_dir}" "${title}" <<'PY'
import json
import sys
from datetime import datetime
from pathlib import Path

target = Path(sys.argv[1])
title = sys.argv[2]
target.mkdir(parents=True, exist_ok=True)
records = []
for run_dir in sorted(target.glob("*/deploy-record.json")):
    try:
        payload = json.loads(run_dir.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    records.append((run_dir.parent.name, payload))

lines = [f"# {title}", "", f"生成时间：{datetime.now().isoformat(timespec='seconds')}", ""]
if not records:
    lines.append("暂无验收记录；先执行 `make verify`（视觉证据执行 `make verify2`）。")
else:
    lines += [
        "| 轮次 | 开始时间 | 结束时间 | 结果 | 失败步骤 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, payload in records:
        failed = [
            step.get("name") for step in payload.get("steps", []) if step.get("status") == "fail"
        ]
        lines.append(
            f"| {name} | {payload.get('started_at', '-')} | "
            f"{payload.get('finished_at', '-')} | {payload.get('result', '-')} | "
            f"{'、'.join(failed) if failed else '无'} |"
        )
    digests = []
    for run_dir in sorted(target.glob("*/seed-digest.txt")):
        digests.append(run_dir.read_text(encoding="utf-8").strip())
    if digests:
        stable = len(set(digests)) == 1
        verdict = "stable（各轮摘要一致）" if stable else "不稳定（摘要不一致）"
        lines += ["", f"固定种子数据确定性：{verdict}", ""]
        for run_dir in sorted(target.glob("*/seed-digest.txt")):
            lines.append(
                f"- {run_dir.parent.name}: `{run_dir.read_text(encoding='utf-8').strip()}`"
            )
    # 证据摘要：令牌审计 + 浏览器页面 + 区域审计（视觉证据目录存在时）
    for name, payload in records:
        token = payload.get("token_audit") or {}
        pages = payload.get("pages") or []
        if token or pages:
            lines += ["", f"### {name} 证据摘要", ""]
        if token:
            lines.append(
                f"- 令牌审计：violations={token.get('violations')}，"
                f"checked_files={token.get('checked_files')}"
            )
        if pages:
            bad = [
                page
                for page in pages
                if page.get("status") not in (None, "ok")
                or page.get("console_errors")
                or page.get("failed_requests")
                or page.get("http_errors")
                or page.get("external_requests")
                or page.get("horizontal_overflow")
            ]
            lines.append(
                f"- 浏览器页面：{len(pages)} 条（页面×视口），异常 {len(bad)} 条；"
                "console/请求错误与横向溢出均为 0"
                if not bad
                else f"- 浏览器页面：{len(pages)} 条，异常 {len(bad)} 条"
            )
    region_audit = target / "region-audit.json"
    if region_audit.is_file():
        try:
            audit = json.loads(region_audit.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            audit = {}
        if audit:
            lines.append(
                f"- 区域覆盖率：{audit.get('coverage')}%（命中 {audit.get('present')}/"
                f"{audit.get('expected')}）"
            )
    for name, _payload in records:
        shots = target / name / "screenshots"
        if shots.is_dir():
            files = sorted(shots.glob("*.png"))
            light = [item for item in files if item.name.endswith("-light.png")]
            lines.append(
                f"- 截图（{name}）：{len(files)} 张"
                f"（深色 {len(files) - len(light)} + 浅色 {len(light)}）"
            )

    lines += ["", "## 各轮步骤", ""]
    for name, payload in records:
        lines.append(f"### {name}")
        steps_file = target / name / "steps.tsv"
        steps = []
        if steps_file.is_file():
            for raw in steps_file.read_text(encoding="utf-8").splitlines():
                cells = raw.split("\t")
                if len(cells) >= 4:
                    steps.append({"status": cells[2], "name": cells[1], "detail": cells[3]})
        if not steps:
            steps = payload.get("steps", [])
        for step in steps:
            lines.append(
                f"- [{step.get('status')}] {step.get('name')}（{step.get('detail', '')}）"
            )
        lines.append("")
(target / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"已写 {target / 'summary.md'}")
PY
}

update_evidence_readme() {
  local readme="${ROOT}/modules/m5-views-console/evidence/README.md"
  [[ -f "${readme}" ]] || return 0
  "${PY}" - "${readme}" "${STARTED_AT}" <<'PY' >/dev/null 2>&1 || true
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = re.sub(r"最近验证时间：.*", f"最近验证时间：{sys.argv[2]}", text, count=1)
path.write_text(text, encoding="utf-8")
PY
}

# ---------------------------------------------------------------------------
# 单轮执行
# ---------------------------------------------------------------------------

run_round() {
  ROUND="$1"
  if [[ "${MODE}" == "visual" ]]; then
    RUN_DIR="${VISUAL_EVIDENCE}/verify-run-${ROUND}"
  else
    RUN_DIR="${EVIDENCE_DIR}/run-${ROUND}"
  fi
  rm -rf "${RUN_DIR}"
  mkdir -p "${RUN_DIR}/screenshots"
  : >"${RUN_DIR}/steps.tsv"
  STARTED_AT="$(date '+%Y-%m-%dT%H:%M:%S%z')"
  BACKEND_LOG="${RUN_DIR}/backend.log"

  section "第 ${ROUND}/${REPEAT} 轮部署验收（${BASE_URL}）"

  check_preconditions
  step_db_up
  step_migrate
  step_seed
  step_build_frontend
  step_start_backend
  step_health_and_static
  step_browser_check
  step_token_audit
  if [[ "${MODE}" == "visual" ]]; then
    skip_step 10 "页面-数据库抽样" "verify2 模式跳过（由 make verify 执行）"
    skip_step 11 "降级验证" "verify2 模式跳过（由 make verify 执行）"
  else
    step_sql_ui
    step_degrade
  fi
  step_write_evidence
  step_cleanup
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

MANAGED_BACKEND=1
if [[ -n "${BASE_URL}" ]]; then
  MANAGED_BACKEND=0
else
  BASE_URL="http://127.0.0.1:${PORT}"
fi

if [[ "${MODE}" == "summary" ]]; then
  section "从已有证据重建 summary.md"
  RUN_DIR=""
  if write_summary "${EVIDENCE_DIR}" "部署验收汇总（summary.md）" \
      && write_summary "${VISUAL_EVIDENCE}" "视觉验收汇总（verify2）"; then
    echo "[1/${TOTAL_STEPS}] PASS 证据汇总（${EVIDENCE_DIR#"${ROOT}/"}/summary.md）"
    exit 0
  fi
  echo "[1/${TOTAL_STEPS}] FAIL 证据汇总（无法写入 summary.md）" >&2
  exit 1
fi

if [[ "${MODE}" == "visual" ]]; then
  mkdir -p "${VISUAL_EVIDENCE}"
fi

if (( OFFLINE == 1 )); then
  echo "提示：--offline 只开启页面加载/外网请求断言语义；断网需在脚本外部完成。"
fi

for round in $(seq 1 "${REPEAT}"); do
  run_round "${round}"
done

if [[ "${MODE}" == "visual" ]]; then
  write_summary "${VISUAL_EVIDENCE}" "视觉验收汇总（verify2）" \
    || echo "警告：视觉 summary.md 写入失败（证据文件仍在）" >&2
else
  write_summary "${EVIDENCE_DIR}" "部署验收汇总（summary.md）" \
    || echo "警告：summary.md 写入失败（证据文件仍在）" >&2
  update_evidence_readme
fi

# 多轮确定性比对（verify3）
if (( COMPARE_SEED == 1 && REPEAT > 1 )); then
  if ! "${PY}" - "${EVIDENCE_DIR}" "${REPEAT}" <<'PY'
import sys
from pathlib import Path

evidence = Path(sys.argv[1])
digests = []
for index in range(1, int(sys.argv[2]) + 1):
    digest = evidence / f"run-{index}" / "seed-digest.txt"
    digests.append(digest.read_text(encoding="utf-8").strip() if digest.is_file() else None)
if None in digests or len(set(digests)) != 1:
    print(f"固定种子数据多轮摘要不一致：{digests}")
    raise SystemExit(1)
print(f"固定种子数据多轮摘要一致：{digests[0][:16]}…")
PY
  then
    OVERALL_RESULT="fail"
    exit 1
  fi
fi

section "验收结果"
if [[ "${MODE}" == "visual" ]]; then
  echo "证据目录：${VISUAL_EVIDENCE#"${ROOT}/"}"
else
  echo "证据目录：${EVIDENCE_DIR#"${ROOT}/"}"
fi
echo "结果：PASS（${REPEAT} 轮）"
if (( JSON_OUT == 1 )); then
  local_dir="${EVIDENCE_DIR}"
  [[ "${MODE}" == "visual" ]] && local_dir="${VISUAL_EVIDENCE}"
  "${PY}" - "${local_dir}" "${MODE}" "${REPEAT}" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
runs = []
for record in sorted(target.glob("*/deploy-record.json")):
    try:
        payload = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    runs.append({"run": record.parent.name, "result": payload.get("result")})
print(
    json.dumps(
        {"mode": sys.argv[2], "repeat": int(sys.argv[3]), "runs": runs, "result": "pass"},
        ensure_ascii=False,
    )
)
PY
fi
