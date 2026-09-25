# 隔离浏览器验收工具与边界

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

现有 54 项 ORM/原生 resource handler 验收、127 项业务单元回归及 14 项 Web/资产边界单测不替代上述浏览器到真实后端证据。当前防火墙尚不允许蓝图激活、库存修复或通用原生单据写入；如需扩大 QA 验收范围，应在版本化白名单中明确增加所需接口并补测试，不关闭整个屏障。未增加一次性链接或 LoginManager 登录旁路；使用正常登录页与隔离强随机口令。
