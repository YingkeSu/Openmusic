# OpenMusic MVP 实现说明（V1.0）

## 已实现内容

基于现有 PRD/SPEC/API/Data Model 文档，已新增一个本地可运行的 MVP 服务骨架（标准库实现，无第三方依赖）：

- `POST /api/v1/compose`
- `POST /api/v1/render/audio`
- `POST /api/v1/render/video`
- `POST /api/v1/score/edit`
- `POST /api/v1/export`
- `GET /api/v1/tasks/{task_id}`

## 代码位置

- `openmusic_service/server.py`：HTTP 服务入口与路由。
- `openmusic_service/service.py`：核心业务逻辑（版本、文件产物、导出 manifest）。
- `openmusic_service/models.py`：Project/Version/Task 与 JSON 存储。
- `main.py`：启动入口。

## 与文档约束对齐

1. 时长限制：`duration_sec > 60` 返回 `1002`。
2. 产物三件套：MusicXML / MIDI / MP4。
3. 本地落盘目录：`runtime_data/projects/<project_id>/<version>/...`。
4. 导出含 checksum：`manifest.json` 包含 sha256。
5. 任务状态：渲染接口写入并可查询 task。

## 当前实现边界

- 目前使用占位产物（最小可识别文件头）模拟渲染结果。
- 未接入真实 LLM/music21/FluidSynth/FFmpeg。
- 拖拽编辑仅演示 `pitch_shift` 的最小行为。

## 启动方式

```bash
python3 main.py
```

默认监听：`127.0.0.1:18080`
