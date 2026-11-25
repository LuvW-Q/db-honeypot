"""覆盖仓库根 conftest 的数据库夹具。

``shared/deploy/tests`` 只做静态分析（目录结构、import 边界、离线资源），不需要
MySQL。根 ``conftest.py`` 定义了 session 级 ``prepare_test_database`` 与 function 级
``database_isolation`` 两个 autouse 夹具；这里用同名夹具覆盖为空操作，避免让
部署工具链的单测依赖 Docker/MySQL。
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def prepare_test_database() -> None:
    """覆盖根夹具：部署工具链单测不准备数据库。"""
    return None


@pytest.fixture(autouse=True)
def database_isolation() -> None:
    """覆盖根夹具：部署工具链单测不做数据隔离。"""
    return None
