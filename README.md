# Chinese Novel Master Lab

面向中文网文与长篇连载的 Agent Skill：从项目准备、章节计划、正文写作，到跨章连续性核对与正典确认，使用同一套工作流程。它以人物行动、场景压力和可读性为写作核心；证据与状态检查在后台进行，不把小说写成设定表。

这是实验版。它能帮助整理决策和发现一部分连续性错误，但不保证固定的文学评分，也不声称脚本能判断故事好坏。仓库不包含任何小说正文或私有项目材料。

## 它怎样工作

```text
用户任务 + 已有小说材料
          │
          ▼
识别新书 / 续写 / 重写 → 核对当前有效资料与已批准正文
          │
          ▼
制定本章事实卡 → 自由起稿 → 正典核对 → 语言润色
          │                         │
          │                         └─ 长篇或高风险章节：可选结构化账本检查
          ▼
章节候选稿 + 证据冲突 + 候选状态变化
          │
          ▼
用户确认后，才更新正式正典
```

Skill 不是训练模型或替换模型的程序。Agent 先根据 `SKILL.md` 的名称与描述发现它，再读取写作规则；只有遇到相应任务时才按需读取 `references/` 的细则、使用 `templates/`，或调用 `scripts/nml.py`。这种分层让普通单章写作不必加载整套长篇账本。不同 Agent 使用同一份写作规则，安装目录和显式调用写法不同。

## 适合哪些任务

| 任务 | 如何处理 | 典型交付 |
| --- | --- | --- |
| 新书准备 | 明确读者承诺、人物驱动、冲突和待定问题；只做当前写作真正需要的规划 | 创作宪法、故事规格、章节方向、首章候选稿 |
| 按章续写 | 查已批准正文与有效设定，抓住上一章后果和本章目标 | 本章事实卡、章节候选稿、必要的状态变化 |
| 章节重写 | 保留已批准事件边界，区分作者、视角人物与读者各自知道什么 | 重写候选稿、对后续章节的影响清单 |
| 连续性核对 | 检查时间、伤病、资源、物件持有人、人物知情、关系和伏笔接续 | 带来源依据的冲突清单；可选账本报告 |

已有项目优先沿用自己的目录和文档，不会仅因模板存在就重建整套资料。普通短篇或单章可以只用写作流程，不启用结构化账本。

## 写作流程

1. **确认任务与资料效力。** 区分用户明确锁定的设定、已批准正文、计划、候选稿和历史快照。旧文档即使标题叫“总纲”，也不能因为名字像正典就覆盖较新的已批准正文。发生冲突时列出证据，必要时请用户裁定。
2. **建立本章事实卡。** 只收录会改变本章行动、代价、感知或误会的事实：视角、时间地点、身体状况、可用资源、关系、物件、人物知情范围，以及上一章尚未结清的后果。章纲提供压力与方向，不预写对白和情绪结论。
3. **三遍成稿。** 第一遍自由起稿，让人物在具体场景里做选择；第二遍核对姓名、时间、伤病、资源、知识和物件流转等硬事实；第三遍调整声音、节奏与重复解释。开篇冲突和章尾钩子是工具，不是机械配额。
4. **分开审读。** 文学反馈看人物、场景和阅读欲望；事实核验只报告有证据的冲突，不替作者改台词。无法安排独立核验时，应如实标注为自检。
5. **候选稿不自动成为正典。** 写后提取真正会影响后续章节的状态变化，附上正文证据。用户批准章节及相关变化后，才把它们并入正式状态；未解决的新设定提案保持待定。

这些规则的主要依据见 [`SKILL.md`](SKILL.md)。按任务再看 [`章节写作`](references/chapter-craft.md)、[`长篇连续性`](references/long-form-continuity.md)、[`审读与批准`](references/review-and-approval.md)、[`项目初始化`](references/project-bootstrap.md) 和 [`状态账本`](references/project-state.md)。

## 为什么能降低长篇出错

- **证据优先：** 把“计划将发生”“候选稿写了”“已批准正文确实发生”分开，避免把未来规划当既成事实。
- **人物知识分层：** 分清不知道、怀疑、确认；写作时只给当前视角人物能够合理获得的信息。
- **状态变化显式化：** 人物伤病、关系、物件和伏笔若发生实质变化，写成候选增量，而不是靠下次对话的模糊记忆。
- **人工批准边界：** 自动检查只能发现可编码的矛盾，不能替作者决定哪些新设定成为正典。

此处的“防幻觉”是降低无证据添加和前后矛盾的风险，不是消除模型错误；最终仍需读正文、核证据，并由作者决定。

## 仓库内容

| 路径 | 作用 |
| --- | --- |
| [`SKILL.md`](SKILL.md) | Agent 入口、任务选择、写作原则与审批边界 |
| [`references/`](references/) | 按需加载的章节写作、长篇连续性、审读、项目状态说明 |
| [`templates/`](templates/) | 新项目文档、事实卡、状态和候选增量的空白模板 |
| [`scripts/nml.py`](scripts/nml.py) | 可选的 Python 3.10+ 连续性账本工具，无第三方运行依赖 |
| [`tests/`](tests/) | 工具的自动化测试 |
| [`agents/openai.yaml`](agents/openai.yaml) | Codex 的可选界面元数据；不是 Antigravity 或 Claude Code 的运行依赖 |

## 安装到不同 Agent

安装时保留**整个仓库文件夹**，不要只复制 `SKILL.md`，否则引用文档、模板和脚本会丢失。以下为各产品当前文档支持的本机位置：

| Agent | 个人安装目录 | 项目内目录 | 显式调用 |
| --- | --- | --- | --- |
| Codex | `~/.agents/skills/chinese-novel-master-lab/` | `<项目>/.agents/skills/chinese-novel-master-lab/` | `$chinese-novel-master-lab` |
| Antigravity App / CLI / IDE | `~/.gemini/config/skills/chinese-novel-master-lab/` | `<项目>/.agents/skills/chinese-novel-master-lab/` | `/chinese-novel-master-lab` |
| Claude Code | `~/.claude/skills/chinese-novel-master-lab/` | `<项目>/.claude/skills/chinese-novel-master-lab/` | `/chinese-novel-master-lab` |

在终端选择一个目标目录，运行：

```bash
# Codex: TARGET_ROOT="$HOME/.agents/skills"
# Antigravity: TARGET_ROOT="$HOME/.gemini/config/skills"
# Claude Code: TARGET_ROOT="$HOME/.claude/skills"
TARGET_ROOT="$HOME/.agents/skills"
mkdir -p "$TARGET_ROOT"
git clone https://github.com/egguy886/chinese-novel-master-lab.git \
  "$TARGET_ROOT/chinese-novel-master-lab"
```

项目级安装时，把 `TARGET_ROOT` 改成该项目的 `.agents/skills`（Codex、Antigravity）或 `.claude/skills`（Claude Code）。Codex 与 Antigravity 可共用项目内的 `.agents/skills` 副本；Claude Code 需要自己的发现路径。若目录已经存在，进入该仓库按需更新，不要重复克隆。

```bash
git -C "$TARGET_ROOT/chinese-novel-master-lab" pull --ff-only
```

在对应 Agent 的对话中调用：

```text
Codex: $chinese-novel-master-lab 阅读当前项目设定，给我下一章的事实卡和候选正文。
Antigravity: /chinese-novel-master-lab 阅读当前项目设定，给我下一章的事实卡和候选正文。
Claude Code: /chinese-novel-master-lab 阅读当前项目设定，给我下一章的事实卡和候选正文。
```

也可直接描述任务，让 Agent 根据 Skill 描述自动选择；重要项目建议显式调用，并确认它读到了对应的 `SKILL.md`。本机个人安装不会自动同步到另一台机器或云端会话，尤其 Claude 的 Cowork / cloud 会话不会读取你电脑上的 `~/.claude/skills`。

安装位置与调用方式以产品官方文档为准：[Codex Skills](https://learn.chatgpt.com/docs/build-skills)、[Antigravity Agent Skills](https://antigravity.google/docs/skills/)、[Claude Code Skills](https://code.claude.com/docs/en/skills)。

## 可选的连续性账本

长篇项目可在小说目录下启用 `.novel-master-lab/`。它与 Skill 安装目录是两回事：前者存**某部小说的状态**，后者存**通用工作流程和工具**。

```text
小说项目/
  正文或章节草稿/
  .novel-master-lab/
    sources.json      # 来源登记、效力状态、章节范围与哈希
    state.json        # 当前已批准的人物、关系、物件、知识、伏笔等状态
    deltas/           # 各章的候选状态变化
    approvals/        # 批准记录
    backups/          # 批准前的状态备份
```

`sources.json` 可标记 `active`、`candidate`、`stale`、`mixed`，避免旧设定和后来追加的内容被误认作同一效力。`prepare` 固定章节稿和当前状态的 SHA-256；`check` 检查文件是否变化、章节是否接续、时间是否倒退、物件持有人是否合法、人物知情状态是否倒退或缺少获取方式、伏笔状态与证据字段是否合规。脚本不理解小说语义，既不能证明证据引文真实，也不能判定角色反应是否可信。

### 在小说项目中运行

请用 **Skill 安装目录的绝对路径**定位脚本。下面以 Codex 个人安装为例；使用其他 Agent 时改动 `SKILL_DIR` 即可。`BOOK` 必须指向已存在的小说项目目录。

```bash
SKILL_DIR="$HOME/.agents/skills/chinese-novel-master-lab"
BOOK="/absolute/path/to/小说项目"

# 初始化可选账本；--new-project 还会补齐缺失的规划文档模板
python3 "$SKILL_DIR/scripts/nml.py" init "$BOOK" --new-project

# 先写好第一章候选稿，再生成候选增量并填入真实变化与正文证据
python3 "$SKILL_DIR/scripts/nml.py" prepare "$BOOK" \
  "$BOOK/章节草稿/001_章节名.md" --chapter 1

# 只读检查；通过不等于文学质量合格，也不等于用户已批准
python3 "$SKILL_DIR/scripts/nml.py" check "$BOOK" \
  --delta "$BOOK/.novel-master-lab/deltas/ch-001.json"
```

`init` 不覆盖已有账本；`prepare` 会创建候选增量，只支持当前已批准章节的下一章；`check` 不修改文件。已有长篇先人工校准其已批准正文和初始状态，不要把空白模板误当全书事实。填写格式看 [`状态账本说明`](references/project-state.md) 和 [`增量示例`](references/data-examples.md)。

**只有用户明确批准章节与候选变化之后**，才能执行写入正式状态的命令：

```bash
python3 "$SKILL_DIR/scripts/nml.py" approve "$BOOK" \
  --delta "$BOOK/.novel-master-lab/deltas/ch-001.json" \
  --approval-note "用户已批准本章及候选状态变化"
```

`approve` 会备份旧状态、登记已批准正文和哈希，并生成批准记录。早期章节重写不适用自动顺推，应人工检查对后续已批准章节的影响。

## 验证与边界

在 Skill 仓库根目录运行：

```bash
python3 -m unittest discover -s tests -v
python3 scripts/nml.py --help
```

Python 工具无第三方运行依赖；测试覆盖结构化账本的主要状态转换，不等于跨 Agent 实际写作质量测试。Agent 是否遵循 Skill 还取决于其版本、权限、上下文与所读项目材料。`check` 的通过只说明已编码的结构规则通过，不能替代人工审稿和来源核对。

仓库当前未附开源许可证；公开可见不代表取得复制、修改或再分发授权。
