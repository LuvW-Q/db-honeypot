# ============================================================================
# 数据库蜜罐与攻击行为分析系统 —— 根 Makefile
#
# 统一入口（模块化重构后的目录布局，见 specs/002-ui-console-modularization）：
#   shared/                                共享包（包根即 shared/，含部署工具链）
#   modules/m1-transaction-integration/    事务写入与 API 集成（Alembic 迁移在此）
#   modules/m2-decoy-capture/              诱饵交互与事件采集
#   modules/m3-er-constraints/             ER 与完整性约束（仅文档/SQL/测试）
#   modules/m4-rules-derived/              规则与派生数据
#   modules/m5-views-console/              分析视图与控制台（含 frontend/）
#
# 约定：
#   - 只依赖仓库内 .venv、Python 解释器、docker compose 与 corepack pnpm；
#     不依赖全局 `uv`（存在时仅在 install/sync 中可选使用），不写死任何本机路径。
#   - PYTHONPATH 统一由本文件导出，命令行直接执行 `make xxx` 即可。
#   - 需要数据库数据的目标（verify*/capture/token-audit 等）请先
#     `make db-up && make migrate && make seed`。
#
# 使用 `make` 或 `make help` 查看全部目标。
# ============================================================================

SHELL := /bin/bash
.DEFAULT_GOAL := help

# ---- 解释器与虚拟环境 -------------------------------------------------------
VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(PY) -m pip

# ---- 路径变量（全部相对仓库根，可覆盖） -------------------------------------
MODULES_DIR ?= modules
M1_DIR := $(MODULES_DIR)/m1-transaction-integration
M2_DIR := $(MODULES_DIR)/m2-decoy-capture
M3_DIR := $(MODULES_DIR)/m3-er-constraints
M4_DIR := $(MODULES_DIR)/m4-rules-derived
M5_DIR := $(MODULES_DIR)/m5-views-console
FRONTEND_DIR ?= $(M5_DIR)/frontend
WEB_DIST_DIR ?= $(M5_DIR)/frontend/dist
EVIDENCE_DIR ?= $(M5_DIR)/evidence/deploy
VISUAL_EVIDENCE_DIR ?= $(M5_DIR)/evidence/visual

# ---- 运行参数 ---------------------------------------------------------------
API_HOST ?= 127.0.0.1
API_PORT ?= 8000
API_BASE_URL ?= http://$(API_HOST):$(API_PORT)
COMPOSE ?= docker compose
PNPM ?= corepack pnpm
NODE ?= node
PYTEST_ARGS ?=
VERIFY_ARGS ?=
RUFF ?= $(PY) -m ruff

# ---- 环境导出 ---------------------------------------------------------------
# 仓库根 + 四个包目录；M3 无运行时 Python 包（仅文档/SQL/测试）。
export PYTHONPATH := .:$(M1_DIR):$(M2_DIR):$(M4_DIR):$(M5_DIR)$(if $(PYTHONPATH),:$(PYTHONPATH))
export WEB_DIST_DIR
# Playwright 浏览器缓存：本机沙箱常无法写 ~/Library/Caches，统一落到 /tmp
export PLAYWRIGHT_BROWSERS_PATH ?= /tmp/pw-browsers
# corepack 缓存：沙箱下 HOME 缓存目录常不可写（EPERM），统一落到 /tmp（可覆盖）
export COREPACK_HOME ?= /tmp/dbh-corepack

# ============================================================================
# 帮助
# ============================================================================
.PHONY: help
help: ## 显示本帮助（默认目标）
	@echo "数据库蜜罐系统 —— 常用目标（用 make <目标> 执行）"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "示例：make db-up && make migrate && make seed && make api"
	@echo "      make frontend-build   # 构建控制台产物（后端统一托管）"
	@echo "      make verify           # 13 步部署验收（需 Docker + 前端产物）"

# ============================================================================
# 依赖安装
# ============================================================================
.PHONY: install sync
install: ## 创建 .venv 并安装全部依赖（含 dev；有 uv 时走 uv sync）
	@if [ ! -x "$(PY)" ]; then \
		echo "创建虚拟环境 $(VENV)（python3 -m venv）…"; \
		python3 -m venv $(VENV); \
	fi
	@if command -v uv >/dev/null 2>&1; then \
		echo "使用 uv sync --extra dev（项目环境 $(CURDIR)/$(VENV)）…"; \
		UV_PROJECT_ENVIRONMENT="$(CURDIR)/$(VENV)" UV_CACHE_DIR="$${UV_CACHE_DIR:-/tmp/uv-cache}" uv sync --extra dev; \
	else \
		echo "未找到 uv，使用 pip 安装（等价 dev 依赖）…"; \
		$(PIP) install -U pip; \
		$(PIP) install -e ".[dev]"; \
	fi
	@$(PY) --version

sync: install ## 同步依赖（等价 install，用于依赖变更后）

# ============================================================================
# 数据库（容器 MySQL + 宿主后端）
# ============================================================================
.PHONY: db-up db-down migrate seed reset-demo demo honeypot
db-up: ## 启动 MySQL 容器并等待健康
	$(COMPOSE) up -d mysql
	@set -a; . ./.env; set +a; \
	for i in $$(seq 1 30); do \
		if $(COMPOSE) exec -T mysql mysqladmin ping -h 127.0.0.1 -uroot -p"$$MYSQL_ROOT_PASSWORD" --silent >/dev/null 2>&1; then \
			echo "MySQL 已就绪（容器 dbhoneypot-mysql）"; exit 0; \
		fi; \
		sleep 2; \
	done; \
	echo "MySQL 60s 内未就绪，请检查：$(COMPOSE) logs mysql" >&2; exit 1

db-down: ## 停止并删除容器（保留数据卷；如需清空用 docker compose down -v）
	$(COMPOSE) down

migrate: ## 执行 Alembic 迁移（M1 迁移脚本，仓库根 alembic.ini）
	$(PY) -m alembic upgrade head

seed: ## 重建固定种子数据：reset → gen(200/2400) → import demo_basic
	@echo "[1/3] 清空并重建基础数据（reset_demo --yes）…"
	$(PY) -m m1_transaction_integration.cli.reset_demo --yes
	@echo "[2/3] 生成确定性的合成会话/事件（200/2400）…"
	$(PY) -m m2_decoy_capture.cli.gen_demo_data --sessions 200 --events 2400
	@echo "[3/3] 导入 demo_basic 固定样本（--set demo_basic）…"
	$(PY) -m m2_decoy_capture.cli.import_samples --set demo_basic

reset-demo: ## 仅重置演示数据（会清空观测数据，需确认）
	$(PY) -m m1_transaction_integration.cli.reset_demo --yes

demo: ## 一键演示（数据导入 → 诱饵 → 模拟器 → 概览摘要）
	bash shared/deploy/demo.sh

honeypot: ## 启动诱饵服务（模拟 MySQL，默认 127.0.0.1:3307）
	$(PY) -m m2_decoy_capture.server

# ============================================================================
# 后端 / 测试 / 质量门禁
# ============================================================================
.PHONY: api test lint format format-check structure boundary
api: ## 启动后端（uvicorn 工厂入口，开发用）
	$(PY) -m uvicorn m1_transaction_integration.api.app:create_app --factory \
		--host $(API_HOST) --port $(API_PORT)

test: ## 运行全仓 pytest（根 tests/ + 各模块 tests/ + 部署工具链单测）
	$(PY) -m pytest tests shared/tests modules shared/deploy/tests $(PYTEST_ARGS) -q

lint: ## 静态检查（ruff check）
	$(RUFF) check .

format: ## 自动格式化（ruff format）
	$(RUFF) format .

format-check: ## 校验格式（ruff format --check）
	$(RUFF) format --check .

structure: ## 目录结构门禁（旧布局残留/命名/必需文件）
	$(PY) -m shared.deploy.check_structure

boundary: ## 模块边界门禁（依赖矩阵 + 公开门面）
	$(PY) -m shared.deploy.check_boundaries

# ============================================================================
# 前端（模块化后位于 M5，构建产物由后端统一托管）
# ============================================================================
.PHONY: frontend-install frontend-build frontend-dev
frontend-install: ## 安装前端依赖（corepack pnpm，锁定 pnpm 版本）
	cd $(FRONTEND_DIR) && $(PNPM) install --frozen-lockfile

frontend-build: ## 构建控制台产物到 $(WEB_DIST_DIR)
	cd $(FRONTEND_DIR) && $(PNPM) build
	@if [ ! -f "$(WEB_DIST_DIR)/index.html" ]; then \
		echo "构建产物缺失：$(WEB_DIST_DIR)/index.html" >&2; exit 1; \
	fi
	@echo "构建完成：$(WEB_DIST_DIR)"

frontend-dev: ## 前端独立开发服务器（Vite）
	cd $(FRONTEND_DIR) && $(PNPM) dev --host $(API_HOST) --port 5173

# ============================================================================
# 部署验收（contracts/deployment-verify.md：13 步；失败即停并给复现命令）
# ============================================================================
.PHONY: verify verify2 verify3 capture token-audit evidence
verify: ## 部署验收 1 轮（13 步：db/migrate/seed/build/浏览器/令牌/核对/降级/证据）
	bash shared/deploy/verify_deploy.sh --repeat 1 $(VERIFY_ARGS)

verify2: ## 视觉验收：两分辨率四页截图 + 令牌审计 + 区域清单（verify2）
	bash shared/deploy/verify_deploy.sh --visual --repeat 1 $(VERIFY_ARGS)

verify3: ## 确定性验收 3 轮（固定种子重建 + 跨轮摘要比对）
	bash shared/deploy/verify_deploy.sh --repeat 3 --compare-seed $(VERIFY_ARGS)

capture: ## 采集控制台截图基线（调用前端 verify/capture-baseline.mjs）
	@if [ ! -f "$(FRONTEND_DIR)/verify/capture-baseline.mjs" ]; then \
		echo "未找到 $(FRONTEND_DIR)/verify/capture-baseline.mjs；" >&2; \
		echo "该脚本由前端/视觉任务交付，交付后本目标自动可用。" >&2; \
		exit 2; \
	fi
	@if [ ! -f "$(WEB_DIST_DIR)/index.html" ]; then \
		echo "缺少前端产物；先执行 make frontend-build。" >&2; exit 2; \
	fi
	cd $(FRONTEND_DIR) && $(PNPM) exec node verify/capture-baseline.mjs \
		--base-url $(API_BASE_URL) --out "$(CURDIR)/$(VISUAL_EVIDENCE_DIR)/baseline"

token-audit: ## 设计令牌审计（调用前端 verify/token-audit.mjs，要求 0 违规）
	@if [ ! -f "$(FRONTEND_DIR)/verify/token-audit.mjs" ]; then \
		echo "未找到 $(FRONTEND_DIR)/verify/token-audit.mjs；" >&2; \
		echo "该脚本由前端任务交付，交付后本目标自动可用。" >&2; \
		exit 2; \
	fi
	cd $(FRONTEND_DIR) && $(PNPM) exec node verify/token-audit.mjs \
		--out "$(CURDIR)/$(EVIDENCE_DIR)"

evidence: ## 从已有证据重建 summary.md（不跑验收）
	bash shared/deploy/verify_deploy.sh --summary-only

# ============================================================================
# 清理
# ============================================================================
.PHONY: clean
clean: ## 清理缓存与前端产物（不动数据库与证据）
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov
	rm -rf $(WEB_DIST_DIR)
	find shared modules tests -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
	find shared modules tests -name '*.py[co]' -delete 2>/dev/null || true
	@echo "已清理缓存/产物；数据库与 evidence 保留。"
