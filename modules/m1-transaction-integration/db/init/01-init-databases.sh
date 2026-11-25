#!/usr/bin/env bash
# ============================================================
# MySQL 8.4/8.0 容器初始化：创建开发/测试/演示库与四类最小权限账号
# 说明：表级精细化授权（audit_log 仅追加等）在迁移完成后由
#       scripts/apply_table_grants.sh 收紧；本脚本只授予库级权限，
#       且 app_rw / app_ro 绝不授予 DDL。
# 仅用于隔离实验环境；口令来自容器环境变量，不写入仓库
# ============================================================
set -euo pipefail

MYSQL_CMD=(mysql --protocol=socket -uroot -p"${MYSQL_ROOT_PASSWORD}")

for db in honeypot_dev honeypot_test honeypot_demo; do
  "${MYSQL_CMD[@]}" <<SQL
CREATE DATABASE IF NOT EXISTS ${db}
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;
SQL
done

# 四类账号分别在“本机回环”和“Compose 隔离网段”创建（禁止使用 % 或公网网段）
for host in '127.0.0.1' '172.28.0.%'; do
  "${MYSQL_CMD[@]}" <<SQL
CREATE USER IF NOT EXISTS 'honeypot_migrate'@'${host}' IDENTIFIED BY '${HONEYPOT_MIGRATE_PASSWORD}';
CREATE USER IF NOT EXISTS 'honeypot_app_rw'@'${host}'  IDENTIFIED BY '${HONEYPOT_APP_RW_PASSWORD}';
CREATE USER IF NOT EXISTS 'honeypot_app_ro'@'${host}'  IDENTIFIED BY '${HONEYPOT_APP_RO_PASSWORD}';
CREATE USER IF NOT EXISTS 'honeypot_backup'@'${host}'  IDENTIFIED BY '${HONEYPOT_BACKUP_PASSWORD}';

-- 迁移账号：三库 DDL + 读写，但无全局特权
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES,
      CREATE VIEW, SHOW VIEW
  ON honeypot_dev.*  TO 'honeypot_migrate'@'${host}';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES,
      CREATE VIEW, SHOW VIEW
  ON honeypot_test.* TO 'honeypot_migrate'@'${host}';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES,
      CREATE VIEW, SHOW VIEW
  ON honeypot_demo.* TO 'honeypot_migrate'@'${host}';

-- 业务读写账号：只有 DML，无 DDL；audit_log/detection_rules 的删除限制由应用层与表级授权收紧
GRANT SELECT, INSERT, UPDATE, DELETE ON honeypot_dev.*  TO 'honeypot_app_rw'@'${host}';
GRANT SELECT, INSERT, UPDATE, DELETE ON honeypot_demo.* TO 'honeypot_app_rw'@'${host}';

-- 分析只读账号：只有 SELECT
GRANT SELECT ON honeypot_dev.*  TO 'honeypot_app_ro'@'${host}';
GRANT SELECT ON honeypot_demo.* TO 'honeypot_app_ro'@'${host}';

-- 备份账号：只读 + 锁表 + 视图元数据
GRANT SELECT, LOCK TABLES, SHOW VIEW, TRIGGER, EVENT
  ON honeypot_dev.*  TO 'honeypot_backup'@'${host}';
GRANT SELECT, LOCK TABLES, SHOW VIEW, TRIGGER, EVENT
  ON honeypot_demo.* TO 'honeypot_backup'@'${host}';

REVOKE GRANT OPTION ON *.* FROM 'honeypot_migrate'@'${host}';
REVOKE GRANT OPTION ON *.* FROM 'honeypot_app_rw'@'${host}';
REVOKE GRANT OPTION ON *.* FROM 'honeypot_app_ro'@'${host}';
REVOKE GRANT OPTION ON *.* FROM 'honeypot_backup'@'${host}';
SQL
done

"${MYSQL_CMD[@]}" -e "FLUSH PRIVILEGES;"

echo "[init] 数据库 honeypot_dev / honeypot_test / honeypot_demo 与四类账号已创建"
