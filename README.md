# OpenMusic / Piano for AI

AI 自动编曲项目（MVP）仓库。

## 当前范围（已确认）

1. 单曲上限 60 秒。
2. 古风优先（同时支持用户自定义风格）。
3. 谱面拖拽编辑优先。
4. 桌面本地优先。
5. 必须导出 `MusicXML + MIDI + MP4`。
6. 音频与视频必须本地渲染。

## 项目状态

已从“纯文档阶段”推进到“可运行 MVP 服务骨架”。

- 实现说明：`docs/IMPLEMENTATION_STATUS_v1.0.md`
- 服务代码：`openmusic_service/`
- 启动入口：`main.py`

## 快速启动

```bash
python3 main.py
```

服务默认地址：`http://127.0.0.1:18080`

## 已实现 API（MVP 骨架）

- `POST /api/v1/compose`
- `POST /api/v1/render/audio`
- `POST /api/v1/render/video`
- `POST /api/v1/score/edit`
- `POST /api/v1/export`
- `GET /api/v1/tasks/{task_id}`

## 文档导航

- 文档总索引：`docs/DOCS_INDEX.md`
- 文档覆盖矩阵：`docs/DOCUMENT_COVERAGE_MATRIX.md`
- PRD：`docs/PRD_AI_Auto_Arrangement_v1.0.md`
- SOP：`docs/SOP_AI_Auto_Arrangement_v1.0.md`
- SPEC：`docs/SPEC_AI_Auto_Arrangement_v1.0.md`
- 测试总策略：`docs/TEST_STRATEGY_v1.0.md`
- 测试计划：`docs/TEST_PLAN_MVP_v1.0.md`
- 测试用例：`docs/TEST_CASES_MVP_v1.0.md`
