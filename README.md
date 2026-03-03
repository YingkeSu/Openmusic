# OpenMusic / Piano for AI

AI 自动编曲 MVP（文档 + 可运行本地服务实现）。

## 已实现能力（对齐文档 V1.0）

1. 60 秒时长上限校验（超限返回 `1002`）。
2. 本地编排服务接口（HTTP）：`compose/render/edit/export/task`。
3. 版本化项目结构：`projects/<project_id>/<version>/...`。
4. 产物输出：`score.json + MusicXML + MIDI + WAV + MP4`（导出三件套）。
5. 拖拽编辑对应的数据层回写（`pitch_shift`）。
6. 日志与可观测：`logs/tasks`、`logs/render`、`logs/export`。
7. AI 编曲支持 OpenAI 兼容格式（MVP 默认 DeepSeek provider，可配置扩展）。
8. Web 入口可直接访问（`/`、`/web`），支持一键跑完整链路。

## 项目结构

- `app/`：桌面端命令行入口（模拟 Desktop 操作）。
- `services/`：本地编排、编译、渲染、导出、HTTP 服务。
- `tests/`：MVP 关键用例自动化测试。
- `docs/`：PRD/SOP/SPEC/测试文档。
- `assets/`：默认 SoundFont 占位文件。

## 快速开始

### 1) 安装依赖

```bash
python3 -m pip install -r requirements.txt
```

### 2) 启动本地服务

```bash
python3 main.py --host 127.0.0.1 --port 8765
```

打开浏览器访问：`http://127.0.0.1:8765/`

Web 工作台能力（已完成）：

1. 项目列表与版本切换（读取本地历史项目）。
2. 一键全流程：`compose -> render_audio -> render_video -> export`。
3. 谱面可视化（Canvas 五线谱 + 音符表）。
4. 编辑与回滚操作（`score/edit`、`score/rollback`）。
5. 产物可视化预览（WAV/MP4）与文件链接。

### 3) 配置 AI（DeepSeek MVP）

在项目根目录创建 `.env`：

```env
DEEPSEEK_API_KEY=你的密钥
```

可选覆盖项：

```env
AI_PROVIDER=deepseek
AI_MODEL=deepseek-chat
AI_BASE_URL=https://api.deepseek.com/v1
```

### 4) 使用 CLI 走完整链路

```bash
python3 -m app.desktop_cli compose \
  --project-id demo_001 \
  --title 江南夜雨 \
  --style ancient_cn \
  --mood calm \
  --tempo-bpm 88 \
  --key D \
  --duration-sec 20 \
  --difficulty medium \
  --reference "古风、空灵、可演奏" \
  --compose-mode auto \
  --ai-provider deepseek
```

可选：指定“目标歌曲 + 参考谱”做高相似生成（验收场景）：

```bash
python3 -m app.desktop_cli compose \
  --project-id senbonzakura_demo \
  --title 千本樱 \
  --style custom \
  --mood dramatic \
  --tempo-bpm 154 \
  --key D \
  --duration-sec 30 \
  --difficulty hard \
  --reference "千本樱，钢琴版" \
  --target-song senbonzakura \
  --reference-score-path assets/reference_scores/senbonzakura.score.json
```

也可直接用 MIDI 作为参考输入（无需本地 OMR）：

```bash
python3 -m app.desktop_cli compose \
  --project-id senbonzakura_demo \
  --title 千本樱 \
  --style custom \
  --mood dramatic \
  --tempo-bpm 154 \
  --key D \
  --duration-sec 30 \
  --difficulty hard \
  --reference "千本樱，钢琴版" \
  --target-song senbonzakura \
  --reference-midi-path assets/reference_scores/senbonzakura.mid
```

`--compose-mode` 支持：

- `auto`：若 AI 配置可用则用 AI，否则回退规则编曲（默认）。
- `ai`：强制 AI 编曲，失败即报错。
- `rule`：固定规则编曲，不调用外部模型。

```bash
python3 -m app.desktop_cli render-audio \
  --project-id demo_001 \
  --version v001 \
  --midi-path projects/demo_001/v001/song.mid \
  --soundfont-path assets/soundfonts/piano.sf2
```

```bash
python3 -m app.desktop_cli render-video \
  --project-id demo_001 \
  --version v001 \
  --musicxml-path projects/demo_001/v001/song.musicxml \
  --wav-path projects/demo_001/v001/song.wav
```

```bash
python3 -m app.desktop_cli export \
  --project-id demo_001 \
  --version v001 \
  --targets musicxml midi mp4
```

相似度评估（默认验收阈值 95）：

```bash
python3 -m app.desktop_cli evaluate-similarity \
  --project-id senbonzakura_demo \
  --version v001 \
  --target-song senbonzakura \
  --reference-score-path assets/reference_scores/senbonzakura.score.json \
  --reference-midi-path assets/reference_scores/senbonzakura.mid \
  --threshold 95
```

### 5) 运行测试

```bash
pytest -q
```

## 文档导航

- 文档总索引：`docs/DOCS_INDEX.md`
- PRD：`docs/PRD_AI_Auto_Arrangement_v1.0.md`
- SOP：`docs/SOP_AI_Auto_Arrangement_v1.0.md`
- SPEC：`docs/SPEC_AI_Auto_Arrangement_v1.0.md`
- 测试用例：`docs/TEST_CASES_MVP_v1.0.md`

## 说明

1. 音频渲染使用本地合成（Python 内置实现）。
2. 视频渲染优先调用本地 `ffmpeg`；若系统无 `ffmpeg`，会生成占位 `mp4` 文件并提示原因。
3. Provider 注册表在 `services/config/llm_providers.json`，新增供应商无需改核心编排逻辑。
