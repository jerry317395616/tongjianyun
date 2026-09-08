# 食材物料组 AI 分类：复用 Harness 模型的只读预览

服务位于 `tongjianyun.ingredient_classification.preview_recipe(recipe)`，供后续保存流程调用。
当前没有保存钩子、前端按钮、自动创建物料或物料组，不会修改任何 DocType。

- 使用当前用户权限读取食谱、完整食材明细及可见物料组；只发送食材名称、单位和分类目录，不发送幼儿或财务数据。
- 调用 Harness 进程现有 `llm.stream` 服务，以 `agentDefaultModel.currentSelection()` 获取平台默认提供商、模型及推理配置。不读取或复制模型密钥，不跟随某个个人会话的临时模型选择。
- 本机 Unix socket `/home/zyd/frappe/state/ingredient-model/bridge.sock` 权限 0600，父目录 0700，由 zyd 持有。无新增公网端口；仅供受信任的本机服务使用，不构成同一 Linux 用户内部的安全隔离。Frappe 入口负责当前账号的数据权限校验，未暴露任意提示词代理。
- 固定分类提示词、严格输入字段，只接受食材和分类目录；工具列表为空，不创建 Agent 会话、不执行工具。每批最多 20 食材，桥接并发最多 2，请求/结果各最多 128 KiB，单次桥接超时 60 秒。Python 在结果返回后执行完整分类校验。
- 必须完整返回原始食材 key；拒绝未知操作、重复/遗漏、额外字段和无效分类。
- 已有分类必须是可见明细组；新组建议必须有现有父级组、规范名称，单次不超过 5 组。
- 汤、粥等菜品强制转人工核对；模型建议不能绕过采购成品确认。
- 调用错误不输出原始异常，避免暴露请求凭据。

测试：`env/bin/python -m unittest tongjianyun.tests.test_ingredient_classification tongjianyun.tests.test_harness_ingredient_client tongjianyun.tests.test_ingredient_resolution tongjianyun.tests.test_recipe_procurement`

桥接测试：`node --test deploy/shared_harness_pilot/test_ingredient_model_bridge.mjs deploy/shared_harness_pilot/test_native_ui.mjs deploy/shared_harness_pilot/test_native_models.mjs`

桥接随童健云已有 `native-ui.mjs` 扩展挂载，在 Harness 中运行；源码仍全部在童健云中。更改桥接后需重启 `systemctl --user restart ione-harness.service`，会短暂中断当前连接。正常食材预览调用不需重启。

本阶段实测：最近食谱 73 项食材完成只读分类，70 项建议使用现有明细组、3 项待核对，0 项新组建议；访客被拒绝。Item 70 个、Item Group 14 个保持不变。这验证的是调用与结果结构，不等于人工审定所有分类的业务准确性。

## 尚未完成

结构化模型和 Dify 的单独配置不再是这个预览功能的前置条件。无需改动它们的配置。
后续仍需实现保存后的后台任务、权限校验、并发防重、标准 ORM 建档及失败反馈。
不得把本阶段的预览服务描述为已实现“保存食谱自动创建物料”。
