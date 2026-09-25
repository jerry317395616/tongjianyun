# 隔离浏览器验收建议（未启动）

日期：2026-09-25。本文件是只读环境调查和操作建议；本轮没有新建静态资源目录、改站点配置、设置密码、启动 Web、启动 SSH 转发或使用浏览器。

## 已核实状态

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

先取得后续启动/浏览器步骤授权并确认所测页面范围，再实施本方案。现有 54 项 ORM/原生 resource handler 验收和 127 项单元回归不替代上述浏览器到真实后端证据。
