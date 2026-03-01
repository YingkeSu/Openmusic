# 接口规格（API Interface Spec V1.0）

> 说明：MVP 采用桌面本地优先。此处定义桌面端与本地服务进程之间的接口，可实现为 HTTP 或 IPC。

## 1. 通用约定

1. 所有请求必须携带 `project_id`。
2. 返回格式统一：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

3. `code != 0` 视为失败，`message` 返回可读错误。

## 2. 生成接口

### POST `/api/v1/compose`

1. 作用：根据用户意图生成编曲计划并产出 MusicXML/MIDI。
2. 请求体：

```json
{
  "project_id": "uuid",
  "title": "江南夜雨",
  "style": "ancient_cn",
  "mood": "calm",
  "tempo_bpm": 88,
  "key": "D",
  "duration_sec": 60,
  "difficulty": "medium",
  "reference": "古风、空灵、可演奏"
}
```

3. 响应体：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "version": "v001",
    "score_json": "projects/<id>/v001/score.json",
    "musicxml": "projects/<id>/v001/song.musicxml",
    "midi": "projects/<id>/v001/song.mid"
  }
}
```

## 3. 音频渲染接口

### POST `/api/v1/render/audio`

1. 作用：本地渲染 WAV。
2. 请求体：

```json
{
  "project_id": "uuid",
  "version": "v001",
  "midi_path": "projects/<id>/v001/song.mid",
  "soundfont_path": "assets/soundfonts/piano.sf2"
}
```

3. 响应体包含 `wav_path`。

## 4. 视频渲染接口

### POST `/api/v1/render/video`

1. 作用：本地渲染谱面进度视频。
2. 请求体：

```json
{
  "project_id": "uuid",
  "version": "v001",
  "musicxml_path": "projects/<id>/v001/song.musicxml",
  "wav_path": "projects/<id>/v001/song.wav",
  "highlight_scheme": {
    "played": "#000000",
    "unplayed": "#C8C8C8"
  }
}
```

3. 响应体包含 `mp4_path`。

## 5. 拖拽编辑接口

### POST `/api/v1/score/edit`

1. 作用：提交拖拽编辑变更并生成新版本。
2. 请求体：

```json
{
  "project_id": "uuid",
  "base_version": "v001",
  "edits": [
    {
      "note_id": "n_000123",
      "type": "pitch_shift",
      "semitones": 2
    }
  ]
}
```

3. 响应体返回 `new_version` 及更新后的 `score_json/musicxml/midi`。

## 6. 导出接口

### POST `/api/v1/export`

1. 作用：导出三件套（MusicXML + MIDI + MP4）。
2. 请求体：

```json
{
  "project_id": "uuid",
  "version": "v002",
  "targets": ["musicxml", "midi", "mp4"]
}
```

3. 响应体返回导出目录和 `manifest.json` 路径。

## 7. 任务状态接口

### GET `/api/v1/tasks/{task_id}`

1. 返回任务状态：`queued/running/success/failed`。
2. 返回阶段：`compose/compile/render_audio/render_video/export`。

## 8. 错误码建议

1. `1001` 参数校验失败。
2. `1002` 时长超限（>60s）。
3. `2001` 编曲生成失败。
4. `3001` 乐谱编译失败。
5. `4001` 音频渲染失败。
6. `4002` 视频渲染失败。
7. `5001` 导出失败。

