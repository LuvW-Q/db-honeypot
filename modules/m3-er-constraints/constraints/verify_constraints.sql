-- =============================================================================
-- M3 完整性约束正反样例校验（honeypot_dev）
--
-- 目的：对主键/外键/UNIQUE/CHECK/无符号列/生成列做"先反例、后正例"的活体验证，
--       证明 docs/database-design.md 第 4 章的约束不是纸面设计，而是数据库层生效。
--
-- 运行方式（批量模式必须加 --force：否则客户端遇到第一个预期错误就退出）：
--   docker exec -i dbhoneypot-mysql mysql --force -uroot -p<ROOT_PASSWORD> \
--       honeypot_dev < modules/m3-er-constraints/constraints/verify_constraints.sql
--   （本机未安装 mysql 客户端；容器镜像自带 mysql 8.0.46 客户端）
--
-- 预期错误码（MySQL 8.0.46 实测；高版本 MySQL 8.4 的外键错误码为 1216/1217，
--                  脚本注释同时给出两种口径）：
--   S1 FK 子行无父行         1452 / 1216   fk_log_session
--   S2 FK 合法插入           成功，随后回滚保存点
--   S3 CHECK 枚举拒绝        3819          ck_sessions_status
--   S4 CHECK 分数越界        3819          ck_profile_risk_score
--   S5 CHECK 正例+生成列     成功（risk_level 生成列 = critical）
--   S6 UNIQUE 幂等重复       1062          uk_attack_log_event_uuid
--   S7 UNIQUE 画像重复       1062          uk_attacker_profile_source_ip
--   S8 无符号列负值          1264          total_connections
--   S9 FK 父行删除拒绝       1451 / 1217   fk_log_session ON DELETE RESTRICT
--
-- 数据安全：全程在单个事务内；反例语句失败只回滚该语句，正例插入用
--           SAVEPOINT/ROLLBACK TO SAVEPOINT 复原；脚本最后 ROLLBACK，
--           并以会话变量 @base_* 对比收尾行数（counts_unchanged 必须全为 1）。
--           输出中的 "ERROR NNNN" 是**预期**的约束拒绝证据，不是脚本失败。
-- =============================================================================

SET SESSION time_zone = '+00:00';

SELECT VERSION()                AS mysql_version,
       @@session.time_zone      AS session_time_zone,
       DATABASE()               AS current_schema,
       @@session.autocommit     AS autocommit;

-- 基线快照：会话变量不受 ROLLBACK 影响，供脚本末尾对账
SELECT COUNT(*) INTO @base_sessions     FROM sessions;
SELECT COUNT(*) INTO @base_attack_log   FROM attack_log;
SELECT COUNT(*) INTO @base_profile      FROM attacker_profile;
SELECT COUNT(*) INTO @base_rule_hits    FROM rule_hits;
SELECT COUNT(*) INTO @base_alerts       FROM alerts;

SELECT @base_sessions   AS base_sessions,
       @base_attack_log AS base_attack_log,
       @base_profile    AS base_profile,
       @base_rule_hits  AS base_rule_hits,
       @base_alerts     AS base_alerts;

START TRANSACTION;

-- -----------------------------------------------------------------------------
-- S1 外键反例：attack_log.session_id 指向不存在的会话 → 子行插入被拒绝
--    预期 ERROR 1452 (MySQL 8.4: 1216)，约束名 fk_log_session
--    使用 UUID() 生成不存在的会话编号，避免与演示数据中的 214 个会话碰撞
-- -----------------------------------------------------------------------------
INSERT INTO attack_log
    (event_uuid, session_id, event_type, source_ip, event_time, status)
VALUES
    ('00000000-0000-4000-8000-0000000000f1', UUID(),
     'connect', '203.0.113.250', UTC_TIMESTAMP(6), 'success');

-- -----------------------------------------------------------------------------
-- S2 外键正例：真实存在的会话 + 事件；随后回滚保存点，事务内不留数据
-- -----------------------------------------------------------------------------
SAVEPOINT sp_fk_ok;

SET @s2_session := UUID();
INSERT INTO sessions (session_id, source_ip, started_at, session_status)
VALUES (@s2_session, '203.0.113.250', UTC_TIMESTAMP(6), 'active');

INSERT INTO attack_log
    (event_uuid, session_id, event_type, source_ip, event_time, status)
VALUES
    (UUID(), @s2_session, 'connect', '203.0.113.250', UTC_TIMESTAMP(6), 'success');

SELECT 'S2 合法插入' AS sample,
       (SELECT COUNT(*) FROM sessions   WHERE session_id = @s2_session) AS session_rows,
       (SELECT COUNT(*) FROM attack_log WHERE session_id = @s2_session) AS event_rows;

ROLLBACK TO SAVEPOINT sp_fk_ok;

-- -----------------------------------------------------------------------------
-- S3 CHECK（枚举）反例：sessions.session_status 只允许 active/closed/timeout/error
--    预期 ERROR 3819，约束名 ck_sessions_status
-- -----------------------------------------------------------------------------
INSERT INTO sessions (session_id, source_ip, started_at, session_status)
VALUES (UUID(), '203.0.113.250', UTC_TIMESTAMP(6), 'hacked');

-- -----------------------------------------------------------------------------
-- S4 CHECK（分数上界）反例：attacker_profile.risk_score 必须 <= 100
--    预期 ERROR 3819，约束名 ck_profile_risk_score
-- -----------------------------------------------------------------------------
INSERT INTO attacker_profile (source_ip, first_seen, last_seen, risk_score)
VALUES ('203.0.113.250', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6), 101);

-- -----------------------------------------------------------------------------
-- S5 CHECK 正例 + 生成列：risk_score=80 合法，生成列 risk_level 自动为 critical
-- -----------------------------------------------------------------------------
SAVEPOINT sp_check_ok;

INSERT INTO attacker_profile (source_ip, first_seen, last_seen, risk_score)
VALUES ('203.0.113.250', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6), 80);

SELECT 'S5 风险分边界+生成列' AS sample,
       risk_score,
       risk_level,
       (risk_level = 'critical') AS generated_level_ok
FROM attacker_profile
WHERE source_ip = '203.0.113.250';

ROLLBACK TO SAVEPOINT sp_check_ok;

-- -----------------------------------------------------------------------------
-- S6 UNIQUE（事件幂等）反例：同一 event_uuid 重复投递
--    预期 ERROR 1062，键 uk_attack_log_event_uuid
--    两个插入使用同一会话与同一个 @dup_event_uuid，第二次必须被拒绝
-- -----------------------------------------------------------------------------
SAVEPOINT sp_uk_event;

SET @s6_session     := UUID();
SET @s6_event_uuid  := UUID();
INSERT INTO sessions (session_id, source_ip, started_at)
VALUES (@s6_session, '203.0.113.250', UTC_TIMESTAMP(6));
INSERT INTO attack_log
    (event_uuid, session_id, event_type, source_ip, event_time, status)
VALUES
    (@s6_event_uuid, @s6_session, 'connect', '203.0.113.250', UTC_TIMESTAMP(6), 'success');

-- 重复投递：同一 event_uuid → 1062
INSERT INTO attack_log
    (event_uuid, session_id, event_type, source_ip, event_time, status)
VALUES
    (@s6_event_uuid, @s6_session, 'connect', '203.0.113.250', UTC_TIMESTAMP(6), 'success');

SELECT 'S6 首次写入保留' AS sample,
       (SELECT COUNT(*) FROM attack_log WHERE event_uuid = @s6_event_uuid) AS rows_with_uuid;

ROLLBACK TO SAVEPOINT sp_uk_event;

-- -----------------------------------------------------------------------------
-- S7 UNIQUE（一来源一画像）反例：同一 source_ip 插入两行
--    预期 ERROR 1062，键 uk_attacker_profile_source_ip
--    203.0.113.250 在演示数据中不存在于 attacker_profile（实测 14 行均为 198.51.100.11-24）
-- -----------------------------------------------------------------------------
SAVEPOINT sp_uk_profile;

INSERT INTO attacker_profile (source_ip, first_seen, last_seen)
VALUES ('203.0.113.250', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6));

-- 第二行同 IP → 1062
INSERT INTO attacker_profile (source_ip, first_seen, last_seen)
VALUES ('203.0.113.250', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6));

SELECT 'S7 首行保留' AS sample,
       (SELECT COUNT(*) FROM attacker_profile WHERE source_ip = '203.0.113.250') AS rows_with_ip;

ROLLBACK TO SAVEPOINT sp_uk_profile;

-- -----------------------------------------------------------------------------
-- S8 无符号列反例：attacker_profile.total_connections 是 INT UNSIGNED
--    预期 ERROR 1264 Out of range value
-- -----------------------------------------------------------------------------
INSERT INTO attacker_profile
    (source_ip, first_seen, last_seen, total_connections)
VALUES
    ('203.0.113.251', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6), -1);

-- -----------------------------------------------------------------------------
-- S9 外键 RESTRICT 反例：删除仍被 attack_log 引用的会话
--    预期 ERROR 1451 (MySQL 8.4: 1217)，约束名 fk_log_session
-- -----------------------------------------------------------------------------
SAVEPOINT sp_fk_restrict;

SET @s9_session := UUID();
INSERT INTO sessions (session_id, source_ip, started_at)
VALUES (@s9_session, '203.0.113.252', UTC_TIMESTAMP(6));
INSERT INTO attack_log
    (event_uuid, session_id, event_type, source_ip, event_time, status)
VALUES
    (UUID(), @s9_session, 'connect', '203.0.113.252', UTC_TIMESTAMP(6), 'success');

DELETE FROM sessions WHERE session_id = @s9_session;

SELECT 'S9 删除被拒后会话仍在' AS sample,
       (SELECT COUNT(*) FROM sessions WHERE session_id = @s9_session) AS session_rows;

ROLLBACK TO SAVEPOINT sp_fk_restrict;

-- -----------------------------------------------------------------------------
-- 收尾：整体回滚，事务内所有正例插入全部消失
-- -----------------------------------------------------------------------------
ROLLBACK;

-- -----------------------------------------------------------------------------
-- 对账：行数与基线一致 → 脚本未污染 honeypot_dev
-- 期望输出每个 *_unchanged 均为 1，all_unchanged = 1
-- -----------------------------------------------------------------------------
SELECT (SELECT COUNT(*) FROM sessions)          = @base_sessions   AS sessions_unchanged,
       (SELECT COUNT(*) FROM attack_log)       = @base_attack_log AS attack_log_unchanged,
       (SELECT COUNT(*) FROM attacker_profile)  = @base_profile    AS profile_unchanged,
       (SELECT COUNT(*) FROM rule_hits)        = @base_rule_hits  AS rule_hits_unchanged,
       (SELECT COUNT(*) FROM alerts)           = @base_alerts     AS alerts_unchanged,
       (
           (SELECT COUNT(*) FROM sessions)         = @base_sessions
       AND (SELECT COUNT(*) FROM attack_log)       = @base_attack_log
       AND (SELECT COUNT(*) FROM attacker_profile) = @base_profile
       AND (SELECT COUNT(*) FROM rule_hits)        = @base_rule_hits
       AND (SELECT COUNT(*) FROM alerts)           = @base_alerts
       ) AS all_unchanged;

-- 生成列风险等级口径抽查：与迁移 0001 的 CASE 阈值一致（0-29/30-59/60-79/80-100）
SELECT CASE
           WHEN risk_score >= 80 THEN 'critical'
           WHEN risk_score >= 60 THEN 'high'
           WHEN risk_score >= 30 THEN 'medium'
           ELSE 'low'
       END AS expected_level,
       risk_level AS stored_level,
       COUNT(*) AS rows_cnt
FROM attacker_profile
GROUP BY expected_level, stored_level
ORDER BY rows_cnt DESC;
