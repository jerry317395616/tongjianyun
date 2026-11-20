# 统一场景：学生出勤验收

日期：2026-09-25。范围：代码只读审计及后续场景前端；不把入口可打开当作业务已验收。审计期间没有修改生产数据，也没有为验证点名而创建、修改或取消真实学生记录。

## 已有能力与入口

| 需求 | 已有实现 | 统一场景现状 / 限制 |
| --- | --- | --- |
| 按班、按日查看 | `business_views.classroom_view` → `classroom._scope/_attendance` | `classroom_day` 已呈现统计和名单；未登记明确为 Unknown，不当出勤或缺勤。 |
| 查看原考勤、请假单 | `business_list/business_record` + 原生 `frappe_document` | 可保留右侧助手，在左侧 iframe 打开原表单；不必跳出主场景。 |
| 登记 / 修改点名 | `classroom.save_attendance(student_group, day, changes, revision, workspace=None)` | 课堂页面已有编辑器，统一场景原本没有对应编辑组件；应复用服务，不另写裸 DocType 批量保存。 |
| 保存后回读 | `classroom.get_overview` / `classroom_day` | 服务保存结果只返回 `saved` 数量；必须再次权限化读取，不能把本地草稿直接当最新事实。 |
| 原生新增 / 编辑 | Education `Student Attendance`，状态字段 `allow_on_submit=1` | 技术上可在场景 iframe 完成，但与童健云未来日期、膳食确认锁定等规则不完全等价，不能宣称直接代替点名服务。 |

## 权限与业务边界

- `classroom._scope`：启用的登录用户、Student Group 读取权限、`allowed_groups()` 授课范围及具体班级读取权限。
- 名册：当前启用学生、班级有效成员、Student 读取权限交集。历史日期仍使用当前名册，不回溯历史学籍。
- `_capabilities(day)`：编辑角色、Student Attendance 可读、每日就餐确认的创建/写入权限、日期不晚于今天、每日汇总不是“已确认 / 已锁定”。
- `save_attendance`：按班级行锁串行、重新读取 revision；拒绝名单变化、跨班/停用/重复学生、Unknown 写入、缺失请假原因；只保存明确发生变化的条目。
- 旧服务 `daily_meals._set_student_status` 内部使用 `ignore_permissions=True`。这是现有受限业务服务的实现，不应由新页面复制或扩展成通用无权限写入。入口必须保持 `_scope` 和 `_capabilities` 检查。
- 有生效请假时，改为 Present / Absent 会被原服务拒绝，需原请假流程撤销或标记返校；对已有请假再次填原因不会更新原单原因。因此编辑器不应承诺直接改请假原因。
- 考勤不等于实际就餐；不能因登记出勤自动确认五餐真实食用情况。

## 服务器 Education 原生入口审计

读取位置：`/home/zyd/frappe/native-bench/apps/education/education/education/`。

1. `doctype/student_attendance/student_attendance.py` 的 `validate()` 中 `self.validate_date()` 被注释。虽然存在日期校验函数，原生单据保存当前不会调用它，不能据此承诺未来日期受到后端阻止。
2. `Student Attendance` 原生保存仍检查成员、重复记录及节假日。JSON 定义 `is_submittable=1`，`status.allow_on_submit=1`；当前站点 Custom DocPerm/工作流可能进一步改变权限，须用真实账号复核，而不是只看源码角色列表。
3. `Student Attendance Tool` 的日期限制在前端；`get_student_attendance_records` 用 `frappe.get_all` 读取子表名册、Query Builder 查询考勤，函数本身未核验授课班级范围。先补权限或验证既有全局拦截后，才能把它列为教师安全批量点名入口。
4. `education.education.api.mark_attendance` 是独立批量入口，显式 `frappe.db.commit()`，且与童健云 revision/确认锁定流程不同。不要用它进行“可回滚”的生产验收；不要用它替代已有课堂服务。
5. Tongjianyun 考勤事件 hook 刷新每日膳食汇总；`refresh_confirmation` 遇到已锁定/已确认时保留汇总，不等于阻止原生考勤变更。原生单据写入与统一点名服务之间存在业务规则差异。

## 最小落地方案

复用现有 `classroom_day` 视图，在统计下方增加一个注册组件 `attendance_register`，展示明确的“班级 + 日期”、每生原登记、本次状态及必要的请假原因。

组件数据建议：

```json
{
  "type": "attendance_register",
  "student_group": "已核验班级编号",
  "group_label": "班级名称",
  "day": "YYYY-MM-DD",
  "revision": "原服务返回的版本",
  "editable": true,
  "reason": "不可编辑时的业务原因",
  "rows": [{"student":"编号","student_name":"姓名","status":"Unknown","source":"尚无登记","attendance_record":null,"leave_record":null}]
}
```

普通保存不弹第二次确认：只提交已变化项，使用服务端原 revision。未保存离开才确认。按钮先显示“正在保存”，响应成功后明确“已保存，正在回读”，回读成功后才展现最新统计。网络失败视为结果未知，保留草稿、禁止盲目重试，提供“重新读取并核对”入口。

日期、班级采用明确上下文，不从膳食餐次推断，不把当前周历日期暗中套到任意原生表单。原生列表/新建表单目前不会自动带入班级和日期，应使用专用组件维持这一语义。

## 必须验收的真实流程

在隔离测试站点使用测试班级和虚构学生；生产只做只读核对，除非另获明确授权。

1. 老师仅看到授课班级；跨班精确编号、伪造班级、禁用账号和 Guest 均被拒绝；普通只读账号没有保存动作。
2. 指定某班今日出勤：在同一场景显示完整、权限过滤后的名单；Unknown 是“待登记”，四种状态总数等于名册人数。
3. 只把一名 Unknown 改为 Present 后保存：提交 1 条变更，Student Attendance 和回读状态一致，其他学生仍为 Unknown；不写实际用餐确认。
4. Present → Absent 再保存：按原服务更新既有记录，不产生同日同班同生重复记录；回读反映修改。
5. 新请假必填原因；创建后回读显示请假来源；已有请假改到园须先原请假流程处理，不绕过或伪造成功。
6. 两个会话同时改相同班级：旧 revision 拒绝，原草稿不误显示为已保存。切换日期/班级不能带着旧 revision 写入新范围。
7. 未来日期、已确认和已锁定每日汇总均不可保存。提示明确区分无权限和业务锁定。
8. 保存成功后故意让回读失败：提示“保存已返回成功，回读失败需核对”，不得用旧统计伪装新状态；保存响应丢失则不盲目重发。
9. 有草稿时后台任务 terminal / 自动刷新不覆盖编辑器；用户切换业务时取消离开可保留草稿；用户明确离开才丢弃。
10. 在左侧打开已有原考勤表单，不关闭右侧会话；日期/班级清楚可见；原生 Form 路由同步助手上下文；保存和审批状态以原表单回读为准。

## 尚未验证

没有针对真实用户角色运行生产读写闭环，没有评估全量 Custom DocPerm、Server Script 或其他应用对 Education 的运行时覆盖，没有断言原生工具现有权限漏洞已被利用。上述原生缺口来自源码路径审计；需后续隔离测试确认影响并优先使用已受限的课堂服务。

## 本轮前端实现

`meal_scene/views.js` 已注册 `attendance_register` 和 `meal_register`。出勤保存沿用 `classroom.save_attendance`，分页回读保留当前 offset；分餐沿用 `classroom.save_meal`，只办理选定班级/日期/餐次，提交全名单，未确认状态不会从预计值预填为真实就餐。修改已确认本餐需填写原业务要求的原因。

两种编辑器均无保存前二次确认，仅离开未保存内容时提示；保存中阻止切换和重复提交，保存成功后重新查询，响应丢失或回读失败提供“重新读取并核对”，不显示伪造成功。已有原生 iframe 和蓝图组件继续保留。

这些是代码实现和本地 UI 单元测试结果，不是生产数据读写验收结论。真实闭环仍应按上述隔离站点流程执行。
