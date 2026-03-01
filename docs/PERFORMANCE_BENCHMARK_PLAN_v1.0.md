# 性能基准计划（Performance Benchmark Plan V1.0）

## 1. 目标

建立 MVP 性能基线，覆盖 60 秒曲目全链路。

## 2. 基准机信息模板

1. CPU 型号
2. 内存大小
3. 操作系统版本
4. 磁盘类型

## 3. 指标

1. `T1`：编曲生成耗时。
2. `T2`：MusicXML/MIDI 编译耗时。
3. `T3`：WAV 渲染耗时。
4. `T4`：视频渲染与编码耗时。
5. `T_total`：端到端总耗时。
6. `sync_delta_ms`：音画偏差。

## 4. 场景

1. S1：古风模板输入（默认）。
2. S2：自定义风格输入。
3. S3：编辑后二次渲染。

## 5. 结果记录格式

```text
scenario,run_id,T1,T2,T3,T4,T_total,sync_delta_ms,result
S1,1,xx,xx,xx,xx,xx,xx,PASS
```

## 6. 判定

1. 指标稳定，无异常长尾。
2. 音画偏差 <= 80ms。
3. 与历史版本对比无明显回退。

