# 班级学生餐次确认

## 授权及结构预览

本次用户单独授权解除本功能最小范围结构冻结。不涉及官方应用修改。

新增 Tongjianyun Class Meal Confirmation（班级每日确认）与其子表 Tongjianyun Student Meal Row。

- 父表：meal_date Date 必填、student_group Link Student Group 必填、status Select 待确认/已确认 默认待确认、students Table 必填；change_reason Small Text 修改已确认记录时服务端必填；confirmed_by Link User / confirmed_at Datetime 只读由服务端赋值。
- 子表：student Link Student 必填、student_name Data 只读快照、attendance_hint Data 只读参考。五个餐次各有 *_expected Check 默认0，以及实际状态 Select 未确认/已就餐/未就餐/不供餐 默认未确认。
- 权限：现有管理员及教师角色可读写创建；班级范围继承现有教师 Employee→Instructor→Student Group 关系并与 Frappe 权限取交集；不得读写其他班级。无普通角色删除权。保存走 ORM、服务端校验与 Frappe Version 审计。
- 历史迁移：无。既有记录不自动确认为学生实际就餐；新表为空。
- 回滚：停用新入口及扩展调用，保留新记录及审计以供核对；不删表、不删数据。恢复旧入口前需评估其把预计默认为实际的风险。

## 行为

原入口 /desk/tongjianyun-daily-meal-confirmation/... → doctype_js public/js/student_meals.js → student_meals.get_class_meals/save_class_meals → 两种新记录 → daily_meals.refresh_confirmation。

未保存时从启用班级学生+考勤/请假给出预计建议，未确认不等于缺勤。停止就餐不写 Education 考勤，不自动退费。未来只能保存预计安排。

名单首次保存时冻结；后续修改保留该日学生快照。每次保存严格校验完整唯一学生名单，并校验修改版本。确认后的修改必须填写原因，锁日禁止修改。新入班学生在新的日期载入，既有日期名单不自动增删。

各班全部确认后才把全园汇总标记已确认；否则是预计参考。已存在的班级人数调整不覆盖学生明细，访客等非学生用餐暂不纳入学生确认快照，避免无名人数混入学生统计。

采购准备读取完整可见班级计划，可带入预计数；不完整则保留原有人工预计逻辑。任何确认修改都不会重写已经提交的采购/库存/发票/付款，不执行退款或公司期间关账。

## 部署

仅定向 reload_doc 两种新增 DocType；禁止运行全量 migrate（站点有无关迁移钩子和未提交改动）。先子表后主表，清理对应元数据缓存，再加载新业务代码；上线前后核对原有模型结构不变。

2026-09-11 验证：51 项 Python 回归通过；JavaScript 语法检查通过；两名临时学生的 ORM 集成回滚覆盖预计/实际分离、单餐未就餐、班级汇总、修改原因、版本审计、过期修改拒绝、未来仅保存预计及采购预计取数。测试后学生、考勤、就餐、采购、付款记录数量全部恢复。

浏览器原路由验收未完成：执行端访问 HTTPS 返回 ERR_CONNECTION_CLOSED，用户反馈其浏览器可访问，服务器访问公网和本机均正常。已通过 Frappe 原生 get_meta_bundle 验证主表单包含新按钮和真实后端方法，不将此替代实际浏览器验收。
