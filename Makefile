# ============================================================
# 数据库蜜罐系统常用命令（中文说明）
# 约定：所有命令在仓库根目录执行；.env 必须存在（复制 .env.example）
# ============================================================
SHELL := /bin/bash
UV := $(HOME)/Desktop/2026.11数据库项目/.venv/bin/uv
PNPM := COREPACK_HOME=/tmp/corepack corepack pnpm

.PHONY: help env setup db-up db-down migrate seed api honeypot frontend-build dev test reset demo explain lint clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

env: ## 从模板生成本地 .env（已存在则跳过）
	@test -f .env || cp .env.example .env && echo ".env 就绪"

db-up: ## 启动 MySQL 8（隔离网段 172.28.0.0/24）
	docker compose up -d mysql
	@echo "等待 MySQL 健康检查..."
	@until docker exec dbhoneypot-mysql mysqladmin ping -uroot -p"$$(grep '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2)" --silent 2>/dev/null; do sleep 2; done
	@echo "MySQL 已就绪"

db-down: ## 停止 MySQL（保留数据卷）
	docker compose stop mysql

setup: env db-up ## 首次初始化：环境 + 数据库 + 依赖
	cd backend && UV_CACHE_DIR=/tmp/uv-cache $(UV) sync --extra dev --python 3.14

migrate: ## 执行数据库迁移（含视图/索引/规则种子）
	cd backend && .venv/bin/alembic upgrade head

seed: ## 导入规则与诱饵种子数据
	cd backend && .venv/bin/python -m app.cli.seed --all

api: ## 启动 FastAPI（8000）
	cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

honeypot: ## 启动诱饵 MySQL 服务（3307）
	cd backend && .venv/bin/python -m app.honeypot.server

frontend-build: ## 构建前端产物
	cd frontend && $(PNPM) install --frozen-lockfile 2>/dev/null || $(PNPM) install
	cd frontend && $(PNPM) build

dev: ## 前端开发模式（5173，需另开 API）
	cd frontend && $(PNPM) dev

test: ## 运行后端测试
	cd backend && .venv/bin/pytest -q

lint: ## 后端静态检查
	cd backend && .venv/bin/ruff check app tests

reset: ## 重置演示数据（保留规则与诱饵）
	cd backend && .venv/bin/python -m app.cli.reset_demo --yes

demo: ## 一键演示：导入样本并打印概览
	cd backend && .venv/bin/python -m app.cli.import_samples --set demo_basic

explain: ## 生成索引前后查询计划对比
	cd backend && .venv/bin/python -m app.cli.explain_diff

clean: ## 清理运行缓存（不删数据库）
	rm -rf backend/.pytest_cache backend/.ruff_cache frontend/dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
