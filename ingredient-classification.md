# 食材物料组 AI 分类：只读预览阶段

服务位于 `tongjianyun.ingredient_classification.preview_recipe(recipe)`，供后续保存流程调用。
当前没有保存钩子、前端按钮、自动创建物料或物料组，不会修改任何 DocType。

- 使用当前用户权限读取食谱、完整食材明细及可见物料组；只发送食材名称、单位和分类目录，不发送幼儿或财务数据。
- 仅调用 IONE Agent 已配置的结构化模型接口。不使用其菜品关联本地降级结果冒充 AI 分类。
- 必须完整返回原始食材 key；拒绝未知操作、重复/遗漏、额外字段和无效分类。
- 已有分类必须是可见明细组；新组建议必须有现有父级组、规范名称，单次不超过 5 组。
- 汤、粥等菜品强制转人工核对；模型建议不能绕过采购成品确认。
- 调用错误不输出原始异常，避免暴露请求凭据。

测试：`env/bin/python -m unittest tongjianyun.tests.test_ingredient_classification tongjianyun.tests.test_ingredient_resolution tongjianyun.tests.test_recipe_procurement`

## 尚未完成

`child.myyr.top` 本阶段实测结构化接口及 Dify 接口均未配置。这不表示 Harness 自身没有可用模型。
需确认平台要复用的模型服务，由受控配置提供地址、模型及必要认证；不得把凭据写入源码或提交 Git。
接通后先以真实食材执行只读分类验收，再实现保存后的后台任务、权限校验、并发防重、标准 ORM 建档及失败反馈。
不得把本阶段的预览服务描述为已实现“保存食谱自动创建物料”。
