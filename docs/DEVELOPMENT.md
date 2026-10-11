# 开发与运行

仓库按 Windows 便携运行包结构组织：`App/` 是服务与课堂源代码，`launcher/` 是 C# 启动器和 Python 控制器，`licenses/` 是许可清单。Python 运行环境、大型模型、预编译上游 Web 资源和角色资源在 Release ZIP 中，不放入 Git 历史。

## 基于发布环境开发

1. 下载同版本 Release ZIP 并完整解压到一个独立开发目录。
2. 把仓库中的 `App/`、`launcher/` 覆盖到开发目录相应位置，不要覆盖到正在运行的副本。保留 ZIP 内的运行环境、模型及角色资源。
3. 双击 `Alex-Learning.exe` 启动。编辑 `App/deployment/study.html`、`study.js`、`study.css` 或 `import-queue.js` 后刷新页面；改 Python 服务后停止并重新启动。
4. 所有便携副本默认使用同一个 Windows 用户资料目录；测试教材、迁移和解析时请用临时 `StudyStore(directory)`，避免污染个人资料。不要同时运行两套便携服务。

在开发副本的 `App/` 中可运行：

```powershell
.\.venv\Scripts\python.exe -m unittest deployment.test_import_queue deployment.test_study deployment.test_learning deployment.test_gateway
node --test deployment/test_import_queue.cjs deployment/test_voice_turn.cjs deployment/test_study_bridge.cjs
```

JavaScript 测试需要自行安装 Node.js。OCR 测试使用 Windows Arial 字体。第三方云服务测试主要使用隔离模拟客户端，不代表每一家付费接口都经过实账号测试。

## 关键代码

- `App/deployment/study_store.py`：教材、解析、检索与课程；`study_routes.py`：持久导入队列和教材 API。
- `App/deployment/import-queue.js`：文件夹递归、逐个上传、暂停和重试。
- `App/deployment/learning.py`、`learning_routes.py`：课后整理、FSRS 与进度；`learning-ui.js`：界面。
- `App/deployment/providers.py`、`plan_gateway.py`：模型连接和流式回复；不要提交真实凭证。
- `App/deployment/voice_server.py`：本地语音服务；`App/frontend/study-bridge.js`：角色页面桥接。
- `launcher/Launcher.cs`、`bootstrap.py`：窗口启动器和本地进程管理。

`launcher/build_portable.py` 保留了原开发布局下的打包实现，它依赖原布局、预先安装的双 Python 环境和固定模型文件，**不能在这个精简仓库直接运行并凭空生成全部依赖**。现阶段复现运行请使用上面的同版本 Release 环境；完全从零自动构建尚未提供。上游 Web 前端源码见 README 中的项目链接。

提交代码前检查 `git diff --cached`。不要提交 `runtime.json`、`conf.yaml`、`.env`、密钥、数据库、教材、语音录音或日志。
