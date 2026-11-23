---
# Lite 默认（单人 + AI 必填）：id、title、status、verification；id 必须与目录名完全一致
id: TASK-ID
title: 任务名称
status: planned
verification:
  status: not_run
  checked_at: null
  revision: null
# Team / 复杂任务可选（有协作、依赖或归属需要时填写，无需填满 null）：
# feature: null
# modules: []
# owner: null
# assignee: null
# reviewer: null
# priority: null
# depends_on: []
# write_scope: []
# source: null
# updated_at: null
---

# 任务名称

## 目标与出处

描述要做什么，引用对应 BACKLOG 条目、计划或原始用户请求。

## 工作范围与接口

说明修改范围、必要输入输出和共享契约链接。涉及新文件时在此标注拟新增，不写入现存目录地图。

## 当前结果与交接

区分已实现、已验证和待完成；说明当前所在分支/未提交改动、剩余事项与下一步接手前提。

## 验证依据

| 时间 | 版本/工作范围 | 检查方法 | 实际结果 | 覆盖范围 | 记录链接 |
| --- | --- | --- | --- | --- | --- |

尚未验证时明确写出。历史结果与当前版本相关性分别说明。

## 阻塞与变更记录

记录障碍与解除条件（无协作或未阻塞可简写“无”）；范围、状态或重开变更及原因简记于此，详细过程放 `records/`。
