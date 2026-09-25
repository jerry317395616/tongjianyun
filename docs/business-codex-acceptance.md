# 共享 Codex 业务通道：实现与验收账本

2026-09-25。第六批候选，**尚未向生产普通账号开放聊天**。
范围是统一场景及 `/home/zyd/frappe` 全项目目标的一部分，不以首批工具代替全业务覆盖。

## 一套运行程序，独立的会话和授权

整个项目使用同一 Codex 版本，业务模块不各自安装或维护一个智能体。管理员项目操作
与普通用户业务操作按服务端授权分开；独立任务身份、会话与临时目录不是另一套产品。
生产既有管理员通道没有在本批改成教师执行器，普通账号没有获得 root 或项目文件权限。

共享运行目录 `/opt/tongjianyun-business-codex` 已由授权管理员安装：

- Codex 0.156.1，复用既有 ARM64 二进制，SHA256 为
  `876fe6bb5f7af7d1e4eda629be0d8ba042f6f24a7bb07475f6a995849f50c068`。
- 目录/可执行文件 root:root 0755，Python 运行文件 root:root 0644；校验父目录不可写、
  不含符号链接。四个文件先完整暂存并验哈希，再替换；原文件有私有备份。
- 安装没有修改 AppArmor、sudo 规则、生产业务数据、原用户角色或教师聊天开关。
- 此安装是单次、无业务启动器并发的部署。将来热更新需要与任务启动共享锁或不可变
  版本目录，不能把两次活动单元检查当作通用的并发更新协议。

## 当前候选能力

`business_agent_tools.py` 是可信业务代理，不是公开 RPC。绑定的 owner/site/task/mode
来自服务端；模型不能传 actor、任意方法、SQL、路径或忽略权限。每次执行重新检查任务、
账号启用和当前原业务权限；身份切换期间隔离 Frappe 请求缓存，完成或异常都恢复。

首批工具提供场景摘要、经过审计的业务视图、班级出勤/用餐读取和原服务保存。视图发布
只发送 selection 与摘要，浏览器仍须按当前身份重新读取。业务记录保留原生 revision、
完整名单、未来日期/锁定、修改原因、事务及审计；没有配置可信提交器时拒绝写入。

`DurableWriteLedger` 在模型不可见的私有 SQLite 中先保存写意图，再执行业务事务：
重复 call ID 或同一操作摘要不会重复执行；提交后回执丢失标为“不确定”，不能自动重写。
它不是跨 SQLite/Frappe 的分布式原子事务。重放回执也重新检查当前业务范围，旧名册
不直接返回。账户行锁覆盖业务提交，RR 旧快照或锁定读取冲突不能使停用账号继续写入。

`TaskProxy` 只提供精确的 `/tools/call` 与 `/v1/responses` 两个路径。每任务私有 Unix
socket 和高熵临时凭据；真实模型 API key 仅留在可信代理。模型出口固定，拒绝跳转、
通用代理、远程托管工具/文件、上游持久会话/提示词/条目引用；本地完整上下文可传递。
取消时撤销代理并关闭原始上游 socket，避免安静的 SSE 读阻塞漏停。

`native_sandbox.py` 以固定 UUID 启动原生 DynamicUser systemd 单元，再使用现有 bwrap
AppArmor 配置、独立挂载/PID/网络命名空间和 seccomp。没有宿主文件、数据库网络、
sudo/docker 组或管理员 HOME/环境继承；临时凭据只映射给本任务。禁止未隔离回退。
Codex 的内部 full-access 仅用于已完成的外层隔离环境，不是服务器全机权限。

`business_agent_tasks.py` 新增独立 business 任务/SSE 核心：
私有 SQLite 同事务保存任务、调度 outbox 和按任务递增的事件，队列固定为
`business_codex`。同请求去重、并发仅领取一次；只有可信队列观察明确不存在且尚未领取
时才可重新投递，不凭心跳过期或网页断线重投。完成必须观察对应执行已退出、写入已收尾，
模型自称完成或取消请求本身不代表任务停止。

工具在把某班/文档数据交给模型之前，必须先登记该任务的权限依赖；每次读取历史和
发送 SSE 事件都重新核对全部已登记范围。即使教师还有 G2，失去曾读取的 G1 后也不能
继续回放包含 G1 的旧答复。当前网页登录会话检查与任务权限分离：退出登录只关当前
SSE，业务账号或范围撤权才停止任务。权限描述符是可信适配器的契约，不是自动解析
全部 Frappe 权限的万能检查器；全部领域的读写适配仍需逐项接入。

新增 `business_chat.py`/`business_agent_service.py` 把该核心接入原生 Frappe 登录、CSRF、
独立 RQ 队列和 SSE。每用户提交使用 OS 持有的私有锁，同时只接收一项活动任务；
相同请求编号仍校验原消息/上下文摘要。队列回应丢失保留原任务与 outbox；网页仅重查
并派发尚未领取的同一任务，不重发另一份业务。历史事件每页100条连续读取，不跳到
任务最新游标而漏掉中间答复。公开接口没有 owner/site/命令/路径/执行模式覆盖参数。

前端根据服务端业务模式选择新接口，保留原管理员接口的权限边界；阶段消息按条更新，
`stopping` 持续占用任务槽，SSE `unavailable` 不伪造成失败。执行器或队列不可用时只
禁止新发送和重新派发；已安装的私有记录仍可查看、已运行任务仍可请求停止。
普通业务附件明确尚未接通，不会静默丢弃或转发给管理员。生产开关本批没有打开。

站点用户运行 `BusinessWorker`，复用同一安装的 Codex。原生启动器使用固定 Unix
控制协议，模型与浏览器不能提供 shell、环境变量、挂载或宿主运行路径。当前 worker
连接完整来源登记的 `classroom_read`、`scene_bootstrap` 和 `class_students_read`，
可发现当前可见班级、分页读取有效学生并发布名单/点名视图。名单排序复用原服务，
分页/扫描未完/权限额度耗尽不冒充全园总数或空名单；其余
已有工具代码尚不能直接冒充已接通的 worker 能力。可信启动器未安装/握手未通过、
独立队列无就绪 worker 或凭据不安全时，新任务不会被接收。

`business_agent_authority.py` 提供固定站点的真实 Frappe 授权适配。每次检查使用独立
Context/数据库连接，不沿用原请求的账号、缓存或旧事务快照；逐账号、班级、单据和
字段投影核权。浏览器 SID 仅留在可信内存，检查原 Sessions 表和 Redis 的存在/过期，
不自动续期登录。数据交给模型之前必须登记同一次原服务读取的完整来源集合；现已
提供出勤原始读取→来源登记→重新核权→最小输出的参考实现，其他工具仍须接入完整
来源集合，不能由模型声称“已核权”，也不能从剥离 ID 后的结果猜测来源。

`business_agent_events.py` 将真实 `codex exec --json` 输出转换为有限公共事件。仅发布
答复和固定阶段标签，不发布 reasoning、命令、工具 stdout、环境或错误正文。消息按
item ID 全文更新并去重，未结束行暂缓公开以防泄露分段凭据。实际 0.156.1 的
`thread.started → 前置 error 提示 → turn.started → turn.completed` 也已覆盖，运行提示
不是业务失败；反之模型文本“已完成”不是终态。事件持久化结果不确定时停止投影而非
盲目重发；浏览器恢复只回放已提交事件。

独立复核修复了持久任务恢复中的三个问题：已确认入队但尚未领取的消息丢失时，重新
观察真实队列后可以恢复；保留投递代际防止旧观察覆盖新投递；固定分页读取完成后再
核验当前权限，防止用较早的授权快照返回新登记范围的事件。未知队列状态、已领取或
已取消的任务均不自动重投。

后续修复了两个停止窗口：未绑定任务只有在已持久取消后，才可请求启动器原子封存；
已绑定但未尝试启动的租约在原控制锁内封存，迟到 start 永久拒绝。证明为独立
`never_started_and_sealed`，没有伪造退出码，不能判业务成功。已尝试启动但丢失句柄
仍为未知，不能直接当未执行。普通历史读取不凭时间猜测 pre-bind worker 已死亡。
有实际退出且租约已关闭的崩溃任务可恢复为失败/取消，不复活凭据、不重新调用模型。

### QA 启动器部署检查点

固定 `tgy-business-codex-qa-launcher.service` 已安装并启动，仅注册
`unified-business-acceptance.localhost` 与原站点 Unix UID/GID 1000。
daemon 源码 SHA256 `fb3ee03768bbcdf1bb3e893e9bd0cdecc553b7318b867714a3b16cdee353e87b`；
既有四个共享运行文件哈希保持不变。配置 root0600、状态 root0700；控制目录从0700改为
0711以允许连接 root:zyd0660 socket，身份仍逐连接按精确UID/GID/站点校验。
没有新增系统组、sudo/AppArmor规则、生产开关或开机启用；第一次管理员预检因既有
Redis认证URL的整串比较失败，改为固定scheme/loopback端点/端口/数据库校验后通过，
未修改或输出认证值。安装器默认不写，已存在不同文件拒绝覆盖；发布中途硬杀仍可能
保留完整文件的同inode暂存硬链接，需人工核对，不能宣传任意中断自动恢复。

每个新任务的固定 systemd argv 增加 BindsTo/After，启动器退出时PID1停止从属任务；
正常关闭并行回收、全局40秒上限。控制器重启不据单位消失编造成功结果。
非root prepare 已通过真实 socket 握手及原教师只读身份校验；实际worker执行另行记录，
这不代表HTTP/RQ/网页全链路或生产普通用户已开放。

班级发现/名单真实只读 QA `business-reads-readonly-70ae55dfdd/evidence.json` 的10项
通过：原生2人名单分页、原顺序、前探来源登记、跨班拒绝及外层上下文不污染。
单独创建的任务元数据在QA私有目录，不是生产业务写入。详见 `business-agent-reads.md`。

## 已有证据（区分真实业务与单元测试）

证据根目录均为专属 QA：
`/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925`。
站点、loopback DB/Redis、禁用调度器和合成 fixture 有精确守卫，不复制生产数据。

| 验收 | 结果与范围 |
| --- | --- |
| 教师业务工具 `3a31f7f43d` | 31 项。原教师角色，本班点名 1 Present/1 Unknown，午餐 1 就餐/1 不就餐；新连接回读，其他四餐 Unknown，日汇总未被冒充确认；重放不重复写审计；24 份其他记录/用户/名册保护摘要不变 |
| 双连接 MVCC `dc184f8f9b` | 11 项。新增无 DocPerm、未分班合成 System User；A 持账户锁时 B 原生停用超时；B 停用提交后 A 的 RR 普通读仍为 enabled=1，锁定当前读拒绝；真实 ledger 的 operation/commit 均未执行；25 份既有记录及教师身份摘要不变，新增账号最终停用 |
| 原生命名空间/系统调用 | 修复后 26 项真实 bwrap+seccomp 检查，含线程/子进程正常工作、宿主路径/数据库网络/命名空间/提权系统调用拒绝，以及只读 proc 与日志/hostname 系统调用拒绝；该专项身份为 zyd，**不是**真实 DynamicUser Codex 验收 |
| 核心工具单测 | 41 项，模拟业务服务而不是生产写入 |
| Linux 代理/去重单测 | 29 项，含真实本机 Unix socket 与安静上游取消，无真实模型请求 |
| Linux 原生运行器单测 | 24 项，构造和边界测试，不等于启动过真实 DynamicUser Codex |
| Linux 持久任务/SSE 核心 | 包含真实 SQLite 并发、持久回放、跨站点/用户/任务游标拒绝、批量权限依赖原子登记、范围撤权、登录过期、取消收尾和文件权限；不是实际网页或 Codex 执行 |

前一实现检查点联合后端回归 473 项、前端 127 项通过；不作为本轮新增接线的验收总数。
Windows 的运行器 HTTP 测试明确跳过，
其实际部署目标是 Linux；不能把跳过计作通过。命名空间专项的证据是 SSH 执行 stdout，
不是声称存在另一份私有 JSON 报告。

前一检查点部署工具联合单测 67 项通过，使用实际原生执行器的 `/usr/bin/python3`。Frappe 的
Python 3.14.6 环境没有 `os.memfd_create`，不能作为该原生执行器解释器；测试发现这个
运行时差异后没有增加无 seccomp 回退。

### 首次真实启动：失败且已清理，不算模型验收通过

2026-09-25 21:21（服务器本地时间），prepare-only 通过：共享运行文件/安装回执匹配，
模型凭据文件权限符合约束，独立只读 Frappe 请求读取到本班合成学生 2 人。
随后一次真实任务 `11965c0c-9d52-41a4-a69b-0ef36d79709a` 在 bwrap 启动阶段退出 1。
`model_calls=0`、`tool_calls=[]`、视图事件 0；不能称为已经调用了模型或驱动了页面。

任务报告 `live-codex-11965c0c-9d52-41a4-a69b-0ef36d79709a.json` 为 root:root 0600，
一次性 marker 保留。凭据、输入目录和 DynamicUser 运行目录均已移除，输出读取线程
已退出。独立 `systemctl show` 核验对应精确 UUID 单元为 not-found/inactive；systemd
日志确认启动后一秒退出。没有业务写入、生产配置变更或自动重试。
下一步先使用无模型、无凭据、无数据库的同配置 DynamicUser 探针定位 bwrap 差异；
诊断修复并重新核对旧进程终态后，才允许显式复核的新一次只读尝试，旧报告不覆盖。

无模型诊断 `cf4741e7-417a-4088-b804-49265f26cb93` 取得具体错误：
`bwrap: Can't mount proc on /newroot/proc: Operation not permitted`。随后固定 10 组
DynamicUser 对照仅改变临时单元的相关 `/proc` 保护选项：单独或两项调整均失败；
同时将 tunables/logs/hostname 的外层子挂载移除时成功，ProtectProc=invisible 可保留。
成功探针 `a2452564-9e4f-48f3-a3f4-22873408e679` 的 UID=64554、NNP=1、Seccomp=2、
capabilities=0、宿主 home 不可见、单任务 socket/合成凭据挂载正常；全部探针均清理。
该结果证明问题在保护层组合，并非须关闭主机 AppArmor 或转成 Docker，也不是模型兼容
验收。修复将保留独立 PID/proc，在最终 bwrap 内落实只读 proc 与相关系统调用限制。

修复已安装，manifest SHA256：
`9053bfef64ea078151b54e3f32cc1b48ea4a1cd03119dc596518eaed8fcd5cd5`。
正式运行配置保留 `ProtectProc=invisible`，将冲突的 tunables/logs/hostname 外层保护
移到最终只读 `/proc` 和 seccomp；没有改主机 AppArmor、用户命名空间开关或 sudo。
固定配置无模型复测 `dd17259f-5bdb-4d7c-8b1c-6758a5658728` 退出 0：DynamicUser
UID 62755、NNP=1、Seccomp=2、capabilities=0、proc 只读、宿主 home 不可见，精确单元
及输入均已清理。这次不是参数矩阵覆盖，也没有发起模型请求或接入生产教师聊天。

真实模型失败重试采用显式旧任务 UUID 与固定复核原因；检查旧任务的进程、单元、
目录、Redis 和清理证据均已终止后，才分配新 UUID。原失败报告不改写，一次性 marker
完整归档，持有私有锁防止并发启动。普通无参数运行仍不能自动重试。

### 真实隔离 Codex / DeepSeek 只读链路通过

显式复核旧失败任务后，新任务 `fd55b522-70da-486e-9ddb-e563424aa86f` 完成，退出码 0。
真实模型请求 4 次，依次调用 `scene_bootstrap` 和 `business_view(class_students)`，
从原业务读取合成班级 2 名学生，发出 1 个视图请求；保护业务摘要不变。没有业务写入。
宿主独立核验实际 Codex 进程 PID 4012771 的二进制 inode 与受审运行文件一致，
DynamicUser UID 65502，不是 root 或站点所有者；NNP=1、Seccomp=2、capabilities=0。
模型执行的命名空间探针同时通过，不能仅凭模型自己报告替代上述宿主核验。

证据 `live-codex-fd55b522-70da-486e-9ddb-e563424aa86f.json` 由 QA 脚本保存为私有文件，
记录源码/运行文件哈希、有限事件类型、工具与清理结果，不存原始推理、命令、stderr 或密钥。
精确单元已 not-found/inactive/dead；临时 token、输入目录、DynamicUser 目录均移除，
JSONL 读取线程退出且清理错误为空。主线程另行只读查询 systemd，确认同一 UUID 单元已退出。
原失败证据和 marker 归档保留，没有用新结果覆盖失败报告。

该验收证明“隔离原生 Codex → 固定模型代理 → 当前教师只读权限 → 真实业务工具 →
视图请求”可工作，**不证明浏览器已展示、持久 SSE 已接入或普通账号生产聊天已开放**。
本次运行仍是独立管理员启动的 QA，不是将管理员执行器交给普通用户。

### 显式取消：保留原误判报告，独立证据复核通过

真实取消任务 `f7fbb769-95bb-4293-be40-998599415585` 在实际隔离 Codex 运行、真实
`scene_bootstrap` 返回后发出停止。原检查把 `systemd-run --wait` 返回0误当成没有
取消，故原报告 `cancellation_check_passed=false` 保持不变。没有重跑这个业务任务。

独立只读复核报告
`live-codex-cancel-review-f7fbb769-95bb-4293-be40-998599415585-531f4d2644.json`
18项通过：同 boot/machine/invocation 的可信 PID1 记录严格按单调时间出现 started →
stopping → deactivated → stopped，停止 JOB_ID 一致；完整 JSONL 没有正常终态；实际
Codex PID、cgroup、unit、输入及临时目录都不存在，业务保护摘要未变。日志中的 kill
警告没有被忽略为成功，最终清理另有实际资源观察。原报告前后 SHA256 均为
`57c50498db376b7e4ed7a04066c291db521ca3c2112c625c60406bd343ee9e01`。

`check_live_codex.py` 的后续取消判据现复用该完整证据链，不再要求客户端非零退出。
评估器20项、live guards37项在 Windows/Linux 均通过；新判据未重跑真实模型验收。
执行复核使用既有授权管理 wrapper；wrapper 自身有模型调度，但没有启动新业务 Codex
测试或更改生产/业务记录。该证据不代替新 HTTP→RQ→worker→浏览器链路验收。

### 完整出勤读取来源

私有 `source_observer` 从同一出勤查询捕获全部 Student Attendance/Leave 记录，包含
较早记录，原 HTTP 参数和默认返回不变；权限来源不再错误地只取最近记录。
同一学生旧记录撤权也阻止历史回放。批量登记减少重复授权查询，不移除任何依赖。
独立只读 QA `business-authority-readonly-f18d9d333b.json` 12项通过，未创建会话或改角色；
具体源码哈希与条件见 `business-agent-authority.md`。

MVCC 第一轮 `367acd6336` 保留为失败证据：QA 的 `innodb_snapshot_isolation=1` 下，
旧快照的锁定读返回 1020 冲突而不是 enabled=0。修正为该冲突直接拒绝权限、不局部重试，
再用独立新 fixture 得到上表结果。失败样本未删除，其合成账号也最终停用。
这些报告包含当时模块哈希；后续补丁的单测不能冒充旧报告已经使用了最新源码。

## 实时输出与超时的准确边界

### 非 root 持久任务 worker：真实执行通过

任务 `a7b97e55-7298-44e1-b21d-fce2c74f09bc` 使用现有普通教师身份，由站点 UID1000
运行 `BusinessWorker`，经已安装的 QA daemon 启动共享隔离 Codex。真实模型请求2次，
`classroom_read` 回读准确班级/日期的2名合成学生：Present=1、Unknown=1；登记8项
权限来源，持久事件包含阶段输出、消息、视图及终态。任务状态 completed，daemon
确认退出0、能力租约关闭；再次投递同任务不启动第二次模型。保护业务摘要前后相同。

私有证据：`business-worker-live-a7b97e55-7298-44e1-b21d-fce2c74f09bc.json`，包含实际
源码哈希与上述计数，不保存密钥或原始模型内部输出。主线程另查精确 UUID 单元：
not-found/inactive/dead、MainPID=0、ControlGroup为空；QA启动器及原生产三服务active。
本次没有创建业务记录、改角色或启用生产普通聊天。

执行前修复真实QA目录超过AF_UNIX路径长度限制：Linux逐组件O_NOFOLLOW固定目录FD，
用短 `/proc/self/fd/<fd>/proxy.sock` 绑定，传给daemon的规范路径不变。关闭时按固定目录
与创建socket的inode清理；不把同UID恶意并发替换下的stat/unlink称为原子操作。
候选Linux后端716项、部署/运行器170项、前端159项通过；测试集合分层，不相加作为业务覆盖率。

这是 task store→worker→daemon→模型→真实工具→持久事件的闭环，**未经过HTTP提交、RQ
消费、SSE网络或浏览器渲染**；不能据此宣称普通用户网页端到端或业务写操作验收完成。

`codex exec --json` 产生逐阶段 JSONL，可信服务负责过滤、保存及向网页 SSE 转发。
[官方命令说明](https://learn.chatgpt.com/docs/developer-commands#codex-exec)。
代理连接/请求头有 15 秒边界，建立后的流读取不设任务总时长上限。停止由任务撤权及
明确取消驱动，不能因为浏览器断线就重复启动业务。

Codex 本身仍有默认 `stream_idle_timeout_ms=300000`；现有源码把 0 解释为 0 毫秒，
不是禁用。当前没有设置 0，也不宣称“端到端永不超时”。
[官方配置说明](https://learn.chatgpt.com/docs/config-file/config-reference)。
网页恢复应回放持久事件和核对任务，而不是重试已有写入。

## 下一步及未完成范围

1. 已完成真实 DynamicUser Codex 只读运行、模型工具调用、JSONL 事件、视图请求及正常
   退出的 cgroup 清理，以及活跃真实模型显式取消的独立复核；仍须新网页链路的撤权
   中断、进程异常恢复及持久事件恢复验收。
   `check_live_codex.py` 默认只准备，`--run` 一次性保留证据；失败必须检查原进程和证据，
   不能因观察超时重复运行，已通过任务也不能自动重跑。
2. 新 HTTP/独立队列/worker/SSE/前端恢复已有候选代码；固定原生启动器已仅在QA安装，
   非root worker真实闭环通过。实际网页链路、浏览器左侧真实显示/回执仍须完整验收；
   生产普通账号入口在此之前保持关闭。
3. 私有附件的原权限复制与内容解析；当前模型请求明确没有附件能力，不虚称已可上传。
4. 按角色补齐所有业务适配器和原生完整流程，包括财务、资产、HR、教育等状态链；
   入口目录、首批点名核餐、单测通过都不代表全部业务已验收。
5. 未知业务保持真实方案/预览/确认/原生创建及再发现能力，并继续复杂源码扩展验收。
   普通用户可以提出需求，结构启用与部署按管理员授权处理，不继承管理员会话。
6. `/home/zyd/frappe` 内独立服务须分别核实认证、用途和接口，不能把目录索引当业务接入。

本账本的本批候选未向生产普通用户开放，不替代完成审计；Git提交及联合回归见最新检查点。
