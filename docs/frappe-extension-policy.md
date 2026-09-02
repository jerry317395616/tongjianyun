# Frappe 业务扩展落盘规范

## 目标

Native Bench 中所有应用都可以作为只读事实来源；所有客户化业务源码只进入
`apps/tongjianyun`。这样升级 Frappe、ERPNext、Education 或 IONE Core 时，不需要手工
重做上游源码补丁，也可以通过 Tongjianyun 仓库审查、测试、发布和回滚全部定制。

## 扩展方式

| 需求 | Tongjianyun 中的实现位置 | Frappe 机制 |
| --- | --- | --- |
| 表单展示、按钮、前端校验 | `tongjianyun/public/js/<doctype>.js` | `doctype_js` |
| 列表列、筛选、菜单 | `tongjianyun/public/js/<doctype>_list.js` | `doctype_list_js` |
| 单据服务端事件 | `tongjianyun/integrations/<source_app>/` | `doc_events` |
| 类行为覆盖 | `tongjianyun/overrides/` | `override_doctype_class` |
| 白名单接口覆盖 | `tongjianyun/overrides/` | `override_whitelisted_methods` |
| 新的 Desk Page | `tongjianyun/tongjianyun/page/` | 标准 Page 文件 |
| 新的报表 | `tongjianyun/tongjianyun/report/` | Script/Query Report |
| 工作区入口 | `tongjianyun/tongjianyun/workspace/` | 标准 Workspace 文件 |
| 经确认的字段/属性扩展 | `tongjianyun/custom/` | Custom Field / Property Setter fixtures |

`hooks.py` 只负责声明入口，实际业务逻辑应位于独立服务模块中，保持可测试。不要复制整段
上游 Controller；覆盖前应读取当前版本源码，只覆盖必要方法，并保留上游校验、权限和审计。

## 每次修改的固定流程

1. 用用户给出的 URL 解析 Page、Report、Workspace 或 DocType，并锁定前端入口和后端调用。
2. 阅读上游源码、DocType 元数据、相关测试和童健云已有扩展。
3. 调用扩展规划工具，确认上游只读文件和 Tongjianyun 目标文件。
4. 若涉及字段，先输出结构影响预览并等待明确确认；否则不得改结构。
5. 在 Tongjianyun 内实现最小变更并增加测试。
6. 运行测试；构建、迁移或清缓存只使用审批式固定部署工具，并逐项获得用户批准。
7. 在原始 URL 验证 UI 和实际请求；记录提交，支持回滚。

## 明确禁止

- 新增 DocType。
- 修改上游应用文件或上游 DocType JSON。
- 仅凭中文标题或相似文件名决定目标。
- 用任意 SQL 或动态 Python 绕过 Frappe ORM、权限、钩子和校验。
- 未经字段级预览与确认创建 Custom Field、Property Setter 或迁移补丁。
