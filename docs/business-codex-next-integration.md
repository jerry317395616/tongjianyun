# 普通业务 Codex：下一批接线与验收契约

日期：2026-09-25。审计基线为已提交的 `459b7dd`；真实非 root Worker 已通过，新的网页链路及
餐次来源适配正在后续候选中开发，不能把开发中的第四个读取工具当成写入闭环。
本文是接线审计和下一批交付边界，不是上线或全业务完成声明。
当前部署与真实运行证据以 [统一业务账本](unified-business-goal.md) 和
[Codex 验收记录](business-codex-acceptance.md) 为准；历史工具测试不能冒充新链路验收。

## 总目标不能缩小为教师只读助手

目标保持为服务器 `/home/zyd/frappe` 下全部项目，包括当前及其他站点已安装的全部 Frappe 业务、
独立服务，以及现有模块不能满足时的未知复杂业务扩展。教师点名/逐餐是最先可验证的写入切片，
不是目标范围；三四个读取工具、打开原生表单或一个 QA 成功任务都不能作为整个项目接管的终点。

“全部项目”也不等于把当前站点身份通用于其他站点/服务：每个目标保留自身真实账号、原权限、
业务事务及接口。后续必须为已有领域补实际执行，为独立服务补明确适配器，为未知复杂需求补
可重复的源码实现、测试、部署和业务视图闭环；不是只返回“请另行处理”。

## 交互目标，不增加通用审批流程

用户在右侧说需求，Codex 在其原有业务权限内组织操作，左侧展示真实结果或可办理的业务视图。
明确的自然语言写请求可以直接办理，例如“把本班今天张某的出勤改为请假，原因是发热”。
服务端仍核实真实学生、日期、权限、业务状态和修订号；不得把模型猜测补全为事实。
只有指代不清、事实不全、不可逆或高影响操作需要针对缺失内容确认，不给每次保存再套一层审批。

- `meal_save.confirm` 是原用餐业务中“确认实际餐次”的状态参数，**不是用户授权凭据或审批结果**。
  参数为 `true` 不证明用户要求确认；查询、核对、预计人数不能自动变成实际用餐记录。
- “显示成功”“Codex 回合结束”“单据保存”“实际餐次确认”“结构启用”是不同结果，分别取可信回执。
- 新业务结构创建保持现有管理员授权与明确启用确认。这是变更结构的边界，不扩展为普通登记的审批流。
- 不改变教师角色、不授予 System Manager、不开放任意方法/SQL/宿主命令，不回退旧管理员 runner。
  整个项目继续共用一套 Codex 版本；每个业务任务使用自己的身份、会话和隔离执行。

## 精确现状：已有实现和断开的接点

本表描述 `459b7dd` 审计基线；正在开发的 `meal_read` 来源适配不改变“写工具未接”的判断。

| 能力 | 已有代码 | 当前断点 |
| --- | --- | --- |
| 普通账号右侧任务 | `business_agent_service.run_task()`、`BusinessWorker.run()` | 实际工具只接 `scene_bootstrap`、`class_students_read`、`classroom_read`；`build_prompt()` 也明确禁止写业务 |
| 全站业务发现及原生办理 | `frappe_project_views.catalog_entries()`、`catalog_view()`、`native_view()`、`operation_capabilities()` | 页面已能按原权限打开单据/表单；普通 Worker 没有发现该目录或发布这些视图的工具接线；入口可用不是代理已经执行 |
| 任务绑定视图 | `business_agent_tools._business_view()`；`VIEW_FIELDS` 已含 `frappe_catalog/doctype/document/new` | Worker 拒绝 `business_view`；现包装返回的 summary 不能代替实际来源登记，须接 `FrappeBusinessAuthority.register_read()` |
| 原业务写入 | `business_agent_tools._write()` 委托 `classroom.save_attendance()`、`save_meal()` | `BusinessBinding.execute_write` 未在真实业务 Worker 构造；没有宿主写线程排空证明 |
| 写入去重 | `business_agent_transport.DurableWriteLedger` | 已有持久 intent、同任务 call/digest 去重；身份包含 `task_id`，不是跨任务未知结果防重 |
| 新业务数据方案 | `business_blueprints.validate_spec()`、`propose()`、`preview()`、`activate()`；前端 `renderBlueprint()` | `propose_for_task()` 仍读旧 `meal_chat.TaskStore`、调用旧 `publish_for_task()`；`_access()` 仍是管理员聊天门控 |
| 普通账号蓝图视图 | `meal_views.get_view()` 已有 `business_blueprint` 分支 | `business_agent_tools.VIEW_FIELDS`、`scene_access.BUSINESS_VIEWS` 未开放它，authority 亦无对应的有限来源/权限契约 |
| 提案交接及启用后使用 | 私有 File + revision 绑定启用、精确结构核验 | `_load()` 要求 File 所有者等于当前用户；管理员也不能直接加载教师提案。新类型默认仅 System Manager，不能宣称教师启用后即可使用 |

`business_agent_reads.BusinessReads._bootstrap()` 当前发现的是任教班级，不是全部 Frappe 业务。
`FrappeBusinessAuthority._view_dependencies()` 是入场依赖，不是具体查询的完整 read-set。
不能仅放开工具名、修改提示词或增加几个视图白名单，就声称普通用户业务已经接通。

## 切片一：右侧发现既有业务，左侧直接办理

完整交付：普通用户说“打开我能使用的采购单”等明确需求，右侧按当前站点已安装应用和当前账号
权限查目录、选择原生入口，左侧加载原生列表/表单。用户可继续在原表单办理；代理不得声称代为保存。

实现位置：

- `business_agent_reads.py`：增加有限、分页的业务目录读取和视图选择工具，复用
  `frappe_project_views`，不新建另一套模块清单。结果明确是入口元数据，不是业务记录或人员统计。
- `business_agent_authority.py`：登记实际返回入口及其权限依据；单据入口登记 DocType，具体单据
  登记原记录；控制类类型保持拒绝。预算不足必须返回未完成，而不是删去来源或冒称完整目录。
- `business_agent_worker.py`、`business_agent_service.py`：只接可信适配器，加入真实工具说明，
  通过本任务的 `register_authorities/emit` 发 selection-only 事件，不用旧管理员发布接口。
- 沿用 `scene_access` 对普通账号的已审计 DocType 范围；本切片不顺手开放 Report/Page/Workspace。

验收必须从真实普通用户 HTTP 提交，经 RQ、Worker、固定启动器和模型工具，到持久 SSE 及浏览器
实际加载回执。分别验证目录分页、无权限入口、撤权、错误站点/角色参数和未安装应用；禁止将
“发送了 view 事件”代替“浏览器已显示”。目录已存在但未安装到站点的项目仍不算可用业务。

## 切片二：先接已有点名/逐餐业务写入闭环

完整交付：用户明确要求变更本班某日事实，Codex 读取真实当前状态及修订号，调用原服务保存，
新连接回读并刷新左侧；不打开通用 SQL/任意 DocType 写入口，不复制或绕过原专业业务规则。

建议新增 `business_agent_writes.py` 作为可信执行适配器，复用 `business_agent_tools` 的有限参数
及原服务调用、`DurableWriteLedger` 的持久意图机制。接入前必须完成以下契约。

### 宿主写入与取消收尾

`TaskProxy` 的请求处理使用宿主线程，`_Server.daemon_threads=True`、`block_on_close=False`；
`TaskProxy.close()` 关闭监听和网络连接，不等于正在运行的 `tool_handler` 已结束。
`UnixLauncherRuntime._proof()` 当前 `active_writes=0` 仅适用于现有只读 Worker，不能沿用到写场景。

1. 在开始执行原服务前，以可信任务/claim 登记写意图和宿主执行状态；不得由模型报告 active_writes。
2. 取消先撤销新请求，原事务在提交前再次检查任务及当前权限；禁止取消后才启动排队中的写入。
3. 正在提交的操作必须等到提交/回滚/结果不明被实际核实和持久登记。隔离 cgroup 为空只证明
   Codex 已退出，不证明站点宿主线程、DB 事务及回执处理已经排空。
4. `finish/reconcile` 只有取得可信宿主执行排空证据才收尾；进程崩溃不得把未知写入当成 0。
   若提交已经发生，取消不撤销既有业务事实，也不能返回“什么都没做”。

### 幂等、跨任务未知结果和原生修订

现有 Ledger 在同一任务内以 `call_id` 和操作摘要唯一约束保留 intent；重复调用只读回执或
unknown，不再次执行。这可以复用，但其任务目录及 identity 中的 `task_id` 限定了防重范围。

- 同任务并发、多个 Ledger 实例/HTTP 线程、重复 call_id、换 call_id 但相同摘要都必须覆盖。
- 增加跨任务的持久 operation 标识或原业务对象上的 unresolved fence，绑定站点、用户、对象、
  原修订和动作。提交结果不明时，重发消息/新任务/换 call_id 不能成为再次执行的理由。
- 不明结果首先重新读取并核实原事实；不能证明完成或未执行时保持不明，不盲重放。
  新的合法编辑应基于已核实当前事实，不把模型自己换一个 revision 当作解除未知结果的授权。
- 原 `classroom.save_attendance/save_meal` 的权限、行范围、并发修订、日期、用餐完整性、变更原因
  及审计约束必须保留。原生 revision 是冲突防护，不是跨任务 exactly-once 的证明。

### 独立事务与提交后真实回读

每个请求在线程自己的全新 Frappe 上下文/连接中按绑定账号执行。采用现有
`validate_binding(..., lock_owner=True)` 等提交前检查，不继承管理员上下文、request_cache 或旧快照。
读上下文的 destroy/rollback 不能被误用为写操作成功。

`business_agent_tools._write()` 当前是在同一外层上下文重新调用 `_classroom_read/_meal_read`；
`_actor()` 仅清理 request_cache，不承诺新 DB 连接。新的执行适配器须在提交后、以及读取旧回执时，
独立新连接回读，并登记这次查询的完整实际来源后才交给模型或事件投影。不能把回执内保存的旧名单
重新当作授权数据发出。权限已撤销则阻止数据回传；有提交回执但回读失败应明确“已提交、回读未核实”，
不得说回滚成功或建议重复保存。

`check_business_tools.py` 既有 QA 使用 READ COMMITTED，不能代替生产默认隔离级别下的上述证明。
必须补默认隔离级别、另一连接改变权限/事实、旧回执重放的实际验证。

### 写入切片文件与验收

- 新增：`tongjianyun/business_agent_writes.py` 及其单测。
- 按需修改：`business_agent_transport.py` 及 Ledger 测试，`business_agent_tools.py` 及工具测试；
  `business_agent_authority.py` 和原业务读取器补完整来源观察，不修改原 HTTP 语义。
- 主线接入：`business_agent_worker.py/service.py` 与对应测试；任务终态涉及
  `business_agent_tasks.py` 的改动需单独合并审阅，不直接伪造 runtime 证明。
- 复用隔离 QA 的 `deploy/business_codex/check_business_tools.py`、`check_binding_current_read.py`，
  再增加真实普通用户 HTTP→RQ→Worker→工具→SSE→左侧回读验收；不以直接调用工具替代整链路。
- 至少覆盖：本班成功/跨班拒绝、未知实际人数不当 0、stale revision、未来日期和锁定状态、
  两个同对象并发写、提交前撤权/取消、提交后丢回执、宿主写未排空、跨任务未知结果重试、
  新连接读回及旁观用户不能读取任务/学生数据。

## 切片三：普通用户提出未知业务，受控启用后按原权限使用

完整交付不是“生成一段 JSON”：先检索已有业务；确实没有匹配类型时，保存当前用户的数据型提案，
左侧显示真实预览，支持继续说“加一个数量字段”更新自己方案的版本。经过有权限管理者的结构启用，
再发现该业务并按实际权限进入原生表单。尚未启用或尚无权限时明确说明，不能假称已有记录。

### 可直接复用与必须新增的边界

- 复用 `business_blueprints.validate_spec/revision`、v1/v2 有限字段/子表/计算校验，以及
  `public/meal_scene/views.js` 的 `renderBlueprint()`。不执行模型 HTML、脚本、表达式或权限元数据。
- 新增 `business_agent_proposals.py`：提案以当前可信 claim/owner/site 绑定，持久化使用原 File
  权限或明确审计的私有提案存储；注册提案与 Link 来源后，通过新任务事件发布，不调用
  `propose_for_task()` 的旧 Redis/root 链路。保留作者和 revision，不接受模型提供 actor/owner。
- 将“自己的草稿读取/编辑”与“结构启用”分开授权。不能简单去掉 `business_blueprints._access()`，
  因为它同时保护当前管理员提案、预览和启用路径。
- 当前 `_load()` 仅允许所有者读取，管理员不能直接接管教师私有 File。若需要交管理者启用，
  必须有明确指定接收者、用途和 revision 的最小授权交接；不能改成所有管理员可浏览所有私有提案，
  也不能让管理者假扮教师。界面沿用方案预览上的一个启用/交接动作，不增加独立通用审批中心。
- `activate()` 继续要求真实 DocType/Workflow 创建权限、显式版本绑定确认和创建后结构核验。
  普通业务模型不能自行调用启用、修改元数据或部署代码；复杂库存/财务/外部接口仍按专业扩展验收。
- `_definition_v1()` 默认仅 System Manager，`_state()` 校验固定权限结构；这意味着“建表成功”
  不等于“提出需求的普通用户已能使用”。如需普通角色使用，要由获授权管理者明确设置受审角色及
  行/字段范围，并与蓝图版本/状态核验契约一并实现；不让模型生成权限，也不靠加 System Manager。
  没有该授权则仍保持管理员类型，向用户准确展示这一状态。

### 蓝图切片文件与验收

- 新增：`business_agent_proposals.py` 及测试；复用 `business_blueprints.py/v2.py`，只拆出所需
  有限权限边界和版本绑定交接，不复刻整套结构生成器。
- 配套：`business_agent_tools.py` 的参数/视图表、`business_agent_authority.py` 的提案来源与权限，
  `scene_access.py` 的普通自有提案访问、必要的 `meal_views.py` 及 `public/meal_scene/views.js`。
  Worker/service 统一接入，避免多个代理同时修改共享注册表。
- 复用 `deploy/unified_business/check_blueprint_lifecycle.py`、`check_complex_blueprint_lifecycle.py`、
  `check_blueprint_workflow_guard.py` 和 `verify_browser_blueprint_readback.py` 的隔离 QA 守卫。
- 新验收覆盖：普通用户真实对话生成→私有预览→修改 revision→仅指定管理者交接→明确启用→
  新连接核验真实结构→目录再发现→有权限账号表单保存/回读。权限不足者不得创建结构或查看他人提案。
  还要测 Link 越权、版本过期、重复启用、部分 DDL 失败、结构/权限漂移，以及无角色扩张和原业务不变。
- “创建类型”“启用原生工作流”“写入业务记录”分别记录证据；即便上面全部通过，也不宣称
  任意专业业务、服务器每个独立项目或全部用户角色已经覆盖。

## 后续连续交付：全部领域、独立服务和未知复杂扩展

前三片不是收尾条件。接通公共链路后，须沿用相同身份/写入/回读契约逐个交付实际业务：

- **已安装业务领域**：以 `frappe_project_views.capability_inventory()` 作为原生能力入口事实，
  为采购/库存、财务、资产、HR、教育等原工作流逐项补有限执行适配器及状态链测试。
  `available` 或 `integration=native_in_scene` 不代表可自动写，也不代表该业务已验收。
  报表、独立页面与工作区按实际数据范围补验收，不能永远以当前 DocType 白名单代替全部业务目标。
- **独立项目/服务**：`project_directories()/projects_view()` 目前只列固定根下的源码目录，
  不核验运行状态、认证、可办业务或写回接口。下一实际交付先为一个真实服务建立固定目标、
  独立认证/用户映射、有限操作、原服务幂等/取消/回读适配器，走相同右侧对话和左侧结果视图；
  成功后按逐服务覆盖账本扩展。普通任务不获项目目录、配置文件或通用网络/宿主命令访问权。
- **未知复杂业务**：`extension_policy.evaluate_extension_change()` 只是纯分类规则，
  `business_blueprints_v2` 只是受控结构/计算/原生复核，均不是任意专业扩展执行器。
  需要新增明确业务开发请求的持久记录和管理者授权的开发任务交接，绑定需求版本、目标项目、
  源码变更、测试/部署回执及新增业务入口。普通用户提出需求后能看到开发状态及最后的实际业务视图，
  不继承开发执行器身份。选一个确实超出 v2 的业务，完成源码实现→隔离完整状态链→部署核验→
  原权限下真实业务执行与回读；不得用多建几个字段表代替这项证据。

可新增 `business_agent_catalog.py`（按需从 reads 拆出）、`business_agent_extensions.py`
（开发请求/授权交接，不执行模型任意代码），独立服务适配器按明确服务单独成模块及测试。
这些文件是后续拥有边界建议，不是当前已经存在或已实现的能力；不要在已有教师工具文件里
添加万能 execute-method 接口。管理开发任务的执行权限、结构变更和部署仍按目标项目已授权边界核实，
不能把“业务用户发了一句话”自动转换为跨项目管理员权限。

### 2026-09-26后续落地状态（不改变完整交付门槛）

普通Worker已接 `BusinessCatalog`、`BusinessWrites`、原账号独立事务适配器和
`BusinessExecutionRuntime`；目录真实只读QA18项、原生写入QA17项通过，完整后端864项通过。
这更新上文459b7dd基线中的“未接线”状态，但没有把两类原服务验收代替HTTP/RQ/模型/SSE/网页
验收。真实网页旧任务仍为failed，不自动重跑。宿主崩溃后active恢复、普通附件、蓝图提案交接、
专业业务全状态链及独立服务/复杂源码扩展仍未完成；下一阶段必须继续沿实际执行闭环交付。

随后候选进一步接通任务绑定的 TXT/CSV/XLSX 附件与普通私有版本化提案；后端954项、前端
167项回归通过，细节与限制见 [附件与方案候选](business-agent-attachments-proposals.md)。
这更新“普通附件/草稿工具尚未接线”的代码状态，但不替代真实上传/模型/保存验收，也未完成
管理者交接 HTTP/UI、结构启用后原权限使用、复杂源码扩展和生产上线。

目录只读网页链路现已实际通过（`994f1ff9-9803-4b53-8e41-ece64ef6fb38`），含刷新恢复与
真实左侧目录；3次早期命令失败的具体分类仍缺证据，后续须补不含参数/原始异常的有限工具
诊断。不能因为目录成功就跳过原业务写入、附件上传和方案交接的独立整链路验收。

## 合并顺序与结果声明

先交付目录/原生视图闭环，再交付已存在领域的真实写入闭环；蓝图提案可独立开发，但注册表、
authority 和 Worker 由主线串行合并。每一片都以真实普通账号整链路证据为完成条件，不以提示词、
模拟回执、入口数量或单元测试数量作为业务覆盖率。生产开放、管理员结构启用与各项目部署仍须
分别核实；本文件不授权改变生产权限或执行任何部署。
