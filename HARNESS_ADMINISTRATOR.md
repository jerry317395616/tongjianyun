# Administrator 业务权限：查询已上线，写入未开放

业务执行器位于 `tongjianyun/harness_administrator.py`，身份适配器位于 `deploy/shared_harness_pilot/administrator_authority.py`。child 站点现已明确准入 Administrator。Harness 仍只公开 describe/list/get：Administrator 的业务查询使用童健云固定只读工作进程；普通账号继续使用原身份执行器及原来的四个 DocType 查询范围。

原始入口链：Frappe 签名登录 → `harness.myyr.top/employee/sso` → 共享会话控制器 → 私有 Unix 身份服务 → 按已验证身份选择执行器。没有给浏览器 Host 控制凭证，也没有修改 Harness、Frappe 或 IONE Core 源码。

## 已实现

- 仅接受 child.myyr.top 当前已认证、启用的 System User `Administrator`；不把 `admin`、同名角色或请求参数提升为管理员。
- 基于实际 DocType 元数据读取明确的安全字段。分页最多 100 条，只允许等值过滤，不接受表达式、SQL、任意方法或脚本。
- 单据新增、标量字段更新、提交、取消、删除的单条预览及内部执行函数。
- 通过 Frappe `insert/save/submit/cancel/delete` 执行，保留权限、业务校验、钩子、链接检查；不使用强制删除、跳过权限或直接 SQL。
- 变更前加记录锁并重新检查预览及 modified；执行后重新读取结果。事务由未来的可信适配器管理，执行器不自行提交。
- 冻结结构、账号权限配置、代码执行类配置和敏感字段；拒绝单例、虚拟表和子表直接操作。子表写入须接现有应用服务，不绕过校验。
- Administrator 准入同时检查精确账号名、签名、启用状态、站点和功能开关；注销或停用后，在途查询不返回业务结果。
- 查询上线单元测试覆盖 39 项；真实签名 HTTP 验收覆盖管理员 Item 查询、普通账号越界拒绝、敏感字段拒绝和会话隔离。生产业务记录不变，验收会创建 Harness 对话。

## 确认与审计适配器（已完成内部验证，未对外开放）

`tongjianyun/harness_administrator_approvals.py` 复用现有 `I-ONE MCP Audit Log`，没有新表、迁移或字段修改。源码与当前站点元数据已核验兼容。53 项相关单元测试通过；Native ORM 验证只写入临时审计记录并全部回滚，业务执行使用替身，不等同于真实业务写入验收。

- `create_preview` 保存当前会话绑定、具体预览、摘要和 10 分钟有效期，不改目标单据。
- `confirm_preview` 锁定预览记录后登记受理记录，再执行 Frappe 业务操作。确认入口必须与 AI 工具分开，不能接受模型自我批准。
- 业务修改与成功审计结果在同一事务提交。重复确认读取已有结果，不再次执行。受理成功不表示业务成功，两者使用不同工具名称和审计记录。
- 已受理但结果未知时返回 `outcome_unknown`，必须核查，不能自动重试。失败审计仅记错误类型，不写可能包含私密值的异常原文。
- 该模块仅能在专用、独立事务的可信工作进程调用；没有 Frappe 白名单方法或公开 HTTP 路由。生产 `tongjianyun_harness_administrator_writes_enabled` 仍未开启。
- 通用业务执行器禁止访问 `I ONE AI` 和 `Flow` 控制模块，模型不能通过普通字段更新修改自己的审批、审计或执行策略。

现有 `I-ONE Approval Request` 的批准函数会自动排队运行 I-ONE AI 任务，不可直接用于本次确定性单据确认。审计写入采用正常 ORM 且失败必须阻止业务成功，不使用现有会吞掉审计错误的尽力记录函数。外部通知、文件和第三方调用不具备数据库回滚语义，发生异常时仍需核查相关副作用。

## 写入开放前必须完成

1. 在现有只读通道之外注册 Administrator 专属预览工具和独立人工确认入口，不能把写方法伪装成 read。
2. 将已完成的服务端预览存储接入可信会话，确保绑定值不能来自模型输入。
3. 浏览器明确展示站点、操作、记录、字段和影响数量，人工确认通过独立 CSRF/Origin 校验入口提交。
4. 将内部确认执行器接入 HTTP 身份与 Origin/CSRF 校验，补充跨进程并发和崩溃恢复验证；中断/重试不得重复执行。
5. 真实会话测试可回滚业务变更、重复提交、撤销登录、并发变更和失败回滚。当前未进行生产业务写入验收。
6. 写入需要另设独立开关；当前 `tongjianyun_harness_administrator_enabled` 只开放身份与业务读取适配器，不等于公开写工具。

`Preview.digest` 仅用于完整性和过期数据检测，不是签名或授权凭证。禁止从模型/HTTP JSON 重建 Preview 后执行。当前内部函数不能替代审批和审计适配器。

当前 Harness 的 `EmployeeTurns` 硬编码只允许 `employee_frappe_read`，其 JSON schema 也仅支持 describe/list/get，没有外部应用注册受控预览工具的扩展接口。接入 AI 预览需要对 Harness 增加最小的通用扩展点，或替换整套会话插件。应优先明确授权前者，避免在童健云复制会话生命周期和身份实现；业务与审批代码仍归属童健云。

本阶段没有新增或修改任何 DocType、字段、权限元数据或数据库结构，也没有变更生产业务记录。

## 运行与回退

身份服务使用 `95-administrator.conf` 覆盖启动入口；原 `90-shared-live.conf` 和原身份配置保持不变。重新启动身份服务会撤销内存中的 Harness 登录，用户需从 Frappe 重新进入。

关闭管理员准入可通过 Frappe 配置函数将 `tongjianyun_harness_administrator_enabled` 设为 0；管理员的后续身份检查即失败，普通账号不受影响。若需退回原服务入口，移走仅本次新增的 `95-administrator.conf`，执行用户级 daemon-reload 并重启身份服务。不要删除原配置、账号或业务数据。
