# 参与童健云

欢迎参与业务设计、中文翻译、安装文档、测试和代码。可以在 [GitHub Issues](https://github.com/jerry317395616/tongjianyun/issues) 搜索现有问题或提交新反馈。

- 报告问题时请提供童健云、Frappe 和 ERPNext 版本，写出复现步骤及预期结果。使用虚构园所和人员资料，截图需遮盖账号和站点敏感信息。
- 提出改进时请说明使用角色、当前操作和希望达到的结果。涉及采购审批、账务或权限的改动，请一并说明影响的角色和单据状态。
- 向 `develop` 提交 PR，附上验证步骤。界面改动可附演示截图，涉及权限、数据迁移或业务状态的变更请附相应的验证结果。

```sh
python -m pip install -e . pytest
python -m pytest -q tongjianyun/tests
node --test tongjianyun/tests/*.test.cjs
```

在 Frappe 站点内验证新行为和原有业务，具体环境见[安装文档](docs/install.md)。童健云使用现有的 Frappe 权限和 ERPNext 单据。优先通过应用的钩子、DocType 和表单布局实现扩展。

涉及账号越权、数据泄露和漏洞的报告请走[安全渠道](SECURITY.md)。
