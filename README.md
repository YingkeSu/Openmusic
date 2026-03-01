# OpenMusic / Piano for AI

AI 自动编曲项目（MVP）文档仓库。

## 当前范围（已确认）

1. 单曲上限 60 秒。
2. 古风优先（同时支持用户自定义风格）。
3. 谱面拖拽编辑优先。
4. 桌面本地优先。
5. 必须导出 `MusicXML + MIDI + MP4`。
6. 音频与视频必须本地渲染。

## 文档导航

- 文档总索引：`docs/DOCS_INDEX.md`
- 文档覆盖矩阵：`docs/DOCUMENT_COVERAGE_MATRIX.md`
- PRD：`docs/PRD_AI_Auto_Arrangement_v1.0.md`
- SOP：`docs/SOP_AI_Auto_Arrangement_v1.0.md`
- SPEC：`docs/SPEC_AI_Auto_Arrangement_v1.0.md`
- 测试总策略：`docs/TEST_STRATEGY_v1.0.md`
- 测试计划：`docs/TEST_PLAN_MVP_v1.0.md`
- 测试用例：`docs/TEST_CASES_MVP_v1.0.md`

## 目录建议（后续代码阶段）

- `app/`：桌面客户端
- `services/`：本地编排与渲染服务
- `docs/`：产品、技术、测试、发布文档
- `assets/`：SoundFont、测试素材、样例输入

## 状态

当前阶段：文档设计与方案冻结。

