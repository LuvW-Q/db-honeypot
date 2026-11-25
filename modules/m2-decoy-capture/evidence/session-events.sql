-- M2 证据 SQL：同一会话的完整事件日志 + M4 命中链路（只读，无 DDL/DML）
-- 复现：docker exec -i dbhoneypot-mysql mysql -h127.0.0.1 -P3306 --protocol=TCP \
--          -uhoneypot_app_ro -p'<RO_PASSWORD>' --table honeypot_dev \
--          < modules/m2-decoy-capture/evidence/session-events.sql
-- 依赖：honeypot_dev 已灌入确定性 demo 数据（214 sessions / 2525 attack_log）

SET @sid := '5a060001-0000-4000-8000-000000000001';

-- 1) 会话元数据：来源、时间跨度、请求计数、最高风险分
SELECT session_id, source_ip, source_port, target_service,
       started_at, ended_at, session_status, request_count, max_risk_score
FROM sessions
WHERE session_id = @sid;

-- 2) 完整事件日志：按 event_time 升序还原时间线（16 条）
SELECT event_id, event_uuid, event_type, event_time, username,
       credential_test_id, sql_statement, status, returned_rows, response_ms
FROM attack_log
WHERE session_id = @sid
ORDER BY event_time, event_id;

-- 3) 事件计数与累计返回行数（核对 R04 条件 B 是否成立）
SELECT COUNT(*) AS event_count,
       SUM(returned_rows) AS total_returned_rows,
       SUM(event_type = 'auth') AS auth_events,
       SUM(event_type = 'query') AS query_events
FROM attack_log
WHERE session_id = @sid;

-- 4) 规则命中：事件 → 规则 → 意图 → 权重 → 证据（M4 落库结果）
SELECT hit_id, event_id, rule_code, intent_type, risk_weight,
       rule_version, evidence_summary, triggered_at
FROM rule_hits
WHERE session_id = @sid
ORDER BY hit_id;

-- 5) 告警：命中聚合后的告警等级与证据摘要
SELECT alert_id, rule_code, severity, title, evidence_summary,
       first_seen_at, last_seen_at, occurrence_count
FROM alerts
WHERE session_id = @sid
ORDER BY alert_id;
