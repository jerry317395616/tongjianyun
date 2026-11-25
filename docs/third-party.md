# 第三方软件

童健云通过 Frappe 应用接口安装，在运行时依赖以下项目。安装环境可能同时启用其他应用，各项目按其自身许可分发。

| 软件 | 用途 | 上游许可 |
|---|---|---|
| Frappe Framework | DocType、Desk、权限和站点运行时 | [Frappe Framework](https://github.com/frappe/frappe) |
| ERPNext | 物料、BOM、采购、库存、项目和会计 | [ERPNext](https://github.com/frappe/erpnext) |
| Frappe Education | 在园名册与学年学期 | [Frappe Education](https://github.com/frappe/education) |

Python 依赖见 [pyproject.toml](../pyproject.toml)。仓库内的前端应用各自保留依赖列表和锁文件。重新分发时请一并遵守相关组成部分的许可及版权声明。
