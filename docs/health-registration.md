# 幼儿健康登记：第一阶段

入口：业务工作台 → 幼儿健康登记。仅 Administrator 或 Tongjianyun Health Manager 可使用；不自动给业务账号分配健康角色。

新增一个标准 DocType：Tongjianyun Student Health。学生与月份确定唯一记录，班级/姓名/性别保存快照；已存记录不能更改归属。未登记、待核实不是明确无。已核对要求明确状态及来源，修改已核对记录须说明原因，启用 Version 留痕。历史月份各自保存，不自动覆盖。

部署仅 reload_doc('tongjianyun', 'doctype', 'tongjianyun_student_health')，不运行全站迁移；先通过 Role ORM 创建 Tongjianyun Health Manager（desk_access=1），不授予用户。现有学生结构不变。

第一阶段支持人工登记、月份/班级查询、沿用上月后重新核对、脱敏打印。无记录的行来自当前启用名单，不是该历史月份到园证明。沿用仅作为待核对建议。手机号目前人工核对填写，不自动覆盖 Guardian。

尚未实现：照片 OCR、家长授权采集界面、教师班级范围授权、食谱过敏原匹配、厨房特殊餐清单、监护人电话带入。不得将第一阶段称为完整健康管理闭环。通用 AI/Harness 不应被赋予此专属角色。

测试：tongjianyun.tests.test_health_registration；生产样本的 ORM 写入验证必须 rollback，不保留测试健康事实。
