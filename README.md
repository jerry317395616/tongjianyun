# 童健云

**为幼儿园打造的 Frappe / ERPNext 开源管理应用。** 膳食与食堂模块把带量周食谱、采购验收、供餐日结和膳食台账连成一条流程。

[十分钟演示](docs/meal-demo.md) · [安装与升级](docs/install.md) · [参与贡献](CONTRIBUTING.md) · [路线图](docs/roadmap.md) · [版本发布](https://github.com/jerry317395616/tongjianyun/releases)

## 一份带量食谱如何落地

1. **编排与审核** — 从标准菜品和配方选菜，按在园名册生成计划人数，支持调整单餐的食材用量。
2. **采购与验收** — 根据人均带量和账面库存核算采购需求，跟踪供应商配送、验收和食材批次。
3. **供餐与食品安全** — 记录逐餐供餐、厨房日结、食品留样、陪餐和检查整改。
4. **台账与复盘** — 按园所、食堂和日期追溯业务记录，查看周食谱、批次和结算报表。

标准菜品和食材使用 ERPNext 物料，菜品配方使用 BOM。食谱审核、学期任务和食堂业务由童健云管理。食材营养档案可以录入每 100 克的营养值。可选的 AI 营养估算另有部署和数据处理说明。[食谱报表与可选 AI 分析](docs/meal-reports.md)

## 开始试用

按[安装文档](docs/install.md)创建演示站点，再跟随[十分钟演示](docs/meal-demo.md)查看「青禾溪畔示范幼儿园」的周食谱及相关业务。上线前请在独立站点完成安装与升级验证。

## 贡献与授权

欢迎报告问题、提交中文文档改进和用虚构数据描述园所的工作流程。[贡献指南](CONTRIBUTING.md) · [安全问题报告](SECURITY.md)

童健云原创代码按 [MIT](license.txt) 发布。部署依赖和各自的许可请见[第三方软件说明](docs/third-party.md)。

*Tongjianyun is an open-source kindergarten management application for Frappe and ERPNext. Its canteen module connects portioned weekly menus, purchasing, receiving, meal service and traceable ledgers.*
