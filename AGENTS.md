# Tongjianyun 扩展应用规则

本应用是当前 Native Bench 的唯一业务定制代码归属。分析问题时可以读取
`/home/zyd/frappe/native-bench/apps` 下的所有已安装应用，但不得把业务修改写入
Frappe、ERPNext、Education、IONE Core 或其他上游应用。

## 实施边界

- 表单和列表增强使用 `doctype_js`、`doctype_list_js` 与本应用 `public/js`。
- Python 行为扩展使用 `doc_events`、`override_doctype_class`、
  `override_whitelisted_methods` 或本应用自己的白名单服务。
- 新建 Desk Page、Report、Workspace 时，其标准文件必须位于本应用模块目录。
- 翻译仍统一维护在 IONE Core；不要在本应用复制通用平台翻译。
- 禁止新增 DocType，禁止直接编辑任何上游应用的 DocType JSON。

## 字段和属性

字段结构变更不是普通页面修改。只有用户明确要求了目标 DocType 和字段，并已看到
字段类型、默认值、必填、权限、现有数据迁移及回滚预览后，才允许通过 Tongjianyun
维护的 Custom Field / Property Setter fixture 实施。字段删除、字段改名和不兼容类型
变更默认禁止，优先采用新增字段、迁移数据、停用旧字段的兼容流程。

任何未明确要求字段结构的任务，不得顺带创建 Custom Field、Property Setter、补丁、
DDL 或数据库结构变化。

## 验证

修改前先解析用户原始路由并锁定真实调用链。修改后运行最小相关测试、必要的资源构建
和缓存更新，并回到原始 URL 验证页面和网络请求。仅检查源码或 Python 返回值不能证明
界面修改已生效。
