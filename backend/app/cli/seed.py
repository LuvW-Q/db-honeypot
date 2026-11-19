"""种子数据导入 CLI（幂等）：`python -m app.cli.seed --all`。

职责（data-model 10.1 / 10.4 / 10.5）：

1. 确保检测规则 R01–R05 存在：若迁移已种入则跳过，缺失才补种 v1；
2. 导入 30 条 `fake_users`、120 条 `fake_orders`、5 条 `fake_config`，
   全部为确定性虚构数据（邮箱 example.com、手机号 1380000xxxx、
   `password_hash` 为带 TEST-ONLY 前缀的 bcrypt 形状伪哈希，不可用）；
3. 每次执行写一条 `audit_log(operation='migration', result='success')`；
4. 输出固定 JSON：`{"rules":5,"fake_users":30,"fake_orders":120,"fake_config":5}`。

幂等实现：规则按 `(rule_code, rule_version)` 判存；诱饵数据使用
`INSERT ... ON DUPLICATE KEY UPDATE`（按 username / order_no / config_key 唯一键），
重复执行不新增行、不改变行数。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.config import settings
from app.db.session import get_rw_engine, get_rw_factory

# ---------------------------------------------------------------------------
# 规则种子定义（与迁移 0004_seed_rules 完全一致，data-model 10.2）
# ---------------------------------------------------------------------------

RULE_SEEDS: list[dict[str, Any]] = [
    {
        "rule_code": "R01",
        "rule_name": "短时高频连接扫描",
        "rule_type": "frequency",
        "intent_type": "scanning",
        "risk_weight": 10,
        "description": "60 秒内同一来源连接不少于 10 次且无有效 SQL，典型端口/服务扫描特征",
        "parameters_json": {
            "scope": "source_ip",
            "window_seconds": 60,
            "min_connect_count": 10,
            "max_valid_sql_count": 0,
            "boundary": "inclusive",
        },
    },
    {
        "rule_code": "R02",
        "rule_name": "短时多凭据认证爆破",
        "rule_type": "frequency",
        "intent_type": "bruteforce",
        "risk_weight": 25,
        "description": "5 分钟内同一来源认证尝试不少于 8 次，且不同用户名与测试标识组合不少于 5 组",
        "parameters_json": {
            "scope": "source_ip",
            "window_seconds": 300,
            "min_auth_attempts": 8,
            "min_distinct_credential_pairs": 5,
            "count_failed_only": False,
        },
    },
    {
        "rule_code": "R03",
        "rule_name": "元数据与结构探测",
        "rule_type": "keyword",
        "intent_type": "recon",
        "risk_weight": 15,
        "description": "出现 SHOW TABLES、SHOW DATABASES、SHOW COLUMNS、DESCRIBE、information_schema 查询",
        "parameters_json": {
            "scope": "event",
            "match_target": "normalized_sql",
            "case_sensitive": False,
            "keywords": [
                "SHOW TABLES",
                "SHOW DATABASES",
                "SHOW COLUMNS",
                "SHOW FIELDS",
                "DESCRIBE",
                "DESC ",
                "INFORMATION_SCHEMA",
            ],
            "max_hits_per_event": 1,
        },
    },
    {
        "rule_code": "R04",
        "rule_name": "会话级批量数据读取",
        "rule_type": "volume",
        "intent_type": "data_dump",
        "risk_weight": 25,
        "description": "同一会话连续 SELECT 不少于 5 次，或会话累计返回行数超过 1000 行",
        "parameters_json": {
            "scope": "session",
            "window_seconds": 300,
            "min_consecutive_select": 5,
            "session_returned_rows_threshold": 1000,
            "count_scope": "session_cumulative",
        },
    },
    {
        "rule_code": "R05",
        "rule_name": "破坏性写操作尝试",
        "rule_type": "keyword",
        "intent_type": "destructive",
        "risk_weight": 35,
        "description": "出现 DROP、TRUNCATE、DELETE、UPDATE、INSERT（诱饵层拒绝执行，仅记录并告警）",
        "parameters_json": {
            "scope": "event",
            "match_target": "normalized_sql",
            "case_sensitive": False,
            "word_boundary": True,
            "keywords": ["DROP", "TRUNCATE", "DELETE", "UPDATE", "INSERT"],
            "count_status": ["denied", "error", "success"],
        },
    },
]

FAKE_USER_COUNT = 30
FAKE_ORDER_COUNT = 120
FAKE_CONFIG_COUNT = 5

# 固定基准时刻（UTC），保证种子可重复、可校验
BASE_TIME = datetime(2026, 11, 1, 0, 0, 0)
ORDER_AMOUNTS = {
    1: Decimal("19.90"),
    2: Decimal("99.00"),
    3: Decimal("199.50"),
    0: Decimal("899.00"),
}

# data-model 10.4：5 条 TEST-ONLY 诱饵配置（连接串只指向本机无效端口）
FAKE_CONFIG_SEEDS: list[dict[str, Any]] = [
    {
        "config_key": "db.primary.connection_string",
        "category": "database",
        "config_value": (
            "TEST-ONLY mysql://fake_admin:TEST-ONLY-NOT-A-REAL-PASSWORD"
            "@127.0.0.1:13307/fake_shop?connect_timeout=1"
        ),
        "description": "伪造主库连接串：指向本机无效端口，口令为占位串，仅用于诱饵展示",
    },
    {
        "config_key": "db.replica.connection_string",
        "category": "database",
        "config_value": (
            "TEST-ONLY mysql://fake_reader:TEST-ONLY-NOT-A-REAL-PASSWORD"
            "@127.0.0.1:13308/fake_shop?connect_timeout=1"
        ),
        "description": "伪造只读副本连接串：同样指向本机无效端口",
    },
    {
        "config_key": "mail.smtp.password",
        "category": "mail",
        "config_value": "TEST-ONLY-SMTP-PASSWORD-0000",
        "description": "伪造邮件服务口令占位，不可用于任何真实认证",
    },
    {
        "config_key": "api.payment.secret_key",
        "category": "api",
        "config_value": "TEST-ONLY-SK-fake0000000000000000",
        "description": "伪造支付接口密钥占位，格式像密钥但不可用",
    },
    {
        "config_key": "storage.s3.access_key",
        "category": "storage",
        "config_value": "TEST-ONLY-AKIA0000000000000000",
        "description": "伪造对象存储访问键占位，不可用",
    },
]


def _utc_now() -> datetime:
    """当前 UTC 时刻（naive，DATETIME(6) 列口径）。"""
    return datetime.now(UTC).replace(tzinfo=None)


def _db_account_name() -> str:
    """从 DATABASE_URL 解析当前数据库账号名，用于审计 `account_name`。"""
    try:
        return make_url(settings.database_url).username or "unknown"
    except Exception:  # noqa: BLE001 - 解析失败不应阻断种子导入
        return "unknown"


def _fake_password_hash(index: int) -> str:
    """构造 bcrypt 形状但不可用的伪哈希（必须保留 TEST-ONLY$ 前缀通过检查约束）。"""
    digest = base64.b64encode(
        hashlib.sha256(f"demo-user-{index:02d}".encode()).digest()
    ).decode()
    bcrypt_like = digest.replace("+", ".").replace("/", "_").rstrip("=")[:53]
    return f"TEST-ONLY$2b$12${bcrypt_like}"


async def _ensure_rules(db) -> int:
    """确保 R01–R05 的 v1 规则存在；已存在则跳过，返回存在的规则数。"""
    existing = {
        str(row[0])
        for row in (
            await db.execute(text("SELECT DISTINCT rule_code FROM detection_rules"))
        ).all()
    }
    inserted = 0
    for rule in RULE_SEEDS:
        if rule["rule_code"] in existing:
            continue
        await db.execute(
            text(
                """
                INSERT INTO detection_rules (
                    rule_code, rule_name, rule_type, intent_type, parameters_json,
                    risk_weight, rule_version, enabled, description
                ) VALUES (
                    :rule_code, :rule_name, :rule_type, :intent_type, :parameters_json,
                    :risk_weight, 1, 1, :description
                )
                """
            ),
            {
                "rule_code": rule["rule_code"],
                "rule_name": rule["rule_name"],
                "rule_type": rule["rule_type"],
                "intent_type": rule["intent_type"],
                "parameters_json": json.dumps(
                    rule["parameters_json"], ensure_ascii=False, separators=(",", ":")
                ),
                "risk_weight": rule["risk_weight"],
                "description": rule["description"],
            },
        )
        inserted += 1
    return len({rule["rule_code"] for rule in RULE_SEEDS})


async def _import_fake_users(db) -> int:
    """导入 30 条虚构用户（幂等：按 username / email 唯一键更新）。"""
    for index in range(1, FAKE_USER_COUNT + 1):
        suffix = f"{index:02d}"
        await db.execute(
            text(
                """
                INSERT INTO fake_users (
                    username, email, phone, password_hash, display_name,
                    is_synthetic, created_at
                ) VALUES (
                    :username, :email, :phone, :password_hash, :display_name,
                    1, :created_at
                ) AS new
                ON DUPLICATE KEY UPDATE
                    email = new.email,
                    phone = new.phone,
                    password_hash = new.password_hash,
                    display_name = new.display_name,
                    is_synthetic = 1
                """
            ),
            {
                "username": f"demo_user_{suffix}",
                "email": f"demo_user_{suffix}@example.com",
                "phone": f"1380000{index:04d}",
                "password_hash": _fake_password_hash(index),
                "display_name": f"演示用户{suffix}",
                "created_at": BASE_TIME + timedelta(minutes=index),
            },
        )
    return FAKE_USER_COUNT


def _order_status(seq: int) -> str:
    """按 data-model 10.4 的序号映射给出订单状态（120 号固定 refunded）。"""
    if seq == FAKE_ORDER_COUNT:
        return "refunded"
    remainder = seq % 10
    if remainder <= 4:
        return "paid"
    if remainder <= 6:
        return "shipped"
    if remainder <= 8:
        return "pending"
    return "cancelled"


async def _import_fake_orders(db) -> int:
    """导入 120 条虚构订单（30 用户 × 4 单，幂等：按 order_no 唯一键更新）。"""
    user_rows = (
        await db.execute(text("SELECT id, username FROM fake_users ORDER BY id"))
    ).all()
    username_to_id = {str(row.username): int(row.id) for row in user_rows}
    user_ids = [username_to_id[f"demo_user_{i:02d}"] for i in range(1, FAKE_USER_COUNT + 1)]

    for seq in range(1, FAKE_ORDER_COUNT + 1):
        user_id = user_ids[(seq - 1) % FAKE_USER_COUNT]
        await db.execute(
            text(
                """
                INSERT INTO fake_orders (
                    order_no, user_id, amount, currency, order_status,
                    remark, is_synthetic, created_at
                ) VALUES (
                    :order_no, :user_id, :amount, 'CNY', :order_status,
                    :remark, 1, :created_at
                ) AS new
                ON DUPLICATE KEY UPDATE
                    user_id = new.user_id,
                    amount = new.amount,
                    currency = new.currency,
                    order_status = new.order_status,
                    remark = new.remark,
                    is_synthetic = 1
                """
            ),
            {
                "order_no": f"FAKE-202611-{seq:05d}",
                "user_id": user_id,
                "amount": ORDER_AMOUNTS[seq % 4],
                "order_status": _order_status(seq),
                "remark": "演示订单，仅用于蜜罐展示" if seq % 2 == 1 else None,
                "created_at": BASE_TIME + timedelta(minutes=seq * 7),
            },
        )
    return FAKE_ORDER_COUNT


async def _import_fake_config(db) -> int:
    """导入 5 条 TEST-ONLY 诱饵配置（幂等：按 config_key 唯一键更新）。"""
    for item in FAKE_CONFIG_SEEDS:
        await db.execute(
            text(
                """
                INSERT INTO fake_config (
                    config_key, config_value, category, description, is_invalid, created_at
                ) VALUES (
                    :config_key, :config_value, :category, :description, 1, :created_at
                ) AS new
                ON DUPLICATE KEY UPDATE
                    config_value = new.config_value,
                    category = new.category,
                    description = new.description,
                    is_invalid = 1
                """
            ),
            {
                "config_key": item["config_key"],
                "config_value": item["config_value"],
                "category": item["category"],
                "description": item["description"],
                "created_at": _utc_now(),
            },
        )
    return FAKE_CONFIG_COUNT


async def _write_audit(db, *, account_name: str, detail: str) -> None:
    """写一条迁移审计（audit_log 仅追加）。"""
    await db.execute(
        text(
            """
            INSERT INTO audit_log
                (occurred_at, account_name, operation, target_table, target_key, result, detail)
            VALUES
                (:occurred_at, :account_name, 'migration', NULL, NULL, 'success', :detail)
            """
        ),
        {
            "occurred_at": _utc_now(),
            "account_name": account_name[:64],
            "detail": detail[:1000],
        },
    )


async def run_seed() -> dict[str, int]:
    """执行完整种子导入（单事务），返回固定结构的结果计数。"""
    factory = get_rw_factory()
    async with factory() as db:
        async with db.begin():
            rules = await _ensure_rules(db)
            users = await _import_fake_users(db)
            orders = await _import_fake_orders(db)
            configs = await _import_fake_config(db)
            detail = (
                f"种子导入完成：规则 {rules} 条、诱饵用户 {users} 条、"
                f"诱饵订单 {orders} 条、诱饵配置 {configs} 条（TEST-ONLY 虚构数据）"
            )
            await _write_audit(db, account_name=_db_account_name(), detail=detail)

    result = {
        "rules": rules,
        "fake_users": users,
        "fake_orders": orders,
        "fake_config": configs,
    }
    await get_rw_engine().dispose()
    return result


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.seed",
        description="幂等导入检测规则与伪诱饵数据（R01–R05 / 30 用户 / 120 订单 / 5 配置）",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="导入全部种子数据（规则 + 诱饵数据），可重复执行",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：`python -m app.cli.seed --all`。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.all:
        parser.error("必须指定 --all（导入全部种子数据）")

    try:
        result = asyncio.run(run_seed())
    except Exception as exc:  # noqa: BLE001 - CLI 需要明确失败信息
        print(f"种子导入失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
