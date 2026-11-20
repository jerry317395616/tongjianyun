# `/home/zyd/frappe` 项目与业务覆盖盘点

盘点日期：2026-09-25。范围：服务器 `172.18.112.42` 上的 `/home/zyd/frappe`。

## 结论与口径

**31 个目录索引项不等于 31 个已接入业务系统。** 当前 `project_catalog` 的统计方式是 24 个顶层目录，加上 `native-bench/apps` 下 7 个应用源码目录。顶层项中混有运行状态、日志、备份、知识库、旧源码副本和验收工作区。

当前可以复用的业务基础是 `child.myyr.top` 已安装的 7 个 Frappe 应用；其他独立服务必须分别解决身份、API、业务规则和验收，不能因 Codex 能访问服务器文件就宣称全部业务已经贯通。

本轮仅执行目录元数据、README/公开源码接口声明、容器名称/镜像/状态/Compose 归属、systemd 名称/状态/工作目录的只读检查。未读取 `.env`、站点密钥、浏览器凭据、业务库内容、员工/学生记录或备份内容；未调用外部业务 API；未修复、重启或新增集成。

证据等级：

- **目录已发现**：只能证明路径存在。
- **用途已识别**：README、源码或部署元数据能说明用途。
- **进程已观察**：systemd/container 状态快照；不等于 API 健康或业务成功。
- **入口已验收**：权限范围内业务入口可解析、原生界面可打开；不等于每一种写操作完成。
- **业务已验收**：必须另有特定账号、数据范围、读写流程、回读结果及错误场景证据。本文件不把前三项升级成这一项。

## 统一接入原则

下表中的 **Frappe 原生接口** 指当前站点身份下的原生列表、表单、报表、工作区，以及按需使用 `/api/resource/{DocType}` 或已白名单化的应用业务方法。审批、提交、取消和修订必须走原应用工作流，不能直接 SQL 改状态。跨应用应复用业务服务，不新建绕过校验的万能写入接口。

所有独立系统接入至少需要：明确唯一在用实例与版本、独立系统身份映射、最小权限凭据、经过核验的读写 API、幂等/并发/审计/回读规则、一个隔离环境的完整业务验收。站点的登录身份、管理员权限、Codex 的系统权限不能互相冒充。

## A. 当前站点的 7 个已安装 Frappe 应用

已安装列表来自上一轮站点只读覆盖验收：`frappe, erpnext, tongjianyun, ione_core, ione_agent, education, hrms`。该轮验证了 957 个可见入口和 585 个当时账号允许的新建表单路由，**是入口数量，不是业务记录数或写流程覆盖率**。本轮未重新查询生产数据库。证据：`docs/unified-business-goal.md`、`deploy/unified_business/check_coverage.py`。

以下路径均以 `/home/zyd/frappe/native-bench/apps/` 为前缀。

| 编号 / 项目 | 真实用途与证据 | 读取入口 | 写入与认证条件 | 当前覆盖边界 |
|---|---|---|---|---|
| 1. `frappe` | 低代码框架、身份、DocType、表单、报表；`frappe/README.md` | 当前用户权限过滤后的 DocType/Report/Page/Workspace；Frappe 原生接口 | 同站点用户会话/经授权的 API 身份；创建、保存、工作流等仍执行框架验证 | 已安装、目录/入口可用；系统设置与所有通用写流程未逐项验收 |
| 2. `erpnext` | 财务、采购、库存、销售、制造、项目等；`erpnext/README.md` | 原生业务列表、单据、报表 | 原生单据 API/表单；角色、公司、会计期间、单据状态、审批条件必须保留 | 已安装、入口覆盖；不能据此宣称采购到付款等跨单据链路已验收 |
| 3. `education` | 学生、班级、入学、课程、考勤、费用；`education/README.md`、`education/education/hooks.py` | 原生学生/班级等视图及应用报表 | Frappe 身份加教师/班级行级权限；考勤与餐数联动走既有业务方法 | 已安装；已有膳食相关专门视图，其他教育流程需分场景验收 |
| 4. `hrms` | 员工、入离职、请假、出勤、报销、工资；`hrms/README.md` | 原生人事/薪酬视图，按当前权限 | HRMS 原生表单与审批；员工身份、部门、薪酬敏感数据权限单独核验 | 已安装、入口覆盖；未读取人员记录，未声称薪酬业务已贯通 |
| 5. `ione_core` | I-ONE 身份、业务关联、AI 作业、审批、审计与跨应用视图；`ione_core/README.md`、`ione_core/ione_core/mcp/` | 原生单据/页面、受控 MCP 业务工具（具体工具另行核验） | Frappe 身份与 I-ONE 执行策略；工具必须保留申请人、权限和审计 | 已安装；目录入口可用，不代表每个 MCP 工具写链路已验收 |
| 6. `ione_agent` | 企业会话、线索任务、证据、受控桌面执行；独立 Codex/LibreChat 伴随服务，Dify 为单独平台；`ione_agent/README.md` | 原生会话/任务单据、`/agent` 与 `/dify` 入口 | 站点角色及独立服务身份；Dify 管理入口需 System Manager/I-ONE Agent Manager 等授权和 Frappe OAuth 对接 | 已安装不等于伴随服务可用；本轮观察到相关 Codex 服务 auto-restart、LibreChat 服务 failed，未诊断/修复 |
| 7. `tongjianyun` | 幼儿园食谱、营养、食材、用餐、班级、视频考勤及会话工作台；`tongjianyun/README.md`、`tongjianyun/tongjianyun/hooks.py`、`tongjianyun/tongjianyun/meal_scene.py`、`tongjianyun/tongjianyun/business_views.py` | 周食谱/食材/营养/学生汇总等注册视图，及全 Frappe 原生目录 | 食谱使用既有编排/导入/保存服务；同周更新原记录并留历史，不能用通用新建/删除制造副本；全程保留业务身份 | 已有专项功能和入口验收；本轮出勤与未知业务蓝图验收由主任务另行记录，不在本文件提前判成功 |

原生目录权限证据：`tongjianyun/frappe_project_views.py` 中 `module_apps`、`catalog_entries`、`operation_capabilities`、`native_view`；目录会根据已安装应用、模块、用户权限和单据状态筛选。配置为禁用或当前用户不可见的入口不应出现在结果中。

## B. 24 个顶层目录逐项映射

第一列目录均以 `/home/zyd/frappe/` 为前缀；该行的证据文件路径相对于对应项目目录。标注“无业务 API”的目录不是需要再造一个业务接口，而是应保留为运维/资料对象，不混入业务菜单。

| 编号 / 目录 | 用途 / 证据路径或元数据 | 读取与写入所需接口、身份 | 验收状态与最小下一步 |
|---|---|---|---|
| 8. `.codex-deepseek` | 本项目专用原生 Codex+DeepSeek 安装/启动与状态；`NATIVE-USAGE.md`、`bin/codex-deepseek` 文档引用 | 不是业务系统 API；由受控执行代理调用 CLI/App Server，再使用目标系统业务 API。模型凭据与系统执行权限需与业务用户权限分离 | 安装用途已识别；本轮未读取配置或执行模型。不得把高权限启动器直接变成普通网页用户的任意命令入口 |
| 9. `backups` | 备份目录；仅目录元数据 | 无业务 API；若需恢复须专门备份/恢复工具、准确目标和授权 | 仅索引，未读取备份、未做恢复；不应显示为可办理业务 |
| 10. `chatbridge` | ChatGPT-Web2API，浏览器会话桥接的 OpenAI 兼容 API/MCP；`README.md`、`docs/api-reference.md`；`chatbridge.service` 工作目录匹配 | 文档列 `GET /v1/models`、`POST /v1/chat/completions` 与 MCP 读写工具；需要有效浏览器登录及网关访问控制，不能复用站点管理员身份假定已授权 | API 服务 active，登录门户伴随服务 auto-restart；未验证登录、接口或业务调用。先确认访问控制与授权账号，再仅做公开测试内容的最小连通验收 |
| 11. `config` | 共用配置目录；仅目录元数据 | 无业务 API；配置变更属于专门运维动作，不向业务视图展示配置内容 | 仅索引，未读取配置；先建立配置所有者/服务映射，不扫描密钥 |
| 12. `deepseek-harness` | 插件化智能体运行时，Web UI、会话、工作区、工具；`README.zh.md`、`packages/api/README.md`、`docs/user/guide/index.zh.md`；`ione-harness.service` 工作目录匹配 | SDK/API Gateway 的 `/api` RPC 通道（具体方法按版本核验），Frappe SSO 网关；读会话/作业与发起执行分别授权 | 主运行时及 SSO 网关 active；不能把进程状态当作当前用户业务操作验收。先核验主体传递、工作区边界与一个只读业务任务 |
| 13. `deepseek-harness-pre-fork-sync-20260901` | 同名 Harness 历史同步源码副本；`README.zh.md`、`package.json` | 不作为新业务实例接入；若确需使用须先确定版本和独立身份/数据状态 | 用途按命名与源码识别；未见本轮服务工作目录指向此副本，不能重复计为已运行系统 |
| 14. `deepseek-harness-state` | Harness 状态存储目录；仅目录元数据 | 无独立业务 API；只能经所属 Harness 的会话/状态接口读取，不能直接跨用户读取状态文件 | 仅索引，未读取内容；需确认在用实例及归属后才可做受控状态维护 |
| 15. `dify` | 独立 AI 应用/工作流平台；`README.md`、`docker/docker-compose*.yaml` 路径元数据、`api/controllers/service_api/app/workflow.py`、`completion.py`、`wraps.py` | 应用 Service API 的 `/v1/workflows/run`、`/v1/chat-messages` 等；应用 token 与管理控制台 OAuth 身份分开。管理入口通过 I-ONE 的 `/dify` Frappe OAuth 跳转 | API/web/worker 等容器运行；已存在登录入口设计，但本轮未验证 OAuth 或工作流。最小接入是一份无副作用工作流、独立应用凭据和申请人映射 |
| 16. `doc` | 本地业务资料目录；仅文件类型/目录元数据，未打开内容 | 无业务 API；资料只能按用户选择的文件，经原文件权限和受控上传/解析流程使用 | 仅索引，包含业务资料，不应批量公开或自动导入；具体文件需单独授权 |
| 17. `frappe-docs-kb` | Frappe 文档知识库，存在 `frappe-docs.sqlite3`；`ione-frappe-docs-sync.service` 描述为知识库同步 | 经文档检索/同步组件提供只读查询；写入为知识索引构建，不是业务单据 API | 文件存在、同步单元当前 inactive；未读取数据库，不把知识库当作实时业务事实 |
| 18. `harness-update-20260916` | Harness 更新候选/工作副本；`README.zh.md`、`package.json` | 不单独接入；候选版本应先验收再由在用运行时升级流程承接 | 源码用途已识别；主服务工作目录不是此目录，未证明独立运行 |
| 19. `logs` | 日志目录；仅目录元数据 | 无业务 API；如需故障分析先限定服务/时间并脱敏，写日志由原服务管理 | 未读取日志；不能当成可对所有业务用户开放的数据源 |
| 20. `native-bench` | Frappe 承载运行时和站点集合；`apps/`、原生 web/worker/scheduler/socketio/redis 等 systemd 名称 | 业务按站点 API/会话接入；不是一个跨所有站点共用的全权身份 | 原生服务快照 active；该目录已由上方7应用展开，不能再将目录自身计作第8套业务系统 |
| 21. `new-api` | 大模型网关、模型/账号/用量/订阅管理；`README.zh_CN.md`、`router/api-router.go`、`router/relay-router.go`、`compose.deploy.yaml` 路径 | 模型读写走 `/v1/models`、`/v1/chat/completions`、`/v1/responses` 与 TokenAuth；管理走 `/api/...` 的 UserAuth/AdminAuth 与独立会话。管理凭据不可当作模型调用 token | `frappe-new-api` 容器 healthy；未验收当前站点用户映射、订阅变更或付费调用。先只读模型/自身用量，再单独授权高风险管理写入 |
| 22. `openai-codex` | Codex CLI/App Server 源码；`README.md`、`package.json` | 开发与执行工具，不是业务数据库 API；业务读写仍调用目标项目接口 | 仅源码存在；不能从源码目录推定该副本就是网页正在调用的可执行版本 |
| 23. `qwen-web-mcp-bridge` | 当前主线合并 Execution Bridge 与 Protocol Gateway；`README.md`、`docs/ARCHITECTURE.md`、`docs/QWEN_PROTOCOL_PRODUCTION_0.7.1.md` | 执行桥 `/mcp` 使用独立 Bearer/设备授权；模型协议侧另用独立 client key，不共用管理员操作令牌；必须区分模型推理和宿主执行 | 当前执行桥服务 auto-restart，协议网关服务 failed；文档也保留真实模型工具闭环未全量通过的边界。本轮未诊断，不应作为可用业务入口推荐 |
| 24. `qwen-web-mcp-bridge-remote` | 远程执行桥旧/独立源码；`README.md`、`docs/DEPLOYMENT_0.5.1.md` | 设备授权、短期令牌、项目控制权与 MCP 执行接口；不能沿用主线共享凭据 | 本轮 remote 服务工作目录实际在用户 `.local/share/.../releases/`，不是此目录，且 auto-restart；需先核对在用构建与授权链 |
| 25. `qwen-web-mcp-protocol` | 模型协议原型/独立分支；`README.md`、`docs/QWEN_PROTOCOL_LAB.md` | 模型协议接口，不提供业务命令执行 API；不能把 protocol fixture 当真实模型通过 | 属独立源码副本；活动协议网关另在 `.local/share/.../current`，本轮服务 failed；不重复算作已集成业务 |
| 26. `recovery-20260907-attendance` | 出勤恢复/回滚材料；目录名及脚本/归档文件类型元数据 | 无在线业务 API；恢复须限定原站点与迁移计划，不能把归档当当前数据源 | 只读索引，未读取归档/资料，未执行恢复脚本 |
| 27. `remote-workspace` | 远程开发、候选构建、证据、隔离验收目录；仅本层目录元数据 | 无统一业务 API；按其中明确选定的候选项目执行开发/验收，不自动发布 | 包含本轮独立蓝图验收环境，但不等于生产业务；不能把暂存副本再计为业务系统 |
| 28. `reports` | 报告/结果文件目录；仅目录元数据 | 受控文件读取或原报告生成接口，必须保留文件所属用户/任务 | 未读取内容；报告可能含过期或敏感信息，不能直接用作实时业务查询结果 |
| 29. `state` | 共用运行状态目录；仅目录元数据 | 只能经所属服务的状态 API；禁止直接改未知状态文件 | 所属服务映射未核验，无可宣称已接入的业务 |
| 30. `subscription-integration` | New API/订阅网关开发、部署候选与验收材料；`prepare-release.py`、`deploy-release.py`、`new-api/README.zh_CN.md` 路径与子目录类型元数据 | 业务应接入在用 New API/订阅网关接口，不读开发 SQLite、测试凭据或候选环境作为生产；支付/订阅写入需独立权限与幂等校验 | 已观察在用 New API 及 subscription-gateway 容器，但不能由暂存目录证明端到端订阅业务通过；先确认唯一部署来源与安全接口契约 |
| 31. `venvs` | Python 虚拟环境目录，含工具运行环境；仅目录元数据 | 无业务 API；通过所属程序调用，环境安装/升级属于运维 | 仅索引；不是独立业务，不应向操作人员增加一个菜单 |

## C. 同一台服务器发现、但不在上述 31 项范围内的独立系统

这些仅由容器名称、镜像、Compose 工作目录标签发现。**本轮未进入其源码目录、读取配置或数据，也未调用业务接口。** 当前项目授权范围不能因同一台服务器而自然扩展。下表用于避免漏报和避免误宣称已覆盖，不是接入完成清单。

| 独立系统 / 观察证据 | 元数据揭示的归属 | 已知与未知 | 若另行授权接入，最小依赖 |
|---|---|---|---|
| 医院不良事件旧系统；`hospital-adverse-postgres/minio/redis/clamav` 等容器 | `/home/zyd/hospital-adverse-dev/compose.yml`（Compose 标签） | 相关基础设施运行；不能据数据库容器判断业务前后端、登录或事件上报链路可用 | 先核验应用服务与 OpenAPI/路由契约、组织/科室/患者数据权限；读取事件与创建/提交/审核分别授权，禁止直写数据库 |
| 医院相关另一组基础设施；`hae-postgres/minio/redis` | `/home/zyd/hae-jeecg-infra/compose.yml`（Compose 标签） | 仅能识别基础设施组，不能确认是否新旧替代、同业务双栈或迁移目标 | 先确认系统所有者与唯一在用实例，再核验 Jeecg/应用侧认证和业务 API；避免双写两个库 |
| 通用 AI 助手；`general-pro-gateway/worker/openresponses` | `/home/zyd/general-pro-assistant/docker-compose.aliyun.yml` | 应用/网关容器运行；具体会话、附件、任务 API 和用户隔离未读取 | 取得应用会话/任务 API 契约、用户身份映射、模型调用额度与工具权限；不把网关名字等同兼容性证明 |
| `medins-gpt`；backend/gateway/searxng 等容器 | `/home/zyd/medins-gpt/docker-compose.yml` | 独立应用运行；名称不能充分证明具体医疗/医保业务及功能成熟度 | 先识别实际业务边界，再核验应用认证、检索与业务接口；涉及医疗数据时额外明确数据范围和审批 |
| 中医项目线索；`tcm-pro-postgres` 容器 | 未带可用 Compose 归属标签 | 仅数据库容器运行；没有确认应用服务或源码目录，不能说中医系统已接入 | 先找到应用所有者、源码与服务，再确定业务 API/认证；不得从库表反推并直接执行诊疗业务 |
| 旧幼儿园膳食平台；`child-health-meal-frontend/backend/postgres` | `/home/zyd/child-health-meal-platform/current/docker-compose.yml` | 独立前后端与数据库运行；不等同现在 Frappe Tongjianyun 的同一数据源 | 先确认是否仍在用、是否迁移或只作历史；若保留，应明确来源标识和单向/双向同步边界，避免重复食谱 |
| DeepSeek Team Gateway；gateway/runtime/ingress/postgres | `/opt/deepseek-team-gateway/deploy/compose.yaml` | 是独立模型/运行网关栈，不在本目录的 Harness 项目内 | 精确版本、模型 API、调用方身份、额度/订阅与执行权限分开核验；不按同名 DeepSeek 自动合并 |
| Codex Full Gateway 与 OAuth | `/home/zyd/apps/codex-full-gateway/oauth/compose.yaml`；`codex-full-gateway.service` | 旧网关及 OAuth 单元可观察到运行；不是 `.codex-deepseek` 的同一安装或状态目录 | 先确认应用实际调用链、OAuth audience/scope、执行主体和隔离范围；防止绕过站点用户权限 |

## D. 下一批接入建议与验收门槛

1. **先完成当前站点真实业务链，而不是增加目录数量。** 从 Education/HRMS 的出勤、ERPNext 的库存采购、Tongjianyun 的食谱修改各选一个独立闭环：不同角色登录 → 查询 → 明确业务写入 → 原系统回读 → 重复提交/拒绝/并发验证。入口可打开只记“入口通过”。
2. **Dify 优先复用已有受控登录设计。** 先验收 Frappe OAuth 到指定租户/工作区，随后接一个无副作用工作流。管理登录、应用运行 token、最终业务写入三种权限不要混用。
3. **New API 先做自己的模型/用量只读视图。** 明确账户映射与来源后再讨论订阅/配额管理；不得因为 Codex 有服务器权限就直接写订阅库或代用管理员 token。
4. **Harness、Qwen 桥、ChatBridge 作为执行/模型基础设施，而非一组“业务菜单”。** 在当前状态异常或真实模型闭环尚未通过时，目录仍可显示，但应标注“待验收/不可用”，不能自动路由真实业务写操作。
5. **范围外医院、通用 AI、中医和旧膳食系统先确认范围与唯一数据源。** 经用户明确选择系统后，再读取其公开接口说明和角色模型，建立单独适配器；本轮不扩展访问或实施接入。

每个新适配器的最小验收包应记录：项目/版本、实例来源、用户/组织映射方式、允许的读写操作、错误/超时状态、幂等键、审计关联、写后回读、权限拒绝测试和回滚/撤销边界。测试凭据和真实个人数据不得进入该文档或 Git。

## E. 可复核证据索引

- 目录数量算法：`tongjianyun/frappe_project_views.py:project_directories`；扫描范围明确包含顶层目录和 `native-bench/apps`，仅判断目录/Git 存在。
- 当前站点入口验收记录：`docs/unified-business-goal.md`；验收程序 `deploy/unified_business/check_coverage.py`。其结果不等于全部项目业务接入完成。
- 本轮安全元数据命令：`find` 限定目录层级；`docker ps` 仅 Names/Image/Status/Ports；`docker inspect` 仅 Compose working_dir/config_files 标签；`systemctl [--user] list-units` 与 `show` 仅 Id/WorkingDirectory/FragmentPath/ActiveState/SubState。
- 运行状态为本次观察快照，可能变化；`active/healthy` 不证明业务成功，`inactive` 也可能是正常的一次性任务。本文没有把元数据异常归因为配置、凭据或网络问题。
- 本文件仅文档产物，未部署适配器、未扩大 Codex/业务账号权限、未改任何服务器服务。
