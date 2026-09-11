# 园区数字孪生 · 空间示意版 01

入口：业务工作台「园区数字孪生」，或 `/tongjianyun-campus`。

本版为 Three.js 可交互空间底座，不是已接入设备的实时数字孪生系统。
照片及视频提供外观依据；尺寸、楼栋连接、楼下通道位置、屋顶及内部房间未测绘。
模型坐标只是示意单位，不提供米制比例尺、实际方位或消防路线。
未采集或展示学生身份、定位、考勤、实时视频；不模拟任何业务状态。

## 功能与边界

- 鸟瞰 / 院内 / 俯视、鼠标或触摸旋转缩放、复位、标注、主动开启自动环绕、全屏。
- 五个区域可从模型或侧栏选择；侧栏支持键盘访问。
- 窗口自适应、移动端上下布局、WebGL/资源错误提示、后台不渲染、离开页面释放资源。
- 禁止作为施工或安全疏散依据。楼下通道有视频证据但位置没有确认，单独标注。
- 登录检查在 Frappe 文件路由的 `get_context` 执行；仅启用的 Administrator 或
  Tongjianyun Business Operator 可打开，不缓存用户页面。
- JS 模型及 Three.js 库为公开静态资源，不包含私人照片、人员数据或监控凭据。
- 本版无数据库写入、无 DocType/Custom Field/Property Setter/Page 元数据创建。
  不运行 migrate，通过应用 www 文件路由交付。官方应用不变。

## 依赖

Three.js **0.180.0**，npm 官方包 `three@0.180.0`，MIT license。
从 npm 包原样复制 build/three.module.js、build/three.core.js、
examples/jsm/controls/OrbitControls.js、LICENSE 至 public/campus/vendor。
运行时全部同源加载，无公共 CDN、外部网络依赖。
上游包 shasum: b930cabfb524f6d36bf63e874b4d866888b50487。
更新时四个文件一起更新并执行浏览器回归，不混用版本。

## 后续真实孪生

先校准建筑尺寸与区域编号，再将真实设备/班级绑定到确认过的区域。
任何设备状态或业务数量必须由权限约束的现有业务服务读取，未知显示未接入，
不能用动画和静态数字充当事实。需要新结构时另行请求明确授权。

## 验证

`tongjianyun.tests.test_campus_viewer` 检查访客、停用用户、角色和管理员访问。
浏览器检查 WebGL 初始化、三个视角、五个区域、标注、环绕、复位、窄屏溢出。
部署只同步 www、public/campus 和工作台入口，清缓存并重载 web 进程；不迁移结构。
