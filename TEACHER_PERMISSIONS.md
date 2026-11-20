# 教师记录范围限制

本次仅修改 Tongjianyun 应用代码，不修改 DocType、Custom Field、Property Setter 或角色权限定义。

## 覆盖范围

通过 Frappe 的 permission_query_conditions 和 has_permission 钩子，对非管理教师的 Student Group、Student、Student Attendance、Student Leave Application 增加记录范围限制。条件与平台既有权限相交，不授予额外权限。

身份来自框架传入的用户，通过在职 Employee.user_id、启用 Instructor.employee、Student Group Instructor 关联到启用班级。学生必须在该班级的启用成员中。缺少关联时返回空范围。考勤和请假同时检查学生与班级；不允许仅凭学生当前归属读取其其他班级历史。

Administrator 和现有管理角色保留框架权限；其他非教师角色的权限不在本次修改范围内。

## 验证

- test_teacher_permissions.py：角色边界、身份缺失、成员关联、直接文档读取、考勤/请假双重范围。
- test_attendance_scope.py：已有就餐接口的班级范围回归。
- child.myyr.top 两名测试教师通过实际 Harness Python 查询程序查询全部分页：分别返回中班 101 人、大班 119 人，与班级成员集合完全一致。
- 对方班级查询返回空；对方学生按编号查询返回空；框架直接文档权限检查拒绝跨班读取。
- Administrator 仍可见 3 个启用班级。验证没有写入学生或出勤记录。

## 尚未覆盖

Frappe get_all、ignore_permissions 和主动绕过权限的业务代码不受查询钩子自动保护，不能作为普通用户工具开放。此修改也没有打通 Harness SSO 与 Agent 执行身份。若工具仍使用固定 Administrator，教师限制不会替代该账号的权限；共享对话执行必须在身份绑定验收完成后开放。

测试教师仅用于测试，不作为真实人事资料。正式投用前应替换为真实教师关联，并另行安排测试账号清理。
