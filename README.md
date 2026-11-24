# 项目管家 · Project Manager Skill

一个面向 Codex 的项目管理技能，维护项目目录地图、用户主动添加的需求清单、任务进度和协作交接。使用者可以直接用自然语言操作，无需了解内部模板或字段。

## 快速开始

把本仓库的 `skills/project-manager` 完整文件夹复制到目标项目的 `.agents/skills/` 下：

```text
你的项目/
└── .agents/
    └── skills/
        └── project-manager/
            ├── SKILL.md
            ├── agents/
            ├── references/
            └── assets/
```

在目标项目中打开 Codex，选择项目管家技能或输入：

```text
使用 $project-manager 初始化当前项目的管理资料。
```

如果技能尚未出现在列表中，重启 Codex 后查看。也可以将完整技能文件夹安装在个人的 `~/.agents/skills/` 下供多个项目使用。请保留整个文件夹结构。

## 日常使用

| 想做什么 | 可以这样说 |
| --- | --- |
| 建立项目地图 | 使用 $project-manager 分析当前项目，建立带文件职责注解的目录树。 |
| 设定编码规范 | 使用 $project-manager 为当前项目启用 CONVENTIONS.md，记录架构分层与编码规范。 |
| 收集一个想法 | 使用 $project-manager 记下一个需求：支持导出聊天记录。 |
| 查看需求 | 使用 $project-manager 展示需求清单和完成情况。 |
| 拆解工作 | 使用 $project-manager 把导出聊天记录这个想法拆成任务。 |
| 查看进度 | 使用 $project-manager 看看项目做到哪里了，下一步先做什么。 |
| 更新资料 | 使用 $project-manager 检查本次修改，更新目录地图和相关任务进度。 |
| 交接任务 | 使用 $project-manager 整理当前结果、阻塞和下一步，让别人接着做。 |

自然语言可以匹配技能；显式选择技能或保留 `$project-manager` 可以明确指定本技能。

## 生成的项目资料

```text
.project/
├── INDEX.md                 # 总入口和模块导航
├── PROJECT.md               # 项目用途、目标、范围与约束
├── CONVENTIONS.md           # （可选）当前项目的编码规范、架构约束与开发红线
├── BACKLOG.md               # 用户主动添加的需求与完成复选框
├── STATE.md                 # 当前状态、阻塞和下一步
├── modules/
│   └── 模块名称/
│       ├── MAP.md           # 带逐文件注解的真实目录树
│       └── CONTEXT.md       # 模块入口、依赖和已知问题
├── tasks/
│   └── 任务编号/
│       ├── TASK.md          # 目标、分工、状态、检查依据和交接
│       └── records/         # 参与者的独立工作记录
├── features/                # 复杂工作需要时建立 PLAN.md
├── contracts/               # 需要时维护共享接口约定
└── archive/                 # 用户要求整理历史时使用
```

只创建本次工作需要的资料。大型项目按模块拆分地图，按任务读取上下文。尚未核实的内容会明确标注，任务状态来自实际检查和工作记录。

## 随时追加需求

用户可以亲手编辑目标项目 `.project/BACKLOG.md`，或明确要求智能体“把这个需求加入清单”。每条只显示需求短句与完成勾选：

```markdown
- [ ] 希望聊天记录可以导出。
- [x] 编辑伴侣资料后直接保存。
```

智能体不能根据普通功能反馈、代码调查或自己的建议自行新增条目。实现分析、原始请求和检查记录放在任务文件中。需求整体完成后更新勾选；添加需求只表示登记，开发由后续工作请求决定。

## 刷新和清理旧信息

```text
使用 $project-manager 对照当前代码刷新 .project，移除已过期结论和重复摘要，保留有用的任务历史。
```

当前资料按主题替换更新：INDEX 做导航，PROJECT 保留目标/约束，MAP 对应实际文件，CONTEXT 保留现行职责/命令，STATE 汇总当前状态。已解决问题、被替代方案和失效快照从当前摘要移除；详细执行过程在 TASK/records 保留，并标注旧流程的交付时点。

刷新会核对任务统计、地图路径/数量、相关事实与本地链接。历史检查与本次检查分别注明时间和范围，不将旧测试数当成当前结果；小修改只刷新受影响范围。BACKLOG 的用户所有权和简短复选框形式保持不变。

## 仓库结构

- [SKILL.md](skills/project-manager/SKILL.md)：技能入口与共用规则。
- [scripts/check_project.py](skills/project-manager/scripts/check_project.py)：零依赖校验脚本（任务 ID/依赖/统计、相对链接、MAP 路径核对与 `--next-id`）。
- [references/](skills/project-manager/references/)：初始化、需求收集、任务规划、协作和进度核实流程。
- [assets/templates/](skills/project-manager/assets/templates/)：12 个项目资料模板（含可选 `conventions.md` 与 `AGENTS.md` 轻量同步片段 `agents-snippet.md`）。
- [agents/openai.yaml](skills/project-manager/agents/openai.yaml)：技能界面信息。

维护技能时修改 `skills/project-manager/`；更新安装副本时保留使用者项目中的 `.project/` 资料。

## 适用范围

当前版本面向 Codex 的本地文件工作流，采用指令和模板，不依赖额外的项目管理服务。其他智能体工具需按各自的技能发现规则安装，尚未进行跨工具运行验证。

当前已做技能结构、引用链接和 YAML 检查；完整工作流仍需在实际项目中持续验证。

参考：[OpenAI Skills 官方文档](https://developers.openai.com/codex/skills/)。
