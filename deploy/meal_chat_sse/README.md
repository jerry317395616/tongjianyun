# 膳食对话 SSE

消息 API 只负责校验、去重与入队。专用 `meal_chat` RQ Worker 使用
`timeout=-1`；Codex 子进程没有总时长截止。停止由用户主动触发。

任务阶段以 Redis Stream 保存 14 天（运行时续期），浏览器通过 SSE 接收，
以 `Last-Event-ID` 续传。刷新页面从当前用户的任务记录恢复，不重新执行任务。
SSE 每 10 秒发心跳，由单独的 Gunicorn gthread 服务承担连接；该服务
`--timeout=0`，原业务 Web 配置不变。专用 worker 子类兼容本机 Gunicorn
对每请求截止时间的额外补丁，零值映射为无限期，不修改上游包。
Nginx 关闭此路由的缓冲、压缩和缓存。
`proxy_read_timeout=3600s` 是相邻数据之间的空闲限制，心跳会续期，
不是任务总时长。代理或网络仍可能断开；前端自动重连。

只推送用户可见消息和工具开始/结束状态，不输出推理、完整命令或工具原始内容。
接口保留系统管理员鉴权，并按站点和用户隔离任务记录。

部署代码后，在 Native Bench 主机以 root 运行本目录的 `install.py`。
它只增加一个队列、两个 systemd 服务和一个 Nginx location，备份配置到
`/home/zyd/frappe/native-bench/config/backups/meal-chat-sse-*`，不运行数据库迁移。

回滚时先确认没有运行中的对话任务，再停止本目录两个服务，恢复备份中的
Nginx 与 common_site_config 配置及对应代码，验证 Nginx 后重新加载 Web/代理。
原有 RQ 长任务队列不受新队列占用影响。

验证：在应用目录运行 Python `unittest tongjianyun.tests.test_meal_chat` 与
Node `--test tongjianyun/tests/test_meal_chat_ui.cjs`。共 14 项测试覆盖阶段顺序、
去重、权限、停止、心跳、续传和无限执行时长配置。
`tongjianyun.tests.test_meal_chat.verify_http_stream` 可通过 Bench execute
运行 130 秒公网 HTTPS 集成探针：只创建临时认证会话和明确标注的测试任务，
不调用模型，不写业务记录；认证会话在结束后删除。运行前必须没有管理员任务。

已验证公网 SSE 首条事件约 3 秒到达、130 秒任务正常完成、12 次心跳及
Last-Event-ID 续传；页面还验证了真实 Codex 阶段输出、主动停止和刷新恢复。
总时长不限不等于网络永不断开，服务重启或模型供应商报错仍会被明确报告。
