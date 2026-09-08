# 食材自动建档：复用 Harness 模型

分类预览位于 `tongjianyun.ingredient_classification.preview_recipe(recipe)`；保存后的自动处理位于 `tongjianyun.recipe_item_sync`。不修改任何 DocType 或官方应用代码。

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

## 保存后自动处理

结构化模型和 Dify 的单独配置不再是这个预览功能的前置条件。无需改动它们的配置。
手工保存及导入保存共用 `recipe_storage._save_current_recipe`，事务提交后才进入 long 队列。任务保留发起账号身份，模型调用后再次校验账号启用状态、权限及食材版本。队列或模型失败不回滚已保存食谱。

优先匹配唯一、启用、可采购的库存物料及兼容单位；无匹配时由 Harness 默认模型建议分类，再使用 ERPNext 标准 ORM 创建 Item、必要的叶子 Item Group。重复名称、未知单位、汤粥等歧义项目保留待核对，不猜测密度，不创建单位。后台自动任务通过 Redis 锁串行写入，并使用确定性物料编号防重；这不保证其他独立写入者使用不同编号时的名称全局唯一。

匹配回执复用 Tongjianyun Food Purchase 的 `erp_recipe_auto_mapping` 业务记录类型，不是实际采购执行记录。采购预览复用结果，人工已确认的公司映射优先；毛料系数仍须核对。本流程不自动提交采购、库存或财务单据。

食谱详情的“食材物料匹配结果”按钮显示状态、创建数量及待核对原因，可刷新状态。失败修正后重新保存可重试；历史食谱不自动批量回填。工作进程被强制终止时缓存状态可能滞后，需检查队列后重试。

权限必须同时满足食谱、食材、物料及回执的相应读写要求；创建物料组还需 Item Group 创建权限。部署时实测 Administrator 满足要求，普通 admin（317395616@qq.com）缺少 Item 读取和创建权限，因此不能自动建档；未绕过或修改这些权限。

验证：50 项 Python 单元测试；`check_recipe_item_sync_live` 使用真实 ORM 验证建档、重复执行、版本冲突、采购复用及权限拒绝，最后全部回滚；`check_recipe_procurement_live` 15 项检查通过；`check_recipe_item_sync_queue` 验证真实 long 队列保留用户身份且删除自身测试任务。未为测试保留生产物料、分类或食谱。
