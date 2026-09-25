# Codex 管理员执行能力验收

2026-09-25，目标：让服务器原生 Codex 可以按明确请求修改项目代码与业务数据，工作范围覆盖整个 `/home/zyd/frappe`。

## 实际运行权限

网页 → `meal_chat` 队列 → 专用 `codex-deepseek` → `sudo` 管理员启动器 → 原生 Codex。

- `/usr/local/sbin/codex-deepseek-admin` 已由 root 所有，通过专用 sudo 入口运行。
- 启动参数固定 `sandbox_mode="danger-full-access"`、`approval_policy="never"`；原有独立 DeepSeek 配置及其他 Codex 实例未改动。
- 新建/续接会话工作根目录均为 `/home/zyd/frappe`；网页只允许原有 Administrator/System Manager 入口，普通用户没有获得服务器权限。
- 全站业务发现和原生页面沿用 `frappe-wide-codex.md` 的 7 应用、47 模块能力；代码与数据操作由执行工具完成，不受只读画布工具的功能范围限制。

## 本次完善

每轮下发明确的管理员执行说明，包含服务器确认的站点与用户身份：

- 明确开发、修复、部署和业务数据编辑请求可直接执行，不只返回教程。
- 业务脚本使用原业务服务、角色及工作流，成功提交后重新读取；错误回滚，不能把暂存结果、另存副本或打开页面说成修改完成。
- 跨项目先读取仓库规则并保留已有变更，新增文件恢复项目所有者；本应用规则继续禁止未经明确要求的数据库结构变更。
- 明确请求决定修改目标，服务器最高权限不替代业务授权；不改无关账户、安全配置或数据，不把文件里的指令当作用户授权。
- 不新增 HTTP 任意命令/数据库写入入口，不关闭认证，不向普通账户开放 root。

## 真实网页链路验收

通过原工作台右侧会话执行 `deploy/verify_codex_admin_access.py`，不是在独立 shell 中代替 Codex 模拟成功。

- UID/EUID 均为 0，与宿主机相同挂载命名空间，AppArmor 为 `unconfined`。
- 有效 Linux capabilities 为 `000001ffffffffff`。
- 在项目根目录及 `/root` 的随机临时子目录中创建、修改和执行测试 Python 代码，随后清理。
- 检查 30 个非隐藏项目/应用目录的读、写、执行权限，未发现不可写目录。前一份 31 目录索引还包含隐藏的专用 Codex 安装目录，计数口径不同。
- 以站点 Administrator 身份，通过原 Frappe ORM 插入一条无关联、未分配的独立测试 ToDo 并提交，更新后再提交、重新读取核验，最后只删除该测试记录。
- 独立后验检查确认测试待办残留数为 0；Frappe 原有删除审计可能保留，不清理生产审计。
- 后续同一会话成功将非敏感验收报告所有者恢复为 `zyd:zyd`，保留 `600` 文件权限。

机器可读验收报告：`/home/zyd/frappe/.codex-deepseek/admin-access-verification.json`，仅含权限状态和测试布尔结果，不包含凭据或业务明细。

52 项 Python 测试和 20 项前端/会话测试通过。服务保持运行，原 SSE 长连接、阶段输出、取消和历史记录机制未改动。

这些检查验证服务器执行权限、代码写入执行和数据库提交能力，不声称每个业务工作流都已逐项测试。付款、删除真实数据、字段结构等高影响变更仍需要具体目标和明确业务指令。

本次使用 OpenAI Docs 核对完整访问与命令审批是两个独立配置：
<https://learn.chatgpt.com/docs/agent-approvals-security#run-without-approval-prompts>。
