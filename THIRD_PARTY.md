# 第三方代码、模型与角色

| 组件 | 来源 | 许可说明 |
| --- | --- | --- |
| 基础虚拟角色服务 | https://github.com/Open-LLM-VTuber/Open-LLM-VTuber | MIT，保留 Yi-Ting Chiu 版权声明 |
| 上游 Web 前端 | https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web | MIT；仓库保留自定义 bridge，预编译前端随运行包提供 |
| Kokoro 英语 TTS | https://huggingface.co/hexgrad/Kokoro-82M | Apache-2.0，版本与哈希见运行包 provenance |
| Whisper / faster-whisper | https://github.com/openai/whisper / https://github.com/SYSTRAN/faster-whisper | MIT，固定模型版本见 `App/deployment/asr-model-provenance.json` |
| FSRS | https://github.com/open-spaced-repetition/py-fsrs | MIT，版本 6.3.2 |
| Live2D Mao 与 Cubism Core | https://www.live2d.com/en/learn/sample/niziiro-mao/ | 专用许可，不属于 MIT。见 `LICENSE-Live2D.md` 与下方链接 |

完整依赖清单和运行组件说明见 [licenses/THIRD-PARTY.md](licenses/THIRD-PARTY.md)、[模型说明](licenses/MODELS.md) 和运行包内各 `*.dist-info`。

Live2D 官方条款：[素材许可](https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html)、[SDK 发布许可](https://www.live2d.com/en/sdk/license/)、[Core 专用许可](https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html)。当前版本固定 Mao 角色，不提供导入扩展角色的功能。公开下载不代表角色素材可任意重新授权；若改变商业主体、用途或扩展能力，需按官方条款重新核对。

This content uses sample data owned and copyrighted by Live2D Inc. The sample data are utilized in accordance with terms and conditions set by Live2D Inc. This content itself is created at the author's sole discretion.

没有重新分发 Mao 原有音频。本项目不是 Live2D、Neuro-sama、SRA 或任一模型服务的官方产品。
