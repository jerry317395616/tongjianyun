# 真实教师出勤 / 分餐隔离验收

日期：2026-09-25。运行器：`deploy/unified_business/check_teacher_scope_lifecycle.py`。

## 范围与结论

固定站点为 `unified-business-acceptance.localhost`；使用独立 MariaDB `127.0.0.1:23316/tgy_blueprint_qa`、独立 Redis `127.0.0.1:23379`。运行器在导入及连接前验证配置标记、精确路径、数据库/Redis、禁用调度器和非开发模式；候选源码必须位于隔离 remote-workspace。没有运行 HTTP、worker、scheduler，没有接触生产数据。

创建合成 User → Active Employee → Active Instructor → Student Group Instructor 身份链，两个新班、各两名虚构学生；教师仅分配其中一班。管理员只创建前置资料，所有正向业务调用均使用真实教师身份。教师角色是 `Instructor` + Education 普通 `Academics User`（Employee 控制器可能自动加 Employee）；明确断言没有 Administrator、System Manager、Education Manager、Tongjianyun Business Operator。

**修复后结果：54 / 54 项真实生命周期检查通过，127 / 127 项相关单元回归通过。** 没有为通过测试额外授予 DocPerm、管理角色或运行权限安装 hook。基线发现的教师出勤权限链路缺口已按下面的受限服务方案修复。

证据文件：

`/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925/teacher-scope-lifecycle-9680e04d9f.json`

成功证据和新合成班/学生保留。最终版本使用此前没有每日汇总的过去日期 `2026-09-21`；新汇总按原服务包含所有活动合成班，不修改其他班学生事实。原 `2026-09-25` 已锁定每日汇总、原班名册和原分餐记录保存前后 `as_json()` 完全一致。初版修复证据 `teacher-scope-lifecycle-5b54b08dea.json`（54 项通过，日期 09-22）以及基线失败证据 `teacher-scope-lifecycle-24edb928b3.json`（28 项通过、1 个真实 gap，日期 09-23）同样保留。

## 实际通过的教师闭环

- 授课范围只含分配班；权限过滤的班级、Student 列表不含其他班学生；未登记显示 Unknown。
- 本班一名 Unknown → Present 保存 → 回读 → Absent 修改 → 回读；另一名始终 Unknown。过期考勤 revision 拒绝，第二连接读取已持久化 Absent 和 Unknown。
- 不经过课堂包装器，直接调用原点名服务同样支持本班正向保存；跨班、外班学生注入及“第一条合法、第二条跨班”的混合批次均在写入前拒绝，第一名原状态不变。
- 原点名服务响应仅含授课班明细，没有全校 total 字段或其他班学生。教师原生日汇总 read/create/write 权限仍全部 false。
- 真实 Frappe resource handler 的每日汇总 read/list/create/update 全部拒绝教师。未启动 HTTP 服务，这验证的是原生 handler 与 DocPerm/ORM 路径，不是浏览器 Cookie 或 Web 网络链路。
- 仅对本次新合成日暂设“已确认 / 已锁定”，两种状态下 UI 能力、课堂保存、直接服务保存均拒绝；每项测试后回滚锁定状态，不变更历史锁定 fixture。
- 本班早餐两人分别就餐 / 不就餐 → 实际人数 1；午餐仍未确认，全日仍“待确认”。
- 陈旧分餐 revision 被拒绝；修改已确认早餐不填原因被拒绝；带原因改为两人就餐后回读人数 2。
- 分餐保存不把未知考勤写成到园；第二个独立数据库连接仍在真实教师身份下回读已持久化结果和授课范围。
- 跨班精确 ID 的出勤/分餐读取、保存被拒绝。出勤使用管理员事先读取的有效目标班 revision，分餐使用有效空初始 revision，避免把“版本错误”误算作权限拒绝。
- 把其他班学生塞入本班分餐名单被拒绝；未来实际就餐被拒绝；拒绝后没有产生跨班或未来业务记录。
- 同一教师账号停用后，课堂出勤/分餐四个读写入口均被拒绝。
- 教师不能调用全校确认。没有执行生产写入、浏览器点击或 HTTP 会话验收。

修复后，在本班过去日期可正常保存的同一教师身份下，课堂和直接服务的未来出勤都独立拒绝。disabled 账号除了课堂四个入口，也不能直接调用原点名服务和原分餐保存服务。私有汇总 helper 未被 whitelist，不能作为远程方法调用。

## 已实现的最小安全修复

- `classroom._capabilities` 使用 `daily_meals.attendance_write_allowed`；该能力是提示，保存时会再次验证，不代替授权。
- `daily_meals.save_student_meal_attendance` 保留启用用户和 editor 角色要求，新增 Student / Student Group / Student Attendance 原生 read 要求；当前身份解析授课范围。完整批次先验证格式、班级、学生、启用、重复、状态、请假原因和日期，再锁定班级、复核权限与成员，最后调用内部派生汇总及原写入服务。
- 私有 `_get_confirmation_for_edit(meal_date, student_groups)` 独立复核当前身份和组范围，以 `get_doc(..., for_update=True)` 锁定并读取当前已确认 / 已锁定状态，避免等待行锁后再从早前重复读快照取状态；教师只通过这条受限业务路径触发原派生汇总。没有增加请求参数 `ignore_permissions`、`internal`、`actor` 或可由客户端设置的放行标记。
- 管理角色仍要求原 Daily create/write 文档权限；`get_daily_meal_confirmation` 仍做原生 read 检查，教师被拒绝；教师改从课堂视图回读本班结果。
- `_require_login` 增加 disabled 拒绝，并用于全校确认/重算入口。`meal_attendance_roles.install` 恢复成幂等、无写入的兼容模块，避免原 after_migrate 引用缺失；不自动分配角色或修改权限。
- 正向教师使用现有 `Instructor + Academics User` 基础角色。仅有 Instructor 但没有原生 Student Attendance read 的账号仍不可编辑；本轮不暗中扩大权限。Teacher / Employee / Academics User 单独角色不是 attendance editor，也不能通过直接服务获写。

Keyless `test_attendance_scope` 共 26 项；隔离 `--unit-tests-only` 运行 scope、teacher_permissions、classroom、student_meals、workspace_entry 五模块共 127 项。修正了旧 workspace_entry 单测 fixture 漏掉已有 `meals` 返回字段的问题，仍断言不能泄漏其他班索引。

## 原始阻塞证据与设计决策

修复前调用链：

1. `classroom._scope` 校验启用用户、Student Group 基础读取权限、授课范围及具体文档权限，正常。
2. `classroom._capabilities(day)` 要求每日汇总已有记录时 write、无记录时 create。Instructor + Academics User 的这两项都是 false，因此 `attendance_write=false`；分餐 write=true。
3. `classroom.save_attendance` 在调用原服务前据此拒绝。即使只修改前端或该能力判定，`daily_meals.save_student_meal_attendance` → `_get_confirmation_for_edit` 仍要求每日汇总 DocPerm，会再次拒绝。
4. 原标准 `Tongjianyun Daily Meal Confirmation` 只有 System Manager / Business Operator 权限；`hooks.after_migrate` 引用的 `tongjianyun.meal_attendance_roles.install` 模块原本不存在。没有用测试站点临时权限补丁遮盖安装缺口。

推荐保持每日汇总为管理级原生 DocType，按已有受限课堂服务办理教师点名，而不是给 Instructor 全校每日汇总读写权限：

| 位置 | 最小约束 |
| --- | --- |
| `classroom._capabilities` / `save_attendance` | 共用服务层能力判定；真实启用 Instructor、基础考勤可读、有效授课班、非未来、非已确认/已锁定。不要让 UI 有能力而保存仍依赖每日 DocPerm，也不要仅用角色就授任意班权限。 |
| `daily_meals._require_login` | 拒绝 disabled 用户，不只拒绝 Guest；原服务可被直接调用，不能只依赖课堂包装器。 |
| `daily_meals.save_student_meal_attendance` | 在任何写入前完整验证所有 changes 的班级范围、当前有效成员、重复、状态、请假原因和日期。教师只允许授课班；保留管理角色原行为，不能接收调用方伪造 actor / ignore_permissions 参数。 |
| `daily_meals._get_confirmation_for_edit` | 对已经通过受限点名授权的服务内部路径读取/锁定每日状态；允许由原 `refresh_confirmation` 内部生成派生汇总。管理文档权限不变；不向任意调用者暴露跳过权限开关。已有已确认/已锁定拒绝仍有效，锁后再次核对。 |
| `daily_meals.refresh_confirmation` | 继续只作为内部派生汇总，不能提供教师任意重算/解锁全校 API。现有 `ignore_permissions=True` 只用于由受限业务动作触发的汇总，不扩为通用写入。 |
| 响应读取 | 教师返回 `visible_confirmation` 授课班明细及本班考勤；不能为了让 `get_daily_meal_confirmation` 通过而新增全局 Daily DocPerm。若保留此 API 的教师读取，须先检查启用、授课范围，再返回过滤结构；原生文档读权限仍拒绝。 |
| 缺失安装 hook | 优先恢复实际需要的窄权限模块或移除无效挂钩。Instructor 原生没有 Student Attendance read；若产品要求只需 Instructor，不加 Academics User，安装 hook 只补所需考勤只读权限并沿用 teacher row hooks。不要给教师 Daily 汇总全局 CRUD。 |

为什么不能简单加 Daily 权限：每日单据的 child table 包含全校班级，当前 `visible_confirmation` 只保护指定业务 API，不能过滤原生 Form / REST 直接读取整张单据。班级分餐单据有 `student_group` 行权限，不能把它的授权方式原样套到全校汇总。

本次选择保持 `get_daily_meal_confirmation` 原文档权限；验收明确断言教师拒绝，并通过 `classroom.get_overview` 回读本班结果，没有为测试要求扩权限。

## 重跑

将本地脚本复制到 `/home/zyd/frappe/remote-workspace/check_teacher_scope_lifecycle.py`，使用既有固定环境：

```sh
UNIFIED_BUSINESS_SITES=/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925/sites \
UNIFIED_BUSINESS_SOURCE=/home/zyd/frappe/remote-workspace/unified-business-20260925 \
/home/zyd/frappe/native-bench/env/bin/python \
/home/zyd/frappe/remote-workspace/check_teacher_scope_lifecycle.py
```

脚本自动选择同一合成年内没有每日汇总的过去日期，不重置旧证据。任何 gap 输出 failed 并非零退出；失败报告区分 fixtures 是否 committed。权限 hook 只有显式 `UNIFIED_BUSINESS_INSTALL_ATTENDANCE_ROLES=1` 才会运行，而且必须来自候选源码；本次没有启用该选项。不要将脚本改成生产站点运行。

增加 `--unit-tests-only` 可只运行上述五模块回归，仍必须通过相同隔离守卫；不会创建新的生命周期 fixture。没有部署或提交本轮修改。
