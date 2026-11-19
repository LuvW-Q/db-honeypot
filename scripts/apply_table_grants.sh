# ============================================================
# 迁移完成后收紧表级权限（最小权限）：audit_log 仅追加、规则不可删除
# 用法：./scripts/apply_table_grants.sh [honeypot_dev|honeypot_demo]
# 说明：库级权限已由 db/init/01-init-databases.sh 建立，本脚本做精细化收口
# ============================================================
set -euo pipefail

DB="${1:-honeypot_dev}"
ROOT_PW="$(grep '^MYSQL_ROOT_PASSWORD=' .env | cut -d= -f2)"
MYSQL_CMD=(docker exec -i dbhoneypot-mysql mysql -uroot -p"${ROOT_PW}")

for host in '127.0.0.1' '172.28.0.%'; do
  "${MYSQL_CMD[@]}" <<SQL
-- 收回业务账号对审计表与规则表的删除权限（库级授权无法单表收回，改为表级重建）
REVOKE SELECT, INSERT, UPDATE, DELETE ON ${DB}.* FROM 'honeypot_app_rw'@'${host}';
GRANT SELECT, INSERT, UPDATE, DELETE ON ${DB}.sessions         TO 'honeypot_app_rw'@'${host}';
GRANT SELECT, INSERT, UPDATE, DELETE ON ${DB}.attack_log       TO 'honeypot_app_rw'@'${host}';
GRANT SELECT, INSERT, UPDATE, DELETE ON ${DB}.attacker_profile TO 'honeypot_app_rw'@'${host}';
GRANT SELECT, INSERT, UPDATE, DELETE ON ${DB}.attacker_intent  TO 'honeypot_app_rw'@'${host}';
GRANT SELECT, INSERT, UPDATE, DELETE ON ${DB}.rule_hits        TO 'honeypot_app_rw'@'${host}';
GRANT SELECT, INSERT, UPDATE, DELETE ON ${DB}.alerts           TO 'honeypot_app_rw'@'${host}';
GRANT SELECT, INSERT, UPDATE          ON ${DB}.detection_rules TO 'honeypot_app_rw'@'${host}';
GRANT SELECT ON ${DB}.fake_users TO 'honeypot_app_rw'@'${host}';
GRANT SELECT ON ${DB}.fake_orders TO 'honeypot_app_rw'@'${host}';
GRANT SELECT ON ${DB}.fake_config TO 'honeypot_app_rw'@'${host}';
GRANT SELECT, INSERT ON ${DB}.audit_log TO 'honeypot_app_rw'@'${host}';

REVOKE SELECT ON ${DB}.* FROM 'honeypot_app_ro'@'${host}';
GRANT SELECT ON ${DB}.sessions         TO 'honeypot_app_ro'@'${host}';
GRANT SELECT ON ${DB}.attack_log       TO 'honeypot_app_ro'@'${host}';
GRANT SELECT ON ${DB}.attacker_profile TO 'honeypot_app_ro'@'${host}';
GRANT SELECT ON ${DB}.attacker_intent  TO 'honeypot_app_ro'@'${host}';
GRANT SELECT ON ${DB}.detection_rules  TO 'honeypot_app_ro'@'${host}';
GRANT SELECT ON ${DB}.rule_hits        TO 'honeypot_app_ro'@'${host}';
GRANT SELECT ON ${DB}.alerts           TO 'honeypot_app_ro'@'${host}';
GRANT SELECT ON ${DB}.fake_orders      TO 'honeypot_app_ro'@'${host}';
GRANT SELECT ON ${DB}.fake_config      TO 'honeypot_app_ro'@'${host}';
GRANT SELECT ON ${DB}.audit_log        TO 'honeypot_app_ro'@'${host}';
GRANT SELECT (id, username, email, phone, display_name, is_synthetic, created_at)
  ON ${DB}.fake_users TO 'honeypot_app_ro'@'${host}';
GRANT SELECT ON ${DB}.v_session_risk_summary     TO 'honeypot_app_ro'@'${host}';
GRANT SELECT ON ${DB}.v_attacker_profile_summary TO 'honeypot_app_ro'@'${host}';
GRANT SELECT ON ${DB}.v_daily_attack_trend       TO 'honeypot_app_ro'@'${host}';
GRANT SELECT ON ${DB}.v_rule_effectiveness       TO 'honeypot_app_ro'@'${host}';
SQL
done

echo "[grants] ${DB} 的表级最小权限已收紧"
