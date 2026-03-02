# OpenMusic / Piano for AI

AI 自动编曲 MVP（文档 + 可运行本地服务实现）。

## 已实现能力（对齐文档 V1.0）

1. 60 秒时长上限校验（超限返回 `1002`）。
2. 本地编排服务接口（HTTP）：`compose/render/edit/export/task`。
3. 版本化项目结构：`projects/<project_id>/<version>/...`。
4. 产物输出：`score.json + MusicXML + MIDI + WAV + MP4`（导出三件套）。
5. 拖拽编辑对应的数据层回写（`pitch_shift`）。
6. 日志与可观测：`logs/tasks`、`logs/render`、`logs/export`。

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

### 3) 使用 CLI 走完整链路

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
  --reference "古风、空灵、可演奏"
```

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

### 4) 运行测试

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
