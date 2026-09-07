# Harness 前端基础服务修复

现有 native-bench-business overlay 禁用了 ui-settings。但当前 ui-settings 提供 settingsScope，locale、theme、conversation 等基础插件依赖此服务，导致浏览器出现 “Failed to load plugins / 14 entries did not activate”。

本目录最后一层 overlay 仅恢复 ui-settings 基础服务；ui-settings-general、ui-settings-models、ui-settings-plugins 等页面仍沿用禁用设置，typert-gateway 白名单、写入拒绝及工具限制均不改变。

run_harness.py 沿用现有部署启动器的令牌发布与日志脱敏逻辑，只增加最后一层 overlay。通过 ione-harness.service.d/20-ui-foundation.conf 指向这个受版本控制的启动器，不修改 Harness 上游源码或旧启动器。不启用共享员工接口，也不变更 Frappe DocType。

重启此服务会更新启动票据，浏览器可能需要从 Frappe 桌面重新进入。回退时移除该独立 systemd drop-in，daemon-reload 后重启原服务；原启动器文件保持原状。
