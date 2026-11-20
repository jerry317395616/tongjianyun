# 教师视频考勤：Windows 采集 + 服务器分析

当前版本是**人工核实试运行版**，不是无人审核的正式考勤系统。
已包含连续分段录制、设备隔离上传、分片续传、校验、识别候选、管理员核实、HRMS Employee Checkin 接入。
单目 YuNet/SFace **不提供可靠活体判定**；不把最后露面当签退。所有核实打卡 `skip_auto_attendance=1`。
没有自动创建 Attendance、缺勤或工资，没有修改 HRMS 源码。

## 服务器

代码均在 tongjianyun。需要 HRMS、FFmpeg、独立 Python 3.12 识别环境。
推荐锁定 `opencv-python-headless==4.13.0.92`、`numpy==2.2.6`。
运行 `install-models.py <私有模型目录>`：下载公开 OpenCV Zoo YuNet/SFace 权重，核对 SHA256，保存 MIT / Apache-2.0 许可。
不得把人脸照片、模板、摄像头地址/密码、设备 API 密钥提交 Git。

站点配置 `tongjianyun_video_attendance`：

```json
{
  "processing_enabled": true,
  "python": "/absolute/path/to/isolated-venv/bin/python",
  "models_dir": "/absolute/private/model/directory",
  "preview_threshold": 0.5,
  "preview_margin": 0.12,
  "retention_days": 3
}
```

这两个阈值仅为候选预览初始值，不代表完成现场校准或可用于自动打卡。
执行 `bench --site SITE execute tongjianyun.video_attendance.setup.install`。
部署 hooks.py 增量（after_migrate / cron / page_js）；重启 web、long worker、scheduler 使代码生效。
页面 `/desk/teacher-video-attendance`，业务工作台工具栏有入口。

只向获授权的系统管理员开放视频、模板管理和候选审核；其他登录教师只能查询与本人 User 关联的 Employee 打卡。
通用业务角色不自动获得生物识别资料访问权。

## 园内 Windows 10/11

1. 安装 Python 3.11+ 与 FFmpeg，记录完整路径。采集程序本身不依赖第三方 Python 包。
2. 创建专用上传用户（不授予学生、员工或考勤管理权限），从 Frappe 用户页面生成 API Key/Secret。
3. 在「教师视频考勤 → 设备设置」创建设备，绑定该上传用户、指定 IN/OUT 专用通道方向。完成点位/传输授权核验后才启用。
4. 将 `config.example.json` 复制为私密 `config.json`。填写实际 LAN RTSP URL、专用 API 凭据和 FFmpeg 路径；实际路径以摄像头能力探测为准。
5. 校准摄像头与电脑时间，Windows 时区设为园区当地时区；检查采集日期/时段。默认示例仅周一到周五 06:30–19:30，节假日需管理者调整。
6. 以管理员 PowerShell 执行：

```powershell
.\install-windows.ps1 -ConfigPath C:\Private\config.json -PythonPath C:\Python312\python.exe
Start-ScheduledTask -TaskName TongjianyunVideoCollector
```

安装器使用开机计划任务以 SYSTEM 身份后台运行、失败重启；不是需要打开浏览器的桌面程序。
目录 `C:\ProgramData\TongjianyunVideo` 限制为 SYSTEM/管理员访问。安装后请安全处理原始配置副本。
请使用面向全机安装的 Python/FFmpeg；SYSTEM 必须能执行，不支持 Microsoft Store Python 别名。
配置中 RTSP 特殊字符须 URL 编码；凭据不进日志，但本机管理员可能从 FFmpeg 进程参数看到它，需限制本机管理员。
电脑与摄像头需持续供电、关闭自动睡眠；不修改客户电脑电源设置，由现场确认。

## 数据与异常

- HTTPS 出站上传，无需摄像头公网端口或服务器反向连接园内。
- 关闭音频录制。FFmpeg 持续录制 MP4，只有 CSV 标记已关闭的片段允许上传，异常尾段不猜测时间。
- 以视频流 wallclock 时间为基准；采集前与服务器比对电脑时间。时间不可验证时保留本地，不替换成上传时间。
- 上传按 256 KiB 分片，片段 ID + SHA256 幂等；设备只能写自己绑定的片段。
- 最长单段 180 秒，最大 128 MiB，站点视频存储上限 32 GiB，未完成上传最多每设备 250 个。
- 本地默认上限 20 GiB，满盘停止采集并报警，**不覆盖未上传视频**。已确认上传视频缓存 24 小时后删除。
- 初始服务器视频最多保留 3 天（按实际拍摄时间计算，可在 1–7 天内配置），过期未审核记录不能自动转考勤。
- 离线补传最长 7 天，仅生成待核实候选；超过窗口需另外人工补卡，不偷偷放宽实时接口。
- 服务器和本地都不是无限期档案库。采集失败/缺段不代表教师缺勤。
- 注册原图在临时私有目录处理后删除；模板加密保存，撤回后停止识别并删除当前模板。备份副本依备份策略到期清理。
- 不建立学生、家长、访客库，不储存未知人脸裁剪/特征；选教师专用通道并控制拍摄区域。

## 上线前验收

必须现场验证：摄像头真实码流与时间戳、上行带宽、录像清晰度、正常/遮挡/逆光/多人、正确方向、断网、电脑重启、重复上传、权限撤回。
以已取得授权的教师样本做对照，不把合成视频测试当作识别准确率验收。
保留便捷非刷脸签到途径，事前进行隐私影响评估和相应告知/单独同意。
当前没有启用自动考勤；后续需要活体/防冒用、方向验证、阈值校准、采集完整性与班次验证后才能另行灰度开放。

## 测试

`python -m unittest tongjianyun.tests.test_video_attendance -v`
真实 HTTP 集成测试使用专用临时用户、临时设备及无人物合成视频；不生成教师考勤。
