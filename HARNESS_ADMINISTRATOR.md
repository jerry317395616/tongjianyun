# Administrator：业务查询、变更预览与独立确认

child.myyr.top 的 `Administrator` 可在共享 Harness 中查询获准的业务数据，并提出单条业务记录变更。AI 只生成预览；用户核对页面卡片并勾选确认后，独立的浏览器请求才执行操作。普通账号维持原有只读范围，不能通过用户名、角色名称或提示词提升权限。

## 代码归属

所有业务权限、字段筛选、预览、确认、审计和中文界面均保留在童健云：

- `tongjianyun/harness_administrator.py`：业务元数据、查询、冻结的单条变更及正常 ORM 执行。
- `tongjianyun/harness_administrator_approvals.py`：10 分钟预览、登录和会话绑定、防重执行、事务审计与结果核查。
- `deploy/shared_harness_pilot/administrator_authority.py`、`administrator_worker.py`：验证真实登录身份，调用固定工作进程；不接受模型指定账号、站点、函数或代码。
- `tongjianyun/public/shared_chat/`：中文对话、变更前后值、影响数量、独立勾选确认和执行回执。
- `deploy/shared_harness_pilot/presets/tongjianyun-business/`：业务助手预设。

经单独授权，Harness 仅增加通用的应用能力查询、预览工具和独立确认传输。工具参数要求 JSON 对象，历史恢复由服务端读取真实游标；Harness 不包含童健云审批或业务规则。

## 使用与边界

使用 `Administrator` 登录 Frappe 后，从桌面进入 Harness。提出具体业务修改需求，核对卡片中的站点、账号、操作、目标记录和修改前后值，勾选后点击“确认执行”。聊天中的“确认”不是执行授权。操作结束后，以卡片回执和业务单据实际状态为准。

- 仅开放 child 站点精确的、已启用的 System User `Administrator`；`admin` 仍是普通账号。
- 查询只允许明确的安全字段、等值过滤和有限分页，不支持任意 SQL、脚本或方法执行。
- 内部执行器支持单条新增、标量字段更新、提交、取消和删除，全部经过 Frappe 正常权限、校验、钩子及链接检查。
- 不新增或修改任何 DocType、字段、权限元数据、Custom Field、Property Setter、命名规则或数据库结构。账号权限、代码执行配置、敏感字段、单例和子表直接写入被拒绝。
- 子表、复杂财务单据及批量业务尚未接入专用应用服务；不能把单条标量修改验收视为这些场景已经可用。
- 预览与当前登录、具体对话绑定，其他账号和其他对话不能确认。服务重启撤销登录后，需重新登录并生成新的预览。

## 执行一致性

复用现有 `I-ONE MCP Audit Log` 保存预览、受理和结果，不改变其结构。确认工作进程先清除身份查询形成的旧事务快照，再通过 Frappe Query Builder 对预览主键做参数化行锁查询；锁定后检查已有受理记录。这样既能看见竞争请求已经提交的受理结果，也不对审计表的非索引字段施加范围锁。

受理记录先持久化，业务保存与成功审计随后在同一数据库事务提交。重复确认返回已有结果，不再次执行。受理成功不代表业务成功；已受理但结果尚不可知时返回 `outcome_unknown`。若请求中断、进程崩溃或提交回执丢失，用户应点击“核查执行状态”，不得再次发起同一业务来猜测结果。

执行前重新核对单据状态和 modified；预览后记录发生变化时拒绝执行。业务失败回滚数据库变更并留下失败审计，仅记录错误类型，不保存可能包含私密值的异常原文。外部通知、文件和第三方调用不具备数据库回滚语义，发生异常仍需人工核查。

## 验收依据（2026-09-08）

童健云 58 项 Python 测试、10 项对话客户端测试通过。Harness 的 23 项会话/HTTP/工具回归和两个真实进程录制回放场景通过。

`deploy/shared_harness_pilot/accept_application_live.py` 使用真实签名登录、实际模型和浏览器，在一条独立 UOM 测试记录上验证：生成预览不改变记录、勾选后独立执行、写入回读、重复和并发确认只执行一次、变更后旧预览被拒绝、普通账号和跨会话确认被拒绝。测试记录已删除，审计保留；现有学生、食谱和财务记录未改变。该验收不是全部业务单据或外部副作用的验证。

`probe_concurrent_approval.py` 直接启动两个独立 Frappe 工作进程验证同一预览的并发确认，断言仅一条受理及一条结果，并清理专用测试记录。单元测试还覆盖提交回执丢失、失败审计、登录变化和不确定结果禁止重试。

## 运行与关闭

主运行目录为 `/home/zyd/frappe`。业务源码在 `native-bench/apps/tongjianyun`。`95-administrator.conf` 指定童健云身份服务；`96-application-previews.conf` 为共享 Harness 加载童健云 `administrator-runtime.yml`。普通用户与 Administrator 使用同一个 Harness，不向浏览器提供 Host 控制凭据。

`tongjianyun_harness_administrator_writes_enabled=1` 开放预览和独立确认。紧急关闭时，通过 Frappe 配置函数将其设为 0；后续工作进程拒绝写入，已经受理的操作仍需核查，不可假设关闭开关会回滚它们。`tongjianyun_harness_administrator_enabled` 控制整个 Administrator 准入，独立于写入开关。

身份服务重启会撤销其内存登录，用户需从 Frappe 重新进入。回退通用接口时，应先关闭写入，再移走本次 `96-application-previews.conf` 并恢复原对话部署；保留审计、业务记录和原有身份配置。
