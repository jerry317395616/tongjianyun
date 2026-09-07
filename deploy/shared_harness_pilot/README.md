# 共享 Harness 教师试点部署记录

2026-09-07：使用两个已存在、已启用的测试 System User，不创建账号、不重置密码、不改变角色或班级分配。

| 测试账号 | 已分配班级 | 实际 ORM 可见学生 | 范围外学生 |
| --- | --- | --- | --- |
| harness.test.teacher.a@example.invalid | 中班 | 101 | 0 |
| harness.test.teacher.b@example.invalid | 大班 | 119 | 0 |

已部署两个身份续期 oneshot 服务及两分钟 timer，以及 `ione-harness-shared-identity.service` 用户服务。全部以 zyd（UID 1000）运行，身份配置与 Unix socket 位于私有目录。辅助服务不是第二个 Harness。配置只允许读取 Student、Student Group、Student Attendance、Student Leave Application，不允许读取 User 或业务写入。

部署配置模板保存在本目录。配置中仅引用既有签名文件路径，不包含密钥值；运行配置必须 chmod 600，配置目录及 identity 子目录必须 chmod 700。通过现有 native_actor_refresh.py 和 shared_identity.py 实现，不复制上游业务逻辑。

`verify_shared_pilots.py` 只检查当前账号权限并输出人数。`accept_shared_identity.py` 通过现有 Frappe 签发方法和实际 Unix 身份服务验证，票据只在测试进程内传递，不输出或落盘。验收通过：签名交接、票据单次使用、账号绑定、学生列表隔离、跨班级直接读取拒绝、User 类型拒绝、退出授权撤销。测试查询遵守每页最多 100 条的现有限制，未调整后端限制。

这不是浏览器密码登录验收。测试通过管理员授权的固定测试账号上下文签发交接，不证明用户自行登录流程已完成。尚未切换既有 Harness 运行配置、公共代理或开启 Frappe 共享入口。原管理员实例仍在运行。下一步需要把同一个 Harness 切换到受限共享配置，再验证 HTTPS 浏览器交接和聊天查询；在此之前不得向普通用户宣传共享聊天已上线。

停用本次辅助服务可使用 `systemctl --user disable --now ione-harness-teacher-a.timer ione-harness-teacher-b.timer ione-harness-shared-identity.service`。这不删除账号、班级或业务数据，不修改原 Harness 服务。
