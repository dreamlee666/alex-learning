# 学习功能与参考项目（2026-10-10）

## 本次实现

- AI 来源：ChatGPT 原有授权、DeepSeek、通义千问/百炼、豆包/火山方舟、Ollama、本机或其他 OpenAI Chat Completions 兼容接口。第三方需自行填写准确模型 ID；未逐一使用付费密钥实测。
- 当前课次下的中英文输入和老师回复自动存入本地 SQLite。旧版本对话不会被猜测归到某一课次。
- 课后整理：依据最多 8 段本课教材与最近 30 条本课对话生成总结、3 张回忆卡和 2 道应用练习；无对话时应明确标注教材预习。
- 查看参考答案前先独立作答；AI 点评可选。评价“忘记/困难/记得/轻松”时保存答案与反馈并安排下次复习。
- FSRS 6.3.2 默认记忆模型、90% 目标保持率、关闭调度随机扰动；未训练个人参数。该目标是算法设置，不是成绩保证。
- “忘记/困难”进入薄弱点，再次自评记得或轻松后移出；自评回忆率与课次完成率分开显示。
- 14 天学习活动、连续学习天数、近 7 天顺利回忆率（自评记得/轻松所占比例）、作答历史、按课程导出 Markdown。界面一次最多显示 100 张卡片，导出包含全部卡片和全部作答记录。
- 原有整节课 1/3/7/14 天复习与新增卡片级 FSRS 是两个层级，前者回顾课文，后者练习具体知识点。

## GitHub 参考

- [Py-FSRS](https://github.com/open-spaced-repetition/py-fsrs)：直接使用 PyPI fsrs==6.3.2，MIT。原许可保留在 fsrs-6.3.2.dist-info 中。参考官方 Card、Scheduler、Rating、ReviewLog 序列化接口。
- [Anki](https://github.com/ankitects/anki)：参考先回忆、翻面、自评、重新排期的交互。没有复制 Anki 源码。
- [OpenMAIC](https://github.com/THU-MAIC/OpenMAIC)：参考围绕教材生成互动课堂与测验、保留学习结果的流程。没有引入其服务或复制其源码。

## API 文档

- https://api-docs.deepseek.com/
- https://help.aliyun.com/en/model-studio/first-api-call-to-qwen
- https://docs.ollama.com/api/openai-compatibility
- 火山方舟地址应以使用者控制台提供的接口与接入点为准。

## 使用

声音与账号设置 → AI 来源 → 保存 → 测试老师回答。

每日学习计划选择课次 → 上课 → 标记学完 → 课后整理与练习 → 生成总结 → 填写自己的答案 → 查看原文与参考答案 → 可选 AI 点评 → 回忆自评。

新对话后可“更新总结”，已有卡片及其复习历史保持。数据保存在当前用户的本机学习数据库；分享 ZIP 不包含账号、教材或个人进度。
