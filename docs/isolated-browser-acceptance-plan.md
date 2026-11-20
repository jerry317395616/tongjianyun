# 隔离浏览器验收工具与边界

## v2 新业务浏览器验收准备（本批追加）

新增 `seed-blueprint` 模式使用同一精确隔离 DB/Redis 守卫、既有合成管理者和真实 `propose_for_task`：私有方案属于任务 owner，经 `publish_for_task` 发出真实 business_blueprint 视图事件，再将合成导航任务置 completed。没有调用智能体、预激活结构或后台代填业务记录。

- 独立私有清单 `browser-blueprint-fixture.json` 将本轮边界绑定为方案 `888d4f4ca2`，任务 `f5e5899a-e1ef-40a0-b04d-16de118e7282`，主类型 `Tongjianyun Advanced browser_estimate_ab6539df86`，唯一子类型 `TGY Extension Row 00b8ba86082a1c798f73099e`。口令及既有课堂 fixture 的文件摘要保持不变；重复 seed 验证并复用方案，不自动重新创建。此处状态是准备时的 proposed，不替代后续实时核验。
- 测试方案为活动估算：明细项目、数量、单价、小计，服务端数量×单价后汇总主表金额，固定 review 复核流程。它不是采购、付款或库存的替代业务。
- 防火墙新增精确方案 activate POST 和本轮主/子类型的元数据读取；新建/修改只允许 `frappe.desk.form.save.savedocs` + `action=Save` + 该主类型的草稿，以及该子类型的正确 parent/parenttype/parentfield。拒绝任意 flags、外来子类型、跨表父对象、不同 owner、直接 Submit/Cancel/Update 和 workflow 跳转。
- 原生必要 RPC 依据已安装源码定位：`frappe/public/js/frappe/model/model.js` 的 getdoctype/getdoc，`form/sidebar/form_sidebar.js` 的 get_docinfo，`form/save.py` 的 savedocs，`model/workflow.js` 的 get_transitions，`model/user_settings.js` 的 get/save。只读及个人显示设置也须精确本轮类型，工作流查询不允许注入 workflow 参数；尚未允许工作流动作、其他原生写入、通用 resource 路由或 Codex 执行。
- 校验 `/api/method`、`/api/v1/method`、`/api/v2/method` 以及 query/form/JSON cmd；冲突命令、冲突参数、重复 JSON/form/query 键（包括嵌套 doc）均拒绝。蓝图预览同样只接受清单中的 proposal。认证 cookie、CSRF header/body 均原样交给 Frappe；没有登录捷径、CSRF 豁免或业务权限猴子补丁。
- 23 项独立无密钥测试通过：原有 9 项边界 + 5 项资产契约 + 9 项蓝图边界。原生 CSRF 测试在这里证明“中间件不注入凭据、不吞掉原生拒绝”，不是已完成真实 HTTP CSRF 验收；真实浏览器激活、保存、刷新和独立后端回读仍须另附结果。

根任务同步 v5 后，已刷新并核验 1,295 个独立公共文件与 HTTP 摘要一致。旧 PID `2619194` 已确认不存在后启动 PID `3068750`；根任务随后同步最新后端，精确核对该 PID 命令及监听，停止并确认旧 exec session `60776` 终止，再以 exec session `59349` / PID `3102260` 重启。监听仅 `127.0.0.1:23380`，无 worker/scheduler/debugger/reloader，重启后 verify 的 HTTP/资产核验仍通过。以上进程信息为准备时证据，后续须重新确认。

另新增 `verify_browser_blueprint_readback.py`，待浏览器完成真实启用和保存后，以同一管理者的新连接开启 `START TRANSACTION READ ONLY`，检查精确主/子 schema 与 workflow、原权限、actor、草稿状态及两行金额计算。它不会激活方案、代填记录或调用保存；生成的结果证据与浏览器操作证据配套，不能替代浏览器本身。预期输入：名称“浏览器合成活动估算”，数量/单价为 `2.5 × 3.8` 与 `10 × 1.25`，应持久化小计 `9.50 / 12.50`、总额 `22.00`。

原生表单首次打开未成功：并非发现生产角色缺陷，而是隔离站点一直未完成 Desk 安装导引标记。只读 `inspect-desk` 证实 `frappe/erpnext/education/tongjianyun` 的 Installed Application.is_setup_complete 均为 0；已有合成公司 `QA Meal 0afbba8af3` 及 CNY/China、COA、仓库。原生 `frappe.is_setup_complete()` 只检查 Frappe/ERPNext 两项，`router.js` 在 false 时强制跳 setup-wizard。不得通过放宽业务角色解决。

经根任务确认，增加严格 QA `prepare-desk`：验证既有合成公司/科目/仓库后，仅用原生 `enable_setup_wizard_complete` 将 Frappe/ERPNext 两项设 1，并将 System Settings.setup_complete 设 1；其他两应用标记及 locale/settings 未动，不运行 setup_complete/disable_future_access、邮件、用户/角色变更或完整导引。旧值/新值保存于 QA `browser-desk-readiness.json`；重复调用只读核对该记录与现状，发现偏离即停止、不覆盖。总 prepare 也调用该幂等步骤。

同时仅增加原生 Desk 启动的两个只读 RPC：get_boot_translations 限 GET/HEAD 与 lang/v，get_session_default_values 限空参数；所有 setup_wizard 和 set_session_default_values 仍拒绝。新增诊断仅记录预定义 RPC 名、HTTP 动词、预定义参数键、响应状态及 native/QA 拦截层，不记录参数值、cookie、CSRF 或口令；请求上下文局部保存，避免并发串线。未知命令/键统一替换为 unlisted。新增 3 项启动边界/日志隐私/延后响应独立性测试，全套 26 项通过。当前 QA 在精确终止旧 PID 后重启为 PID `3191733` / exec session `97093`；未刷新教师前端资产。

### 已完成的真实蓝图浏览器办理与新连接回读

根任务使用 CUA 操作既有合成管理者：实际打开左侧方案，先取消一次，再确认启用；页面以新 GET 回读展示 active 及“开始录入 / 查看记录”。随后进入同场景的原生新建表单，以键盘输入名称“浏览器合成活动估算”和两行材料 `2.5 × 3.8`、`10 × 1.25`，点击原生 Save。服务器脱敏日志确认 `frappe.desk.form.save.savedocs` POST 到原生应用并返回 `200 OK`，不是后台代填或 fake 响应。

记录为 `pespg1lt48`，两行小计 `9.50 / 12.50`、总额 `22.00`，状态“扩展·草稿”。根任务随后通过原生 Menu → Reload 再见同一记录、同样明细与合计；服务日志亦记录 getdoc/get_transitions 原生 `200 OK`。没有点击送审或复核，因此此处不声称工作流审批已通过浏览器验收。

独立脚本新连接执行 `START TRANSACTION READ ONLY` 后回读 19 / 19 通过，最终证据 `browser-blueprint-readback-4e38ef3652.json`（QA root，0600）核对：方案仍属于管理者、完整主/子 schema 与 fixed workflow active、原 System Manager 权限及禁止删除/分享、创建者/修改者均为浏览器管理者、恰好一条记录、真实子表父级绑定、服务端计算值及 manifest 不变。只读脚本没有激活、保存、提交或更改记录。先前报告 `browser-blueprint-readback-5df09fc541.json` 保留，最终报告另加币种限制说明。

证据范围：QA 全局币种未配置，原生表单显示了默认 `₹` 符号；这里只证明数值计算及两位金额字段，**不能证明币种配置正确**。本方案是活动估算，不是财务记账。Frappe 原生 grid 为草稿附带的 `__unedited / __checked` 仅按布尔值放行，任意 flags 仍拒绝。保存后一次 get_transitions 读请求曾因 QA 使用写入级别校验误拦；已依据原生函数会按固定 type/name 重新 load_from_db，将只读身份检查与 Save 草稿检查分开，仍禁止 flags、外来类型、外来 workflow 注入和任何审批动作。

在上述管理员浏览器验收之后，根任务统一同步教师候选。QA 新增 GET `tongjianyun.scene_access.get_bootstrap`，将 `scene_bootstrap.js` 加入关键资产；刷新后 1,296 个文件及 6 个关键 HTTP 资产均与候选一致，app 版本 `teacher-scene-20260925-1`、chat/views 为 v5。旧课堂、蓝图、readiness、口令文件摘要保持不变。该阶段 helper 单测 29 项通过（含 UI 标记、只读工作流/严格保存分离及 bootstrap 负例），运行 PID `3275771` / exec session `30084`。教师自己的 9 月 17 日办理证据由独立教师验收文档记录，不混入这份管理者验收。

真实切换账号时另修复两项 **QA 屏障兼容性**：bootstrap 的前端原生参数实际为 day/meal/可选 group，故仅允许这三个参数及合法格式，不能传 user/role 等覆盖权限；后端仍自行验证本人的班级范围。Frappe desk.js 的正常 Logout 调用为无参 `logout` POST，浏览器可以省略 Content-Type/body，原 QA 解析器因此误拒。现只对该无参命令允许零长度无 Content-Type POST，拒绝 user/sid/session 等目标参数，其他空体写接口仍拒绝；`frappe.handler.logout()` 由 Frappe 正常注销当前会话，没有后台代注销或绕过 CSRF。补充测试后全套 30 项通过，精确重启至 PID `3309690` / exec session `53771`，verify 证实 HTTP 和 6 项关键资产一致。

原生页另一附带拒绝的未知 POST，通过只记录 SHA256 并离线匹配公共前端源码，确定为 `frappe.core.doctype.background_task.background_task.get_recent_tasks`（固定 limit=15）。它不是 Save 或 Logout 失败。当前 QA 未开放后台任务查询/重试/取消，此弹窗是隔离屏障边界，不代表已证实的生产业务权限缺陷；不会为消除提示去运行后台任务。

教师首次进入时还遇到浏览器缓存旧 `chat.js?v5`：服务器文件/HTTP 摘要已新，但浏览器先成功读取新 bootstrap 后仍调用旧管理聊天 get_chat_access，原生拒绝教师属于正确权限结果，并非要给教师管理员角色。根任务将模板 chat/viewsCSS 以及 chat→views import 统一升到 `unified-business-20260925-6`。随后只刷新 QA 公共资产并精确重启到 PID `3335176` / exec session `78349`，verify 确认 v6 URL 与 1,296 文件、6 项关键 HTTP 资产一致；账号、口令、配置及业务 fixture 摘要保持不变。需要真实浏览器 reload 新 URL 才能证明缓存问题已解决，不能仅以源/HTTP 一致代替浏览器实际加载证据。

```sh
/home/zyd/frappe/native-bench/env/bin/python /home/zyd/frappe/remote-workspace/serve_isolated_browser.py seed-blueprint
```

日期：2026-09-25。最初为只读建议，后经明确授权实现 `deploy/unified_business/serve_isolated_browser.py`，并已准备合成浏览器 fixture、独立静态资源和 loopback Web。没有启动对外代理、执行生产写入或由本子任务操作浏览器；本机 SSH 转发和 CUA 验收由根任务负责。

## 已实施工具

- `prepare`：重复精确 root/site/DB/Redis 守卫，将四个应用的 1,295 个公共文件复制到 QA 真实 `sites/assets`；不跟随 public/node_modules symlink，不改生产 assets。设置仅 QA `maintenance_mode=0` 与独立 host_name，仍禁用 scheduler、开发模式、邮件发送。
- 合成管理用户 `browser-manager-02e16a31d7@example.invalid` 具有明确 System Manager + Academics User；教师 `teacher-scope-9680e04d9f@example.invalid` 保持原角色。两套强随机临时口令只存 QA root 下 `browser-credentials.json`，0600、不输出。重复 prepare 不重置口令或业务事实。
- 复用授课班 `QA Teacher 9680e04d9f Assigned` 的两名合成学生，浏览器业务日期 `2026-09-18`、午餐，初始考勤 Unknown，未创建实际考勤或就餐确认。
- QA Redis 的“隔离测试导航，未调用Codex”任务通过实际 `publish_for_task` 校验并发出 classroom_day / meal_counts 视图指令后标记 completed，没有 RQ job、worker 或 Codex 进程。打开右侧“查看”按钮将真实查询 QA 后端，不用浏览器隐藏函数。
- `serve`：使用 Werkzeug `make_server` 而非会设置 debug 标记的 Frappe 开发启动器；固定 site/sites_path，绑定 `127.0.0.1:23380`，单线程、无 debugger/reloader/worker。运行时再次逐请求校验隔离配置，拒绝其他 Host 和 site header。
- WSGI 测试防火墙对 RPC 默认拒绝，仅允许登录/登出、课堂考勤/分餐保存和必要只读接口。真实 Codex send/cancel/private runner、文件上传、非白名单方法、generic resource/native 写入均被拒绝；校验路径及 form/JSON/query cmd，不能借别名绕过。没有猴子补丁业务权限。
- `refresh-assets`：只刷新独立 QA 公共文件，不连接 Frappe/DB/Redis，不创建导航、轮换口令或改配置；内部比较 credential/fixture/config 字节摘要保持不变，摘要不输出。
- `prepare` / `refresh-assets` 将每个公开源文件与副本的 SHA256 写入私有测试清单；记录模板资源版本和 chat→views import，必须含考勤、分餐、蓝图、库存核对组件。`serve` / `verify` 检测源文件、模板或副本变更后拒绝声称版本一致。
- `verify`：仅输出非敏感 readiness、公开资源 SHA256 和合成 fixture；另将 HTTP 实际返回的五个关键文件与源/副本摘要逐一比较。已确认 health=ready、login=200、agent send POST/GET-body cmd=403、端口监听仅 loopback。
- 防火墙 9 / 9、资产证据与只刷新契约 5 / 5 无密钥单测通过。版本化工具已复制到 QA remote-workspace 用于运行；没有提交或生产部署。

启动记录：精确核对脚本后停止旧 PID `2545326`，当前服务器 PID `2619194`、exec session `63201`。根任务可使用该 session 结束本次进程；若状态变化，以 `verify`、`browser-server.json` 和精确 PID/监听检查为准。

首次管理者浏览器验收发现候选 overlay/QA 副本仍是旧 views.js，缺少 attendance 组件；这是测试资产同步问题，不是已证明的生产缺陷。根任务同步完整候选前端后，已执行只刷新资产、验证 1,295 个文件源/副本一致并重启精确 QA 进程。chat 和 views import 为 `unified-business-20260925-4`，模板 views.css 为 `unified-business-20260925-2`；凭据、fixture 和导航未变。公开资源摘要以 `browser-assets.json` / `verify` 输出为准，不把旧文档摘要当实时版本证据。

```sh
/home/zyd/frappe/native-bench/env/bin/python /home/zyd/frappe/remote-workspace/serve_isolated_browser.py prepare
/home/zyd/frappe/native-bench/env/bin/python /home/zyd/frappe/remote-workspace/serve_isolated_browser.py refresh-assets
/home/zyd/frappe/native-bench/env/bin/python /home/zyd/frappe/remote-workspace/serve_isolated_browser.py serve
/home/zyd/frappe/native-bench/env/bin/python /home/zyd/frappe/remote-workspace/serve_isolated_browser.py verify
```

管理场景 URL：`http://unified-business-acceptance.localhost:23380/tongjianyun-meal-scene?day=2026-09-18&meal=lunch`。口令文件只交根任务的授权浏览器流程读取，不贴聊天或录屏。

## 管理者浏览器保存后的独立回读

根任务通过真实 QA 页面完成：第一名合成学生到园、第二名保持待点名；午餐先保存为“就餐 / 不就餐”，再填写“隔离浏览器验收：核对后补录本餐实际就餐”改为两人就餐。根任务另行刷新浏览器核对显示。这里只证明合成管理者办理，不替代纯教师权限验收。

`verify_browser_fixture_readback.py` 随后新建独立连接，以合成管理者执行 `START TRANSACTION READ ONLY`，只核对固定班级/2026-09-18 记录并最终 rollback。18 / 18 检查通过，证据保存在 QA root 的 `browser-readback-ad5c578350.json`（0600）：

- 考勤为 Present / Unknown，原生到园记录只有第一人，记录 actor 为合成管理者。
- 午餐实际人数 2，两名均已就餐；其他四餐仍未确认、actual 为 null；班级日记录和每日汇总仍待确认，没有整日确认人/时间。
- 午餐预计仍为两人；全部 expected 字段与原预计规则一致，持久化 Version 没有 expected 字段变更。没有独立保存前数据库快照，故证据明确限定为“浏览器保存前看到两人预计就餐 + 当前原规则一致 + 历史无预计字段改动”，不冒称完整数据库前后快照。
- Version 保留第二人午餐“未就餐→已就餐”、精确修订原因与管理者 actor；两条原生午餐核对 Comment 保留且 actor 一致。

未保存离开保护的原生 `window.confirm` 使 CUA 标签 13 停住，工具不能关闭/响应；根任务改用标签 14 完成其余检查。**离开保护的真实浏览器结果仍为未验证，不能记为通过。** 此次回读未执行新的业务写入，没有运行 Codex、重启服务或触及生产数据。

## 初始只读调查

- 固定站点：`/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925/sites/unified-business-acceptance.localhost`。
- 隔离 `sites/assets` 尚不存在；站点 `public` 是独立真实目录，sites 下没有发现 symlink。
- 生产 `native-bench/sites/assets -> ../assets`，其中 frappe、erpnext、education、tongjianyun 各自链接到生产 app/public。**不能在这些链接下复制、覆盖、构建或清理文件。**
- Frappe、ERPNext app/public/dist 已有构建好的 JS/CSS。生产 assets 根部有 `assets.json` 和 `assets-rtl.json`（仅公共构建清单，不含站点凭据）。
- 当前隔离进程仅监听 loopback 23316（DB）与 23379（Redis）；23380 未监听。
- 本机安装的 `frappe.app.serve` 支持显式 `site`、`sites_path`、`bind_addr`、`port`、`no_reload`、`no_threading`；静态中间件只从给定 `sites_path/assets` 提供文件。
- `init_request` 先用固定 `_site`，再考虑 Host / `X-Frappe-Site-Name`；固定 site 可防请求头把测试请求指向其他站点。

## 建议的最小接入方式

1. 创建隔离 root 内的真实 `sites/assets` 目录，拒绝现成 symlink。将只需的公共资源复制到该目录：候选 Tongjianyun 的 `tongjianyun/public`，以及 Frappe/ERPNext/Education 的公共静态资源和必要构建 manifest。目标全部 `resolve()` 后必须仍在隔离 root 内。不要复制任何生产 `sites/<site>`、private 文件、配置、上传附件或 session；不要执行 production bench build。复制是单向只读来源、独立可写目的地，不能用链接“借用”生产 assets。
2. 用新建的专用启动器重复生命周期脚本的全部隔离守卫，并验证 `frappe`/Tongjianyun 加载路径；清除继承的 DB/Redis 环境覆盖，设隔离 `FRAPPE_BENCH_ROOT`，候选源码在 sys.path 首位。以固定 `site='unified-business-acceptance.localhost'`、精确 sites_path、`bind_addr='127.0.0.1'`、`port=23380`、`no_reload=True`、`no_threading=True` 启动 `frappe.app.serve`。不要使用 `bench start`，不启用 worker/scheduler/debugger/proxy，也不改生产 supervisor/nginx。
3. 如需局部 host_name 配置，仅在已验证的隔离站点设置测试 loopback URL；不写生产配置、不放宽 CSRF/CORS。应用启动前应再次确认有效 DB/Redis 与标记；启动后验证监听地址恰好 `127.0.0.1:23380`。
4. Windows 侧仅开本地转发：`ssh -N -L 127.0.0.1:23380:127.0.0.1:23380 -o ExitOnForwardFailure=yes frappe-harness`。后台进程须隐藏窗口并记录精确 PID，仅关闭本次 PID。不能用 ngrok、0.0.0.0、公网代理或修改防火墙；转发失败不改用公开监听。
5. 浏览器使用独立临时会话，以 `http://unified-business-acceptance.localhost:23380` 访问（localhost 子域解析到 loopback，先做只读解析检查）。不要复用 `child.myyr.top` 标签、cookies、localStorage、production sid/API key。若浏览器不支持该 localhost 子域，先确定一个独立本地测试域方案，不通过 hosts 把生产域导向测试服务。
6. 给本次合成教师设置一次性强口令，只存隔离 root 的 0600 私有文件，由获授权的浏览器控制流程使用；不回显口令、sid 或 CSRF token。不要重置 Administrator 或真实用户密码，不复制生产 cookie。完成后可禁用这名单独合成浏览器账号并使其测试会话失效，保留业务证据。

## 角色和页面必须分别验证

纯教师当前不能进入 `tongjianyun-meal-scene`：`meal_scene.require_access()` 要求原膳食/采购/库存权限，`meal_views.get_view()` 又要求高权限 Codex 聊天访问。不能给教师 System Manager 来把统一场景测试伪装成教师测试。

- **真实教师业务写入证据**：使用 `/tongjianyun-classroom?workspace=teacher` 的已有教师页面，选本次隔离合成班和新的、未锁定过去日期，办理一名学生点名，刷新后核对；再办理本餐就餐并回读。保持另一班不可选，另开会话精确跨班 URL/API 被拒绝。后台用同一账号/权限化服务核对记录和修改时间。该页面仍是原教师课堂 UI，不能说成新统一场景组件已验收。
- **统一场景组件证据**：使用独立的隔离管理业务账号测试管理场景，明确这是管理员，而非教师。只触发合成视图/办理合成记录；不要向真实 Codex runner 发送聊天任务。默认 Codex executable/project 仍指服务器真实项目，隔离 DB 不等于隔离宿主机智能体权限；未另行隔离 runner 时，应禁用/不操作聊天发送、上传、任务执行。
- 若要求教师也使用新统一场景，需单独实现“业务视图读取权限与高权限 Codex 运行权限分离”的受限入口，不能在验收启动器里猴子补丁绕过 `require_chat_access`。

## 建议采集证据

1. 页面上可见的合成账号、班级、日期与空白 Unknown 状态。
2. 用户点击选择和保存动作；POST 真实响应；保存后 GET 的 revision 和结果；浏览器刷新仍一致。
3. 未保存离开保护、陈旧 revision 拒绝、未来/确认/锁定拒绝、跨班和 disabled 拒绝。
4. 页面截图/操作录像仅含合成人名，不能录入一次性口令或控制台私密请求头。
5. 独立后端回读报告及固定站点/数据库标记，且旧历史 fixture 摘要保持不变。

现有 54 项 ORM/原生 resource handler 验收、127 项业务单元回归及初版 14 项 Web/资产边界单测不替代上述浏览器到真实后端证据。初版防火墙不允许蓝图激活、库存修复或通用原生单据写入；本批仅按文首的精确方案扩大到蓝图启用及该类型的草稿保存，没有关闭整个屏障，库存修复和其他单据写入仍不开放。未增加一次性链接或 LoginManager 登录旁路；使用正常登录页与隔离强随机口令。
