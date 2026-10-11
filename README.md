# Alex Learning · 虚拟学习课堂

用自己的教材，与虚拟老师一问一答地学习。Windows 本地运行，支持连续语音、同步小黑板、课程计划、课后整理和间隔复习。

**[下载 Windows 便携版](https://github.com/dreamlee666/alex-learning/releases/latest)** · [批量导入说明](App/deployment/IMPORT-GUIDE.md) · [开发说明](docs/DEVELOPMENT.md) · [隐私与数据](PRIVACY.md)

软件免费下载。每位使用者配置自己的模型账号、API 或本机 Ollama；云端服务可能收费，不提供共享账号或免费 API 额度。仓库用于发布源码与下载包，课堂运行在你的电脑上。

## 三步开始

1. 在 Releases 下载 `Alex-Learning-Windows-0.3.1.zip`，**完整解压**，双击 `Alex-Learning.exe`。无需另装 Python；首次启动会联网下载并校验少量运行组件。
2. 在「声音与账号设置」选择 AI 来源，填写模型配置并测试回答。支持 ChatGPT 授权、DeepSeek、通义千问/百炼、豆包/火山方舟、Ollama 和其他兼容接口。授权与可用额度以各服务返回结果为准。
3. 打开「教材书架」导入教材 → 「每日学习计划」创建课程 → 选择课次开始对话。允许麦克风后，点一次录音即可连续交流；也可以直接打字。

适用 Windows 10/11 x64；建议至少 8 GB 内存，语音默认在 CPU 上运行。解压后的运行环境约 2 GB，首次下载、教材与 OCR 还需要额外磁盘空间。

## 可以怎样学

| 环节 | 功能 |
| --- | --- |
| 教材 | PDF（含扫描 OCR）、DOCX、TXT、Markdown；整文件夹及子文件夹、拖拽、批量排队、重复识别与失败重试 |
| 计划 | 自定义学科、教学语言、基础和每日时长；分课程保存，SQE 与英语是可选模式 |
| 上课 | 苏格拉底式逐步追问；连续语音自动发送；可选转写校对；原文、页码与讲解同步显示 |
| 课后 | 根据教材和本课对话生成总结、回忆卡和应用练习，先作答再看答案 |
| 复习 | FSRS 卡片排期、薄弱点、作答记录、活动与进度统计、Markdown 导出 |

导入不再限制每次五本；单本最多 50 MB，PDF 最多 1500 页。大批扫描书需要等待本机 OCR。导入是建立可检索的教材库，不会重新训练底层模型；往书架添加教材后，需要在新课程计划中选择它们。

![批量教材导入测试](docs/images/import-batch-demo.png)

![学习进度演示](docs/images/learning-progress-demo.png)

以上截图使用独立功能测试数据。

## 模型和网络

- 兼容接口使用 OpenAI Chat Completions 协议；模型 ID 或火山方舟接入点 ID 请按服务商控制台填写。第三方预设未逐一使用付费账号实测。
- Ollama 需要自行安装、下载并启动模型，配置本机地址和模型名称；此包不包含本地对话大模型。
- 英语语音合成和 Whisper 语音识别在本机执行；中文语音使用联网 Edge TTS。选用云端模型时，课堂问题、相关教材片段和对话会发送给选定服务。
- ChatGPT 授权是否可用取决于账户及官方授权流程；不保证所有订阅都能使用。

## 版本与排错

当前版本 **0.3.1**：新增整文件夹、子文件夹及批量教材导入，串行解析队列、失败重试、去重和中断恢复。验证：43 项 Python 测试、12 项 JavaScript 测试通过；页面实测 12 本一次入库、重复 12 本不重复建库。

端口为 `32193 / 32194 / 32195`。启动后学习空间是 `http://127.0.0.1:32194/study`。已有同一软件运行时会复用；其他软件占用端口时需要自行调整或关闭对应软件。

分享时请转发 **Releases 原始 ZIP**，不要压缩用过的软件目录。账号、教材、进度和会话的存放位置见 [PRIVACY.md](PRIVACY.md)。程序未做代码签名；校验值见 `SHA256SUMS.txt`，请核对下载来源。

## 许可与致谢

基于 [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) 及其 [Web 前端](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web)。课堂与启动器代码采用 MIT，保留原作者声明。角色、SDK、模型和依赖分别适用各自许可，**并非全部 MIT**；详见 [THIRD_PARTY.md](THIRD_PARTY.md) 和 `licenses/`。

使用固定的 Live2D 原创示例 Mao，不提供人物扩展接口。英语声线使用 Kokoro 混音与音色调整，与 Neuro-sama 无关联。没有附带商业 SQE 教材、个人教材或真实用户学习记录。

This content uses sample data owned and copyrighted by Live2D Inc. The sample data are utilized in accordance with terms and conditions set by Live2D Inc. This content itself is created at the author's sole discretion.

复习调度直接使用 [Py-FSRS](https://github.com/open-spaced-repetition/py-fsrs)；教学交互参考项目和区别见 [学习功能与参考](App/deployment/LEARNING-REFERENCES.md)。AI 生成内容、练习和学习统计不构成官方考试评分或成绩保证。
