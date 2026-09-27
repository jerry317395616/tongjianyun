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
- `recipe_nutrition`：复用 `nutrition_sheet.get_nutrition_sheet` 的整周营养分析；按业务日期
  选择唯一可见食谱，多份时提供点选，无匹配时不退回最近食谱。食谱主单和全部明细读取
  权限仍检查；班级筛选不允许静默丢弃无权限项。默认自动标准，档案错误不自动降级手动。
  可在对话中指定食谱、园内供给目标、统计班级或明确要求手动年龄/性别口径。
  这些筛选只影响本次查询，不写食谱、不冻结人口快照、不导出附件、不更改营养规则。
  默认按原 Excel 导出模板显示完整带量分析表：食物分类与五组食物/重量列、各餐热量比例、
  营养标准/实给量/评价、食谱口径和结论建议。合并区域、列比例和边框复用同一模板。
  表头固定，窄屏在表格内滚动；概览只保留简洁提示和调整/导出操作，不再显示三张大卡。
  全部食材口径折叠补充显示（含原模板未列出的油脂、水），超出分类容量的食材不丢弃。
  缺少有效食材用量时不把原服务的零估算显示为偏低或达标。
  `frappe_page/weekly-recipe-nutrition-sheet` 经原页面权限检查后切换到这份业务视图，
  原 Desk 页面及其菜单不再嵌入场景，其他原页面暂时保留。
  “请助手调整食谱”仅准备未发送消息，不自动提交、不覆盖已有输入。
  “导出分析报告”是独立明确操作：确认后调用 POST `meal_nutrition_view.export_view`，
  重新核对账号、食谱全部行及统计班级权限，再沿用原导出服务。
  原导出可能冻结人口标准快照并保存附件，查看视图不会调用导出。

通用组件为 `stats/table/bars/notice`，营养专用组件为 `nutrition_overview/nutrition_sheet`，周历复用已有实现。新增业务时注册受控数据查询
与需要的组件，不允许聊天生成任意可执行前端代码。Codex 的既有系统权限和其他配置
不变，网页对话仍仅向已有获权管理员开放。

除选择视图外，Codex 可使用 `--components stats bars table` 组合和排序数据组件。
组合按业务类型校验，必要的未知/重复/不完整提示不能被隐藏。默认不传组件参数，
仍使用简洁的数字加表格；用户要求图表或对照时才增加对应组件。

## 交互与隐私

SSE/历史只保存展示选择，不保存名单内容；再次打开会重新检查权限及读取当前数据。
名单姓名不回传模型的工具摘要，网页按权限直接读取。打开或重新加载页面默认显示周食谱，
不恢复之前的左侧选择，也不因回放聊天历史切换视图；日期、餐次沿用页面当前上下文。
新收到的视图事件仍会自动切换，点击聊天中的“查看”可重开历史结果。
页面内刷新数据保留当前视图。慢请求不会覆盖较新请求，失败保留上次内容并提示，
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
python -m unittest tongjianyun.tests.test_meal_nutrition_view
```

`tongjianyun.tests.test_meal_views.verify_read_only_views` 是 Bench-only 集成检查，输出
汇总和组件类型，不输出学生姓名，并检查查询前后学生、班级、用餐确认及食谱记录数不变。
线上验收还需从原始页面发出真实 Codex 查询，确认 SSE 事件、视图数据 HTTP 请求、
实际渲染、班级下钻、返回周历及重新加载默认周食谱；仅通过单元测试不代表页面已经生效。

仅调整默认视图的前端发布无需重启服务；同步 JS/HTML 及更新的资源版本号后，
验证重新加载默认周食谱、历史结果可重开、再次重新加载仍回到周食谱。

营养视图发布需在对话队列空闲时重启原 Web / SSE / meal_chat worker；不运行迁移。
`tongjianyun.tests.test_meal_nutrition_view.verify_live_nutrition_view` 对照原服务各指标和评价，
并检查食谱、菜品、食材、附件记录数不变。还须从真实对话验证 Codex → SSE → 营养视图，
验证 Excel 表格、固定表头、表内滚动、返回食谱及刷新默认周历。原 Desk 营养分析和 Excel 导出入口保持不变。

Excel 版式增量发布使用 `release_nutrition_excel.py`：先检查当前七个目标文件的哈希，
仅替换这次组件和资源版本，保留线上其他代码差异。新备份单独存放，不覆盖上一轮备份。
`verify_nutrition_canvas.py` 在数据库强制 READ ONLY 会话里逐单元格对照原导出结果，
五处历史单位/标签勘误除外；不会调用导出或新增附件。纯投影测试可独立运行：

```sh
python -m unittest tongjianyun.tests.test_nutrition_canvas_sheet
python deploy/meal_chat_views/serve_nutrition_preview.py
```

预览只监听本机 23403 端口，使用合成数据，不代表生产营养结果；Ctrl+C 停止。
