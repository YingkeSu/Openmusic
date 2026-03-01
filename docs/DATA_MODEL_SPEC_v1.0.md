# 数据模型规格（Data Model Spec V1.0）

## 1. 实体关系总览

1. Project：项目主实体。
2. Version：项目版本快照。
3. Score：结构化乐谱数据。
4. Artifact：编译与渲染产物。
5. Task：异步任务状态。
6. StyleProfile：风格策略配置。

## 2. Project

```json
{
  "project_id": "uuid",
  "title": "string",
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "active_version": "v003"
}
```

## 3. Version

```json
{
  "project_id": "uuid",
  "version": "v003",
  "parent_version": "v002",
  "reason": "compose | manual_edit | rollback",
  "created_at": "ISO8601"
}
```

## 4. Score

```json
{
  "meta": {
    "time_signature": "4/4",
    "tempo_bpm": 88,
    "key": "D",
    "duration_sec": 60,
    "style": "ancient_cn"
  },
  "notes": [
    {
      "note_id": "n_000123",
      "bar": 1,
      "beat": 1.0,
      "pitch": "A4",
      "dur": "1/8",
      "vel": 72,
      "tie": false
    }
  ]
}
```

## 5. Artifact

```json
{
  "project_id": "uuid",
  "version": "v003",
  "musicxml_path": ".../song.musicxml",
  "midi_path": ".../song.mid",
  "wav_path": ".../song.wav",
  "mp4_path": ".../song.mp4",
  "checksum": {
    "musicxml": "sha256",
    "midi": "sha256",
    "wav": "sha256",
    "mp4": "sha256"
  }
}
```

## 6. Task

```json
{
  "task_id": "uuid",
  "project_id": "uuid",
  "version": "v003",
  "stage": "compose | compile | render_audio | render_video | export",
  "status": "queued | running | success | failed",
  "started_at": "ISO8601",
  "ended_at": "ISO8601",
  "error": "string"
}
```

## 7. StyleProfile

```json
{
  "style_id": "ancient_cn",
  "prompt_rules": ["pentatonic", "ornament_allow"],
  "harmony_rules": ["I-IV-V preference"],
  "evaluation_rules": ["style_consistency_score >= 0.8"]
}
```

## 8. 目录约定

1. `projects/<project_id>/<version>/score.json`
2. `projects/<project_id>/<version>/song.musicxml`
3. `projects/<project_id>/<version>/song.mid`
4. `projects/<project_id>/<version>/song.wav`
5. `projects/<project_id>/<version>/song.mp4`
6. `projects/<project_id>/<version>/manifest.json`

