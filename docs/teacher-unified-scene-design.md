# 普通教师进入统一场景：授权边界与实施方案

2026-09-25；只读审计及设计，不代表已经向教师开放对话。

## 结论

可以让教师在同一 `/tongjianyun-meal-scene` 页面办理其已有权限内的业务，但必须拆开
**页面访问、业务读取/办理、管理员 Codex 执行**三个权限，不能把教师加入现有聊天白名单。

现有 Codex 执行器明确具有 Linux root 文件、命令及网络能力。`frappe.set_user(teacher)`
约束的是经过 Frappe 权限检查的业务调用，不约束 root 读取数据库配置、改源码或直接连接
数据库。提示词“遵守教师权限”、只隐藏按钮、为教师切换 cwd 或仅换一个 Linux 非 root
账号，都不能独立证明隔离成立。

推荐分两步交付，同一界面最终使用两个服务端判定的执行通道：

- 先解耦场景和业务视图：教师可在左侧真实查看、点名、逐餐核对；右侧明确告知业务对话
  尚未启用。此阶段不是“教师已由 Codex 接管”，也不能用关键词响应替代 Codex 验收。
- 再接入真正受隔离的业务 Codex：只能通过绑定当前用户的业务工具代理调用原服务。
  管理员项目开发通道保持独立；教师既不能选中该通道，也不能继承其会话、附件或权限。

## 审计依据及当前授权链

### 本轮候选实现状态：已实现，尚未上线或通过真实教师浏览器验收

以下描述当前工作区的候选代码，不是生产已开放声明，也不替代后文的隔离与业务验收。

- 新 `scene_access.get_bootstrap` 只读返回账号、正规化日期/餐次、周食谱读取能力、默认
  selection、最小导航及授课范围摘要。账号必须启用且为 System User；请求不接受 actor、
  角色、站点或执行器覆盖。班级参数必须在当前服务端范围内，不给用户分配任何角色。
- 场景 HTML 与 `meal_views.get_view` 已拆开场景账号门和具体业务门。普通账号候选开放
  学生、班级学生、点名、用餐核对四类投影视图，以及仍校验原权限的原生 DocType
  列表、文档与新建视图；周食谱必须已有 Recipe 读取权。**报表、独立 Page、Workspace
  的统一场景入口仍仅向原管理员通道开放**，没有把“所有原生入口存在”视作普通账号
  范围验收完成。原系统已有链接和权限保持不变，不声称该限制替代原生页面授权。
- 服务器项目目录新增独立管理员门。私有业务方案仍要求管理员聊天权限、本人 File
  所有权、私有属性及站点/创建者一致；现有 root Codex 发布工具也再次核验任务 owner
  当前的管理员聊天权限。场景账号门不授予服务器、方案启用或 Codex 执行能力。
- `scene_bootstrap.js` 是当前页面两个模块共用的单次请求，不存入跨用户缓存。
  `app.js` 对无食谱权限账号不请求 `get_overview`，也不开周历自动刷新定时器。
  `chat.js` 先独立初始化左侧；教师右侧明确说明业务对话尚未开通，隐藏发送表单，
  不读取管理员会话历史、不启动 SSE、不上传文件、不创建 Codex 任务。
- 教师的日期、餐次和少量业务按钮放在左侧场景内部，不恢复已移除的顶部工具栏。
  返回按钮回到当前账号场景首页；切换和刷新沿用未保存/保存中保护。学生主数据的
  服务端 selection 不保留日期，前端只保存该场景上下文供下一次点名或用餐使用，
  不把学生名册伪装成按日筛选的历史名单。管理员仍默认周历及原真实聊天。
- bootstrap 失败时不回退到授权成功或空食谱；右侧显示错误和重新加载按钮。模板
  app 资源更新为 `teacher-scene-20260925-1`；chat/views 继续使用本轮 `v5`。
  隔离浏览器切换候选资产时还须把新共享模块加入资源摘要校验，并允许固定的只读
  bootstrap RPC；不能只同步旧文件后声称新前端已验收。

当前前端验证包括教师默认视图、最小导航、跨视图日期/餐次、未保存阻止切换、无周历
请求/定时器、无教师聊天历史/SSE、初始化错误与管理员兼容。VM/单元测试不等于真实
Cookie/CSRF/浏览器、点名或用餐落库验收。本轮尚未证明真实教师浏览器链路可用，
更没有实现第二阶段的隔离业务 Codex；不得宣传为“教师 Codex 已接管”。

独立复核还发现两处新边界下的失配动作：班级点名的通用分页返回 `business_catalog`，
以及普通账号原生收货/库存单详情给出 `stock_reconciliation`，而两类入口仍需管理员。
这些是会被服务端拒绝的死入口，不是越权成功。候选代码已把普通账号点名页的返回动作
改为 `frappe_catalog`，并隐藏无管理员聊天权限账号的库存核对动作，补入对应测试；
仍需随完整候选回归及教师浏览器验收核对。资产原生历史删除问题另见 `asset-acceptance.md`。

本地及生产 app HEAD 均已只读核验为 `b8b43b73ec36e1f807b9b155211ba3da9e2d0ac2`。
本审计未读取密钥、站点配置或凭据，未修改服务器、角色、执行器或生产数据。

| 环节 | 当前代码与行为 | 教师被拦的位置 |
| --- | --- | --- |
| 工作空间入口 | `workspace_entry.entry_model`、`resolve_entry` | `teacher_only` 不添加 meals 入口，教师仍跳到原课堂 |
| 场景 HTML | `www/tongjianyun_meal_scene.get_context` → `meal_scene.require_access` | 要有食谱、采购、收货读取权限，或 Warehouse/Bin/Item 三者读取；教师班级权限不在其中 |
| 周历初始化 | `public/meal_scene/app.js` 的 `load` 及自动刷新 → `meal_scene.get_overview` | 再次 require_access；并且应用启动、刷新、回到周历逻辑依赖膳食数据 |
| 左侧视图 | `meal_views.get_view` → `meal_chat.require_chat_access` | 不论查看学生、点名还是原生表单，都先要求管理员对话权限 |
| 前端初始化 | `public/meal_scene/chat.js` 底部 | 只有 `get_chat_access.allowed` 为真才调用 `initializeViews`，所以只放开 HTML 仍不可用 |
| 聊天入口 | `get_chat_access` / `require_chat_access` | require_access 后，仅 Administrator 或 System Manager 可用 |
| 聊天运行 | `send_message` → RQ `run_task` → `_command` | worker 再检查同一权限；执行 `/home/zyd/frappe/.codex-deepseek/bin/codex-deepseek`，cwd 为 `/home/zyd/frappe` |
| 模型说明 | `meal_chat.execution_instruction` | 明确描述 root、完整文件/命令/网络、无交互命令审批；不是教师沙箱 |
| 视图工具 | `meal_view_tool.use_site_os_identity` → `publish_for_task` | 子进程降为站点 Unix 所有者；任务 owner 来自 Redis，再 set_user 并 get_view；不会降低 Codex 父进程权限 |
| 历史与 SSE | `TaskStore`、`_owned_task`、`get_conversation`、`stream_events` | 站点前缀、用户哈希、严格任务 owner；目前只服务上述管理员通道 |

还有一个解耦后的显式权限补位：`frappe_project_views.projects_view` 当前依赖外层管理员
限制，本身会枚举服务器目录和路径。它不能随 `get_view` 放宽而向教师开放。该函数及
项目目录入口应有独立的项目管理权限校验，普通用户的 Frappe 业务目录不应显示这个动作。

`business_blueprints._access` / `_load` 已独立调用管理员聊天权限，并检查私有方案 owner、
站点及 File 权限；第一阶段保留这一边界，不把“看业务视图”变成“能创建数据库结构”。

## 已有可复用的真实业务能力

1. `classroom._scope`、`_roster`、`attendance_scope.allowed_groups` 从当前认证用户的
   Active Employee → Instructor → Student Group Instructor 身份链求范围，并与原生
   Student Group/Student 权限求交集。
2. `teacher_permissions` 的 query/document hooks 约束 Student Group、Student、
   Student Attendance、Student Leave Application；班级分餐另有 `student_meals` hooks。
3. `classroom.save_attendance` 和 `save_meal` 已接入现有校验、版本、锁定、完整名单和
   修改原因规则。前端 attendance_register / meal_register 直接调用这两个服务，
   无须让教师获得 Daily Meal Confirmation 的全校文档权限。
4. `students_view`、`class_students_view`、`meal_counts_view`、`classroom_day` 内部已有
   权限过滤；原生 `frappe_*` 视图核验 DocType、Document、Page、Report、Workspace
   权限。解耦后仍需逐项负例，不应因已有 guard 就假定所有投影视图都可直接开放。

已有教师后端证据：`docs/teacher-scope-lifecycle-acceptance.md` 的 54 项生命周期，角色为
`Instructor + Academics User`，没有管理角色、临时 DocPerm 或权限安装补丁。
服务器证据文件仍存在、权限为 0600、属主 zyd：

`/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925/teacher-scope-lifecycle-9680e04d9f.json`

该 54 项证据验证本班真实保存/新连接回读以及跨班、停用、锁定、未来日期拒绝，但未验证
统一场景 HTML、Cookie、浏览器、教师 Codex 或 SSE。上一批浏览器证据使用合成管理账号，
也不能替代教师验收。

## 第一阶段：最小且可立即实施的解耦

不修改 `meal_scene.require_access` 为一个无差别“所有用户都通过”的判断；该函数还被
现有多个膳食读写入口调用。新增一个统一场景账号门和只读 bootstrap 更容易审计。

| 改动点 | 建议行为 | 不做的事 |
| --- | --- | --- |
| 新 `scene_access` 模块 | `require_scene_account` 复用 require_account，允许启用 System User 打开空壳；只读 bootstrap 返回当前身份可用视图、日期和聊天模式 | 不分配角色，不返回其他用户，不把空壳访问当业务授权 |
| `www/tongjianyun_meal_scene.py` | 用场景账号门渲染；仍 private/no-store、CSRF、Guest 登录跳转 | 不调用管理员执行器 |
| `meal_views.get_view` | 改为场景账号门 + 具体视图 guard；项目目录仍管理级，蓝图沿用独立管理检查；业务 API 每次重新验证范围 | 不用一个全局 `allowed=true` 代替 DocPerm/行权限 |
| 视图注册 | 各视图明确 admission 与数据 guard；拒绝未知视图、参数和任意 URL/方法/SQL | 不给模型任意拼接 HTML 或浏览器脚本 |
| `chat.js` / `views.js` | 左侧初始化不依赖聊天 allowed；右侧管理员可聊天，教师暂显示“业务对话尚未开通，可先在左侧办理” | 不假装右侧已具备教师 Codex |
| `app.js` | bootstrap 完成后决定是否加载食谱；无膳食访问时不反复请求 get_overview，不出现永久读取/403 循环 | 不为周历默认值新增食谱读取权限 |
| 默认视图 | 现有有食谱权限账号仍默认周食谱；无食谱权限时显示其可用业务/班级选择，明确权限原因 | 不将“无权限”显示成“本周没有食谱” |
| 返回/刷新/日期上下文 | 无食谱权限时“回到食谱”替换为该账号的场景首页；通用 context 独立于膳食 get_overview | 不让保存后 refreshMealData 又把老师带回错误周历 |
| 场景内导航 | 对话未开通时给最小的“点名 / 核对用餐 / 可用业务”真实导航，仍在左侧切换；支持正确的班级、日期上下文 | 不先恢复庞大侧边菜单，也不要求老师知道内部 view ID |
| `workspace_entry` | 教师进入同一场景并携带已验证的本班 context；原课堂 URL 保留兼容 | 不绕过班级选择或授课范围 |

bootstrap 只是 UI 提示，不是授权令牌；最终每次 GET/POST 仍由服务端执行当前权限检查。
不要复用跨用户缓存，不能从 query/body 采纳 `actor`、`role`、`ignore_permissions` 或
`runner_mode`。`get_view` 中的 `recipe_week` 目前只返回组件指令，开放后也要明确检查
Recipe 读取权，不能仅依赖下一次周历请求失败。

可先实现和验收教师四类视图及其原写服务，再逐项放开其他经过审计的业务视图；若只开放
这四类，必须明确标记为阶段交付，不能声称全站业务已经对教师完整覆盖。教师没有的原生
业务权限保持没有，不为“所有业务覆盖”强行赋权。

## 第二阶段：真正的业务 Codex 执行通道

### 可信边界

```text
认证网页（同一场景）
  ├─ 左侧业务组件 ── 当前 Cookie + CSRF ── 原 Frappe 服务
  └─ 右侧消息 ── 服务端身份/模式判定 ── task(owner, site, mode)
                    ├─ admin_project ── 现有管理 Codex（不向教师开放）
                    └─ business ── 独立隔离 Codex ── 任务绑定业务工具代理
                                                     └─ 当前原业务权限/校验
```

两个通道都必须是真正 Codex，不改成关键词聊天。模型可以理解需求、选择业务工具、组合
步骤、生成数据草案，并通过同一 SSE 展示阶段进度和请求左侧视图；安全来自执行边界及
服务端授权，不来自它是否“听话”。

### 必须具备的隔离条件（上线前要实测，而非只写配置）

- 独立低权限 Unix 身份、独立 CODEX_HOME、任务临时目录、模型会话、队列及进程组；
  不使用 zyd/站点服务身份，不属于 sudo/docker/站点密钥可读组，不继承管理员 HOME、
  SSH agent、环境、文件描述符或 Codex resume ID。
- 原生系统服务可以做到这一点，不要求改成 Docker。需单独验证文件系统命名空间与
  只读运行时映射、允许写入的临时目录、无提权/无能力集、进程与设备隔离和网络规则；
  不关闭 AppArmor、不开放全机路径。具体配置必须按已安装 Codex/内核运行验证。
- 即使模型触发了 shell，也不能读取生产站点配置、DB/Redis/SSH 凭据、管理员 Codex
  日志/附件、其他任务目录或项目源码，不能连生产 DB、Redis、内网 SSH、宿主其他
  loopback 服务、元数据地址，不能改服务/代码。只允许模型出口代理及任务绑定工具代理。
- 模型凭据由受信代理管理，不嵌入提示词或工具输出。代理拒绝重定向/任意目的地绕过；
  文件读取、外部 URL、DNS/IPv6、symlink/proc 等绕过也要验证。
- 启动器只接收受限 task ID，由服务端读取 owner/site/mode；不接收任意 Unix 用户、
  命令、cwd、mount、环境变量或 CLI 参数。业务 runner 不得 fallback 到 root runner。
- 资源限制、取消、停止后写入禁止、失败不盲目重试均由服务控制；任务执行和浏览器连接
  生命周期分离，不能因为 SSE 断开重复创建任务或业务记录。

### 工具代理，而不是通用 Python/SQL 后门

受信代理在隔离进程外持有最小执行凭据。代理通过不可由模型更改的任务绑定确定
`site/owner/mode`，每次调用检查账号启用、任务有效、取消状态及当前原业务权限；不采纳
模型传来的 actor。单靠可猜的 task UUID 不算代理认证。

首批工具可为：权限过滤的目录/视图读取、读取本班名册和 revision、原点名保存、原本餐
保存、读取本人有权访问的私有附件。每个工具有有限 JSON schema，调原服务并回读；
不给任意 `frappe.call(method)`、SQL、Python、`ignore_permissions` 或远程命令参数。
其他业务逐个增加受测适配器，或在左侧打开原生表单由用户办理，不能将未实现写工具
包装成“已经自动办理”。

业务记录写入需保留原生事务、工作流、审计、revision、确认/修改原因与幂等机制。
结果不确定时先回读，不重复保存。模型输出的“成功”不是提交证据，左侧回读成功才展示
已完成。

教师上传的原文件只经 File 读取权、私有性、类型/大小验证后复制到该任务私有目录；
拒绝他人 File ID 和路径穿越，不把宿主绝对路径交给隔离模型。模型内容只作为数据，
不能将附件中的“切换管理员、导出全部学生”等文字变成授权。

### 会话与 SSE

- 将 `mode` 固化在可信 TaskStore 创建记录；admin/business 的历史、模型 resume 缓存
  key 和队列分开，不能沿用当前只含 site/user 的管理员 resume key。
- 保留 `_owned_task` 的 owner 校验；history/get/stop/events/publish 全部核验模式及
  当前身份。订阅期间停用账号/撤销权限需要停止后续受保护输出与操作，不能只在连接
  开始时检查一次。
- publish 通过同一任务代理触发 `get_view`，结果只返回当前权限允许的摘要，学生姓名
  默认仍不发送给模型；网页再次按当前身份加载真实数据。
- 教师无法借旧的管理员 task ID、历史角色、同用户跨模式 resume、其他站点 task ID
  或取消再恢复等方式获得管理通道。前端在撤权/登出时清除该模式的缓存内容和活动视图。

## 教师提出未知业务时

不让教师直接调用现有 root 方案 CLI 或 `business_blueprints.activate`。业务 Codex 可以
起草有限的数据结构/流程需求并展示“待审核，尚未创建”，但结构启用和项目代码开发是
独立的管理员授权任务。移交必须有明确记录、最小必要内容和接收权限，不共享教师会话
及私有附件；管理员审核后生成其本人所有的蓝图，沿用现有预览/确认/DDL 校验。

启用完成不意味着教师自动有新表权限。管理员按业务定义审批哪些角色可读写、是否需
班级/学生范围和审批规则，应用对应行权限后再向教师发布可用视图。涉及专业财务库存
语义仍使用原生业务/受测开发路径，不把一张扩展表当成完整专业系统。

## 验收清单与完成判据

### 场景与原权限

1. 同一隔离站点使用真实 `Instructor + Academics User` 账号、两个合成班；不新增
   System Manager、Education Manager、Business Operator 或临时 DocPerm。
2. 正常登录进入同一路由；默认视图/导航合理，聊天未开放时说明真实；无空白、永久
   loading、每分钟 403、无权限误报为空食谱，保存刷新不跳出场景。
3. 浏览器左侧本班一人点名、另一人 Unknown；本餐核对和带原因修改；刷新及独立连接
   回读成功；其他餐次/出勤未被误写；修改仍保留真实教师操作者。
4. 直接 URL、view selection、原生 Form/REST、混合批次注入其他班 ID 均失败，且
   拒绝前没有第一条部分写入。Daily 全校汇总原生读写仍被拒绝。
5. 陈旧 revision、未来日期、已锁定/已确认、撤销授课、账号停用、缺 Student Attendance
   read 等按原规则拒绝；网络响应丢失先回读，不重复提交。
6. Teacher-only、无任教班教师、只读业务员、禁用/Website User/Guest、管理员分别
   验证。服务器项目路径、管理员方案、无权限报表/模块/学生数据不可见。

### Codex 隔离及对话（不能由前一组替代）

7. 真 Codex 在隔离实例接到自然语言后调用正确业务工具；SSE 有阶段输出，左侧真实
   切换并完成允许的保存/回读，不使用合成历史导航冒充实时链路。
8. 真任务发出越权尝试，包括任意文件、站点密钥、宿主命令/网络、SQL、跨班/跨站点、
   他人附件、伪造 actor、root mode、tool schema 绕过；在 OS/代理层拒绝，生产及
   其他合成班快照保持不变，不依赖模型主动拒绝。
9. 两个教师同时运行、断线重连/重复 request ID/取消/worker 崩溃/角色撤销；无会话或
   SSE 串流、无重复写入、旧 root resume 不可用，无残留任务继续写入。
10. 未知业务请求形成教师草案→受权管理员独立审查→启用→赋予明确业务范围→教师
    实际使用的新视图闭环；教师不能自授权限、改审批或直接 DDL。

只有第一组通过，可称“教师已能在统一场景办理已覆盖业务”；两组全部通过，并逐项补齐
其他角色/专业业务后，才能逐步扩大“Codex 统一办理”的完成范围。当前设计没有证明
整个 Frappe 的业务覆盖已经完成。

## 第一阶段候选实现与预验（未部署）

本次后续实现新增 `scene_access.get_bootstrap(day, meal, group)`，返回日期/餐次、
`recipe_calendar`、`chat`、`default_view`、简短 `navigation` 和只有数量/选中 ID 的
`scope`。普通启用 System User 可进入空壳；Teacher 入口跳转同一场景并带已验证的 group。
`meal_scene.require_access`、原读写接口及管理员聊天 gate 均未扩大。

明确的临时开放范围：students、class_students、classroom_day、meal_counts，以及经原生
DocPerm/文档权限核验的 frappe_doctype / frappe_document / frappe_new；周食谱另外要求
已有 Recipe 读取权。普通账号 catalog 暂仅列 DocType，并说明 Report/Page/Workspace
仍待范围验收。它们的原生入口授权独立有效，但未逐一审计各报表 SQL、页面 RPC 和工作区
内容，不能将入口检查当作班级数据隔离证明。管理员原有完整入口保持不变。

`projects_view` 已增加独立管理 gate，普通账号目录不提供服务器项目动作。
`publish_for_task` 特别保留现有管理员聊天校验，避免放开网页 get_view 后，历史或已撤权
的 root 任务反而获得新的发布能力。蓝图仍为管理员私有方案，不因空壳/视图开放而放宽。

候选源码独立副本为：

`/home/zyd/frappe/remote-workspace/teacher-scene-unit-vuB307`

通过严格专用 QA 配置守卫连接，343 项完整列表单测通过；已包含新 scene_access 与原
workspace_entry 回归。真实既有教师账号 19 项只读预验覆盖 bootstrap、四类视图及 root 聊天、
项目目录、蓝图、原生日汇总、确切外班学生/班级编号拒绝。没有新增身份、角色、权限或业务记录，也未同步正在使用
的 QA Web overlay。前端、教师 HTTP/浏览器保存及隔离教师 Codex 仍须另行验证。

补齐解耦后的能力提示：普通账号点名视图分页的“可用业务”返回 frappe_catalog，不再
指向其不能访问的 business_catalog；原生收货/Stock Entry 详情只有管理通道账号显示
库存核对动作。这不改变底层拒绝规则，避免页面展示一定失败的下一步入口。

### 后续前端和真实浏览器验收

候选已同步QA Web（不是生产），前端127项回归通过，合并静态版本为v6。
真实原教师账号9月17日完成同场景点名/午餐保存及整页刷新读取，独立READ ONLY回读
24/24通过；角色和20份其他记录不变。详见 `isolated-browser-acceptance-results.md`。
因此前文“浏览器待验证”是预验阶段状态，已由该有限正向流程补齐；教师隔离Codex、
实时SSE、全部角色/专业业务及浏览器负例仍未完成，不能称为全站Codex接管。

### 第一阶段上线

上述有限场景解耦随 `40f3d6c` 部署；生产343项回归、只读探针和三项运行服务核验通过。
本节替代候选阶段的“未部署”状态，不改变教师真实Codex尚未接入的边界。
