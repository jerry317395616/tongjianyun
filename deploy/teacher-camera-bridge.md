# 教师摄像头接入层（2026-09-14）

所有扩展位于 tongjianyun，不修改 HRMS。HRMS 已安装。

## 已实现

- 内部函数 `tongjianyun.teacher_camera.ingest(event, dry_run=True)`，非白名单 API，不可从浏览器匿名调用。
- 使用受信识别器的标准事件，不把海康抓拍事件当作已识别身份。
- 检查设备、教师授权映射、在职状态、当前账户权限、单人、活体结果、置信度和候选差距。
- 时间必须带时区；只接受最近 5 分钟及最多未来 30 秒的事件，历史补传暂不自动入账。
- 摄像头配置固定 IN 或 OUT；不能凭最后露面推断下班。
- HRMS Employee Checkin 写入保留官方验证和权限，不使用 ignore_permissions。
- 事件 ID 派生唯一名称，员工行锁串行化写入，同方向前后 60 秒去重。
- 默认预览，正式写入另需 enabled=true。skip_auto_attendance 固定为 1，待校验班次与灰度验收后另行开放自动考勤。
- 不写 Attendance/工资，不存照片、人脸模板和原始事件；调用方负责事务提交/回滚。

## 部署配置（目前未配置，保持关闭）

站点私密配置键 `tongjianyun_teacher_camera`：enabled 布尔值；cameras 为 camera_id 到 enabled/direction 的映射；subjects 为 subject_id 到 employee/consent 的映射；min_confidence/min_margin 必须由实测校准，范围 0 到 1，没有默认阈值。

事件字段：event_id、camera_id、subject_id、occurred_at（ISO8601带时区）、face_count、liveness_passed、confidence、margin。

这些字段必须由受信服务器识别器生成，不能信任摄像头或外部客户端自报的姓名、分数和活体结果。当前没有开放网络接收端，也没有启动识别服务。

## 尚未实现 / 实机前置条件

摄像头联网/VPN、真实事件订阅和断线恢复、人脸识别模型及活体实现、经同意的教师注册照片、管理页面、持久异常审核队列、非刷脸签到入口、正式运行的审计与照片保留策略。此版本是后端接入准备，不是完整刷脸考勤上线。

先联网验证 camera_preflight，随后选定合法可部署识别器，校准阈值和方向，再开展灰度；切勿直接开启配置作为生产验收。

## 测试

`env/bin/python -m unittest tongjianyun.tests.test_teacher_camera tongjianyun.tests.test_camera_preflight -v`

识别策略用模拟输入测试；写入分支使用数据库替身，不对真实教师制造测试打卡。真实摄像头和真实 HRMS 写入联调仍待完成。
