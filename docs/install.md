# 安装与升级

## 环境

膳食与食堂的可复现环境使用 Linux、Python 3.14、Node.js 24、Yarn 1、MariaDB 11.8 和 Redis。Frappe 与 ERPNext 使用 17 开发基线，Education 提供在园名册。三个上游版本固定在 [引导脚本](../scripts/bootstrap-bench.sh)。请用同一组提交在独立站点验证升级。

生产部署可以使用自己的 Bench 或 [Frappe Docker 自定义镜像](https://github.com/frappe/frappe_docker/blob/main/docs/02-setup/02-build-setup.md)。请把 Frappe、ERPNext、Education 和童健云一起构建，并使用生产环境的数据库、队列、HTTPS、备份和访问控制。

## 建立可交互的演示站点

从 [Releases](https://github.com/jerry317395616/tongjianyun/releases) 取得童健云代码。在 Linux 上准备 Git、Python 3.14（含 `venv`）、MariaDB 客户端、Redis、Node.js 24 和 Yarn 1。准备一个专用于演示的 MariaDB 库服务和 Redis 实例，默认地址为本机 3306 和 6379。

在童健云源码目录运行以下命令。脚本会创建 Bench 目录、安装固定版本的依赖、生成演示站点和虚构业务数据。

```bash
bash scripts/bootstrap-bench.sh "$HOME/tjy-demo-bench"
read -rsp '演示数据库管理员密码：' TJY_DB_PASSWORD
printf '\n'
export TJY_DB_PASSWORD
bash scripts/check-site.sh "$HOME/tjy-demo-bench"
unset TJY_DB_PASSWORD
```

可用 `TJY_DB_PORT` 和 `TJY_REDIS_URL` 指定演示服务的端口和 Redis 地址。为演示站点单独设置管理员密码并构建 Desk 资源。以下命令在安装了 Frappe Bench CLI 的环境下运行。

```bash
cd "$HOME/tjy-demo-bench"
bench --site tjy-demo.test set-admin-password
bench build
bench use tjy-demo.test
bench --site tjy-demo.test serve --port 8000
```

在启动 Bench 的机器上打开 `http://127.0.0.1:8000/desk`，以 `Administrator` 登录，按[十分钟演示](meal-demo.md)查看业务。演示初始化是显式启用的，且只允许在没有其他公司数据的站点执行。

## 安装到已有 Bench

先核对 Frappe、ERPNext 与 Education 版本。在 Bench 中安装 ERPNext 和 Education 后，将童健云固定到有发布说明的版本，再安装应用。

```bash
bench get-app --branch <童健云版本标签> https://github.com/jerry317395616/tongjianyun.git
bench --site <站点名> install-app tongjianyun
bench build --app tongjianyun
```

先在 ERPNext 中设置园所公司、原料仓、厨房仓、库存单位和采购基础资料。在 Education 中设置学年、学期、在读班级和学生的归班信息。在童健云中建立「食堂资质与场所档案」，把公司和仓库绑定到食堂，再开始编排周食谱。账户按园所和岗位分配角色及 User Permission。中英文界面依站点语言显示。

## 升级、备份和恢复

1. 记录四个应用的当前提交，使用 `bench --site <站点名> backup --with-files` 备份数据库和公私文件，单独保管站点配置、加密密钥、外部存储配置和自定义部署文件。
2. 把备份恢复到独立站点，切换童健云到目标发布标签，重建静态资源，再执行 `bench --site <站点名> migrate`。用测试账号复查周报、采购、台账和园所访问权限。
3. 核对记录数量和关键业务状态后，再安排生产升级。遇到需要回退的故障，切回旧版应用及固定依赖，使用该版本对应的升级前备份恢复。保留失败现场日志以便排查。
4. 如果旧站点仍装有 IONE Core，按 [迁移说明](meal-reports.md) 先转移模块归属并验证原单据。之后由管理员在已备份的站点卸载旧应用。

周食谱和相应报表可使用 Frappe 的下载功能。园所数据导出按角色授权执行，交付前请核对范围和字段。公开演示和外部问题反馈统一采用虚构资料。
