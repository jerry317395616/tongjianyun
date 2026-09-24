# 对话驱动业务视图

在已有膳食页面及 SSE 上增量实现，不增加 DocType、字段或数据库迁移。

## 调用链

网页消息携带日期、餐次和当前左侧的选择。`run_task` 给原生 Codex 提供本轮专属
`python -m tongjianyun.meal_view_tool --site ... --task ... --view ...` 调用方式。
Codex 根据需求选择视图及展示形式，工具从任务记录取得真实网页用户身份，调用
已有权限范围及只读业务接口。成功后发送 `kind=view, version=1, selection, title`
事件。浏览器收到后以自身登录状态重新读取视图数据，组件注册表更新左侧内容。

Codex 不提供业务数字、SQL、HTML 或脚本给渲染器。当前可选视图：

- `students`：当前可见启用学生去重总数、启用班级有效成员人数；`table` 或 `bars`。
- `class_students`：有权限的班级名单，只显示姓名、学生编号和学籍状态，50 条分页。
- `meal_counts`：按日期和餐次读取已有确认记录；预计、已确认小计、最终总数不混用。
- `recipe_week`：恢复已有周历，不新建、发布、覆盖或改变食谱。

通用组件为 `stats/table/bars/notice`，周历复用已有实现。新增业务时注册受控数据查询
与需要的组件，不允许聊天生成任意可执行前端代码。Codex 的既有系统权限和其他配置
不变，网页对话仍仅向已有获权管理员开放。

除选择视图外，Codex 可使用 `--components stats bars table` 组合和排序数据组件。
组合按业务类型校验，必要的未知/重复/不完整提示不能被隐藏。默认不传组件参数，
仍使用简洁的数字加表格；用户要求图表或对照时才增加对应组件。

## 交互与隐私

SSE/历史只保存展示选择，不保存名单内容；再次打开会重新检查权限及读取当前数据。
名单姓名不回传模型的工具摘要，网页按权限直接读取。会话存储按账号隔离，只记录左侧
选择；点击聊天中的“查看”可重开结果。慢请求不会覆盖较新请求，失败保留上次内容并提示，
未知人数不写成零。返回食谱保留日期、餐次和全部对话。查询不修改业务记录。

## 部署与验证

部署本次应用文件至 Native Bench，确保没有运行中或排队的膳食对话后，重启原有
`frappe-native-web`、`frappe-native-meal-sse` 和 `frappe-native-worker-meal-chat`。
不修改代理、Codex 配置、服务权限或数据库结构。回滚使用前一提交对应的本次文件，
在任务空闲时重启上述服务；保留原有 SSE 队列和服务。

测试：

```sh
python -m unittest tongjianyun.tests.test_meal_views tongjianyun.tests.test_meal_chat
node --test tongjianyun/tests/test_meal_views_ui.cjs tongjianyun/tests/test_meal_chat_ui.cjs
```

`tongjianyun.tests.test_meal_views.verify_read_only_views` 是 Bench-only 集成检查，输出
汇总和组件类型，不输出学生姓名，并检查查询前后学生、班级、用餐确认及食谱记录数不变。
线上验收还需从原始页面发出真实 Codex 查询，确认 SSE 事件、视图数据 HTTP 请求、
实际渲染、班级下钻、返回周历及刷新恢复；仅通过单元测试不代表页面已经生效。
