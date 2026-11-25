"""部署与校验工具链（`shared.deploy`）。

本包只承载构建、部署、结构与依赖边界检查脚本，不承载业务逻辑：

- ``check_structure``：仓库目录结构 / 包命名 / 必需文件 / 禁止遗留检查；
- ``check_boundaries``：模块依赖边界静态检查（``boundary_check`` 为契约兼容别名）；
- ``verify_deploy``：13 步部署验收主脚本（``verify_deploy.sh``）。

脚本只依赖 Python 标准库 + bash + `corepack pnpm`（前端构建/浏览器检查）；
不引入新的第三方依赖。
"""
