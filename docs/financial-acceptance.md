# 财务能力验收：单币种费用采购应付、支付与冲回

日期：2026-09-25。这里只验收一个真实原生应付案例，不等同于“全部财务已覆盖”。

## 已验证的案例

在专属隔离站点 `unified-business-acceptance.localhost` 中，复用原生 ERPNext 的单据、映射器、过账、付款分配与撤销逻辑：

`非库存费用采购发票 → 提交 → 原生付款单 → 全额支付 → 取消付款 → 取消发票 → 新连接回读`

本案例为全新合成供应商、非库存服务 Item，`8 × 12.50 = CNY 100.00`。费用记入已存在的 `Administrative Expenses`，应付记入已存在的 `Creditors`，支付使用已存在的 `Cash`。没有新建科目，没有税额、汇差、库存动作，也没有向银行或供应商发送真实款项。

为避免以负现金演示支付，测试先通过原生 Journal Entry 给合成场景增加100元测试资金，借记现金、贷记既有 `Opening Balance Equity`；主流程完成后再原生取消该凭证，现金回到执行前基线。这是测试夹具，不是额外财务功能的完整验收。

## 结果和证据

最终代码完整运行 `f70a9ac11d`：**24项集成断言通过**；独立本地守卫单测2项通过。此前 `df9f997daa` 也通过24项；最终版额外保留了取消发票后的原始未付字段与反向GL证据。

服务器证据：

`/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925/payables-lifecycle-f70a9ac11d.json`

保留的合成凭证：发票 `ACC-PINV-2026-00004`、付款 `ACC-PAY-2026-00004`、测试资金凭证 `ACC-JV-2026-00004`，均已由原生流程取消。供应商 `QA Payables f70a9ac11d`、Item `QA-SERVICE-f70a9ac11d` 和无权限测试账号保留供核查。

| 阶段 | 实际核验 |
| --- | --- |
| 发票草稿 | 100元计算正确；无GL、无库存流水 |
| 发票提交 | 费用借100、应付贷100，总账平衡；供应商精确匹配；未付100；PLE关联本发票 |
| 付款草稿 | 原生 `get_payment_entry` 正确带入供应商、现金/应付账户与100元本发票分配；尚未结清或过账 |
| 付款提交 | 应付借100、现金贷100，总账平衡；未付0、未分配0、差额0；对应发票PLE净额0 |
| 再次全额付款 | 原生校验拒绝；原分配及未付余额保持不变 |
| 取消付款 | 未付恢复100；付款无有效GL或有效分配PLE；现金恢复测试注资后的金额 |
| 取消发票 | 发票已取消；本发票无有效GL/PLE；无库存流水 |
| 取消测试资金凭证 | 现金回到执行前基线；无有效资金凭证GL |
| 新连接 | 重新读取取消状态、有效GL/PLE和现金余额，与预期一致 |
| 权限反例 | 无业务角色用户不能读发票、创建付款单或打开付款业务视图 |
| 业务视图 | 后端返回的原生表单路由精确指向本发票、本付款单 |

本批成功操作使用隔离站点既有 `Administrator`，没有为了通过测试临时添加广泛角色。无角色用户反例不等同于普通会计/出纳角色、复核分工或单位间权限的完整验收。

## 两个不能误判的原生行为

### 取消发票不一定要求先取消付款

本站 `Accounts Settings.unlink_payment_on_cancellation_of_invoice = 1`。原生 `AccountsController.on_cancel` 会调用 `unlink_ref_doc_from_payment_entries`，按配置解除付款分配。因此不能硬编码“已付款发票一定不能取消”，也不能把这种原生设置行为说成安全漏洞。

初次尝试 `5dc0cb6230` 在这个额外负向断言上停止，是测试预期错误，不是本批主流程故障。事务回滚后已只读确认其发票 `ACC-PINV-2026-00001` 仍为已提交、未付0；这一首次测试的供应商/发票/付款/资金夹具未删除，保留作为调查证据。完整主流程按本任务指定的“先取消付款、再取消发票”顺序执行，未改变任何财务设置。

### 已取消发票的 outstanding_amount 不能单独当成未付债务

完整运行后，已取消的 `ACC-PINV-2026-00004`：`docstatus=2`，单据上的 `outstanding_amount` 仍保留100；但原生有效GL和有效PLE均已消除。不能为了让展示归零而手改这个字段，也不能将已取消发票的历史字段计入“现在欠供应商多少钱”。业务展示必须同时核对单据状态与有效付款/会计流水，未付汇总至少排除已取消单据。

## 隔离与可重跑

脚本：`deploy/unified_business/check_payables_lifecycle.py`。

固定校验以下条件，任何一项不符立即停止：

- 精确专属 sites 路径、站点名称和 `unified_business_acceptance=1`。
- 数据库 `127.0.0.1:23316`，数据库/用户均 `tgy_blueprint_qa`，无本机数据库 socket。
- 三个 Redis 地址均 `127.0.0.1:23379`；scheduler暂停；非developer mode。
- 在连接前清除数据库/Redis环境覆盖，并再次检查Frappe有效配置。
- 只选择既有 `QA Meal` 合成公司；每次使用独立随机编号创建新供应商、Item和凭证。

原生API可能内部提交，因此脚本不承诺失败时能清空全部夹具。最终版本会把中断时已通过检查、对应合成单据和失败步骤写入独立 `payables-lifecycle-incomplete-*.json`，保留证据，不自动删数据。不启动worker、不修改生产站点、原生ERP代码、GL或余额字段，不用SQL写财务结果，不调用外部支付。

运行方式：

```bash
UNIFIED_BUSINESS_SITES=/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925/sites \
UNIFIED_BUSINESS_SOURCE=/home/zyd/frappe/remote-workspace/unified-business-20260925 \
/home/zyd/frappe/native-bench/env/bin/python \
/home/zyd/frappe/remote-workspace/unified-business-20260925/deploy/unified_business/check_payables_lifecycle.py
```

加 `--inspect` 仅查看合成公司的科目及已保留测试发票，不创建业务记录。

## 覆盖边界

本批是后端真实原生会计生命周期、查询和精确业务视图选择验收，**未通过浏览器实际录入/点击验收**，也未验收SSE刷新后的视觉结果。不是全财务完成证明。

未覆盖：应收收款、税务与发票合规、外币汇兑、部分支付/预付款/退款、跨单据复杂核销、银行对账、库存采购估价及暂估、资产折旧、工资、期间结账、多公司权限、普通会计/出纳分权、多人并发与真实银行支付。每一项需独立原生业务案例，不可由本案例推断已实现。
