"""捕获层（诱饵协议模拟）：mysql-mimic 会话、认证、伪造库表目录与事件发射。

模块边界（`impl-contract.md` 第 1 章）：本包只负责协议解析、伪造响应与产生
标准事件，不承担风险评分/告警判定，也不连接任何真实业务数据库。

常用入口：
- `app.honeypot.server`：诱饵服务进程（`python -m app.honeypot.server`）；
- `app.honeypot.session.HoneypotSession`：自定义协议会话；
- `app.honeypot.auth.DecoyIdentityProvider`：诱饵账号认证；
- `app.honeypot.emitter.EventEmitter`：事件写入存储层。

注意：包 `__init__` 刻意不做子模块导入，避免与 `app.honeypot.session` 形成循环导入。
"""

__all__ = []
