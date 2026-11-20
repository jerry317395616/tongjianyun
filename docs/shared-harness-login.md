# 共享 Harness 登录入口（待上线）

本阶段只增加独立的 Frappe 登录转接方法，不替换现有入口，不上线共享聊天界面。

入口：`/api/method/tongjianyun.harness_shared_login.launch`。

调用链：当前 Frappe 会话 → 检查站点、显式账号名单、启用的 System User → 复用 `ione_core.harness_auth.launch` 签发短期交接 → 固定转向 `https://harness.myyr.top/employee/sso`。未登录用户先进入 Frappe 登录页，登录后返回本入口。请求不能指定用户、站点或重定向地址。Administrator 不作为普通员工入口的回退身份。

部署默认关闭。将来验收后，站点配置 `tongjianyun_shared_harness_enabled` 必须为整数 1 或布尔 true，`tongjianyun_shared_harness_users` 必须为明确的账号列表（最多 256 项）。名单还必须与共享身份服务配置一致；此名单不是角色授权，不授予任何 DocType 或数据权限。

本次不设置上述配置，不读取或显示密钥，不修改旧 `/sso` 路由，不重启服务、不迁移、不改变 DocType 或业务记录。现有签名实现固定 child 站点，因此本入口拒绝其他站点，而不是冒用 child 身份签发。响应禁止缓存并禁止发送 Referer。

上线前仍需完成：共享聊天界面、外层代理仅允许员工接口、共享身份服务及名单配置、真实浏览器 HTTPS 单次交接和两个教师账号的班级隔离验收。不要把现有 Host 登录链接分发给普通用户。单个 Linux 用户 zyd 不提供操作系统级隔离，普通用户仍不得访问 Shell、任意文件、配置或源码编辑能力。

验证：`env/bin/python -m unittest tongjianyun.tests.test_harness_shared_login`（从 Native Bench 执行）。测试不签发真实票据，不访问生产学生数据；不能作为共享聊天已上线的证明。
