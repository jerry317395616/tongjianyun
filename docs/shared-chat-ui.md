# 共享 AI 聊天界面（未切换生产入口）

源码：`tongjianyun/public/shared_chat/`。这是员工专用的静态界面，不是管理员 Host Web UI，也不需要新建 Page 或 DocType。

首版支持登录状态检查、新建对话、提交只读问题、展示最近 50 条最终文本、停止等待、退出员工登录。只调用同源 `/employee/status`、`/employee/logout` 和 `/employee/session/create|prompt|page`。身份由 HttpOnly 登录 Cookie 和服务端会话归属确定，客户端不传 user/site/preset，不存储票据、Cookie 或对话到 localStorage。

页面刷新后开始新对话，不删除服务器历史；暂不提供历史会话恢复。现有列表接口不返回恢复历史所需的游标，前端不能猜测游标或改用管理员接口。结果页不渲染推理、原始工具结果或 HTML；最终文本以 textContent 输出。取消、网络失败后不自动重试，提示结果状态未知。

## 发布条件

必须部署到共享员工 API 的同一个 HTTPS origin，预定路径 `/employee/chat/`，不能直接把 child 的 `/assets/` 链接作为已连通聊天入口。后者与 Harness 不同源，身份 Cookie 不能这样复用；不得用宽松 CORS 或转发 Frappe Cookie 绕过。

反向代理应只为 `/employee/chat/index.html`、`chat.css`、`chat.mjs`、`client.mjs` 提供明确静态文件映射，不映射测试或源码目录；开启 JS mjs 的正确 MIME 类型。静态入口可匿名加载，但查询必须继续由员工 API 认证。设置 `Cache-Control: no-store`、`Referrer-Policy: no-referrer`、`X-Content-Type-Options: nosniff` 和限制到 self 的 CSP（default-src、script-src、style-src、connect-src；frame-ancestors none）。

共享 `/employee/sso` 成功后，当前 API 返回到 `/employee/status`；代理需要仅在 SSO 成功响应中把该固定 Location 映射到 `/employee/chat/`。不能重定向 status API 本身，因为界面需要它的 JSON。API 路由采用精确白名单，其余 Host API、WebSocket、配置和文件端点不得向员工开放。外层代理必须隐藏交接票据查询参数，不记录完整 SSO URL。

本次仅落盘界面与测试，不修改代理配置、共享身份服务或站点开启名单。共享登录入口仍默认关闭。上线前必须跑真实 HTTPS SSO、两个教师账号跨班级访问拒绝、退出及停用测试；本次模拟接口测试不能替代这些验收。

## 测试

从应用目录运行 `node --test tongjianyun/tests/shared_chat/client.test.mjs`。7 项测试覆盖员工专用路径、服务器游标、身份失效、取消不重试、非法响应、最终文本投影及退出清理。

浏览器测试：仅在测试机使用静态服务器提供 `tongjianyun` 目录，打开 `/tests/shared_chat/browser-test.html`。该页面模拟员工 API，直接加载生产 chat.mjs，检查登录启用、提问展示、HTML 文本化、新对话清理、退出禁用和退出清屏，显示 PASS 或 FAIL。测试页面不得通过生产代理发布。未登录布局另在普通 index.html 预览中验证。
