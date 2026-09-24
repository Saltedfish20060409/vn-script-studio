# 参考依据索引（规范 / 论文 → 项目的哪个决定）

这份文件回答两个问题：**我们凭什么这么判**、**想深挖该读什么**。

顺序是"从能当规范用的，到只能当参考的"——推荐性国家标准与排版需求在最前，
因为它们是可直接核对、可写进代码依据的；论文在后，因为绝大多数是**相邻领域**，
没有一篇能给出"轻小说 AI 工作流"的答案。

> 写在代码里的依据优先于本文：`app/core/novel_consistency.py` 的 `_RULE_BASIS` 与
> `frontend/src/lib/editorAssist.ts` 的 `RULE_BASIS` 是**真源**，两份由
> `backend/tests/test_rule_basis.py` 逐条比对守卫。本文只做索引与延伸阅读。

---

## 一、写作规范（可直接核对，已落进代码）

| 依据 | 管什么 | 落在哪 |
|---|---|---|
| **GB/T 15834-2011《标点符号用法》**<br>（推荐性国标；[全文转载](https://cbimg.cnki.net/Editor/2016/1222/misy/10004b10-38f3-47ad-a43f-356437b3b0a3.docx)） | 标点符号的写法与用法：引号/括号成对、引号内再引号降一级、书名号内再书名号用〈〉、破折号（——）、省略号（……）、连接号 | `novel_consistency` 与 `editorAssist.lintProse` 的 `quote_unbalanced` / `quote_nested_level` / `title_mark_nested` / `dash_ascii_double` / `dash_single_em` / `ellipsis_ascii_dots` / `ellipsis_fullwidth_period` |
| **GB/T 15835-2011《出版物上数字用法》** | 数字的写法与宽度；数值范围的写法（起止数字之间用一字线/浪纹线） | `digit_width_mixed`、`dash_ascii_range` |
| **CY/T 154-2017《中文出版物夹用英文的编辑规范》**<br>（[标准平台](https://std.samr.gov.cn/hb/search/stdHBDetailed?id=8B1827F23645BB19E05397BE0A0AB44A)、[全文](https://www.spc.org.cn/online/8ae3828864f5e2f8c43455ed49bd4b88.html)） | 中文里夹用英文的间距、大小写与标点 | `punct_halfwidth_near_cjk`、`letter_width_mixed`、`space_between_cjk`；**中英间距只判"内部是否一致"**（见下方说明） |
| **W3C《中文排版需求》(clreq)**（[W3C TR](https://www.w3.org/TR/2023/DNOTE-clreq-20230301/)） | 标点的比例与位置、行首行尾禁则、书名号、注音（旁注）等中文排版的行业需求 | 标点类规则的并列依据；注音导出（待办：见第四节） |
| **W3C HTML Ruby Markup Extensions / Ruby Annotation**（[W3C TR](https://www.w3.org/TR/html-ruby-extensions/)） | 注音标记的规范形态（`<ruby>` / `<rt>`，以及不支持的场合用 `<rp>` 回退） | `app/core/ruby_render.py`：源写法 `｜汉字《注音》` / `{汉字\|注音}` → **Markdown 出 W3C `<ruby>/<rt>`（带 `<rp>` 回退）**，Word 稿与 .rpy 出 `<rp>` 回退的纯文本形态 |
| **JTF 日本語標準スタイルガイド**（[PDF](https://www.jtf.jp/pdf/jtf_style_guide.pdf)） | 日文的注音（ルビ）、送假名、记号规则 | 轻小说/日文路径（**待办**：目前只做中文注音） |
| **Locke & Latham 目标设定理论**（[APA](https://psycnet.apa.org/record/2002-15790-003)，35 年综述） | 目标要具体、可测、有难度但可达，且**反馈必须及时**；否则承诺度会掉 | 见下方"目标设定理论落到哪"一节 |
| 各出版社/平台的投稿规定（非论文） | 投稿排版（首行缩进、一章一文件、字数表） | `export_submission` 的默认值；**没有按某个平台的规范硬编码**，理由见下方"投稿规定：为什么不做平台对齐" |

**注意"推荐性"三个字**：国标是推荐性的，文学写作里破例是常事。所以除「引号不配对」外
（它会让我们在导出时把后续正文吞进台词），所有表记规则都只报 warn/info，并附依据，
由作者定夺。

### 中英之间要不要加空格：只判"一致"，不判"对错"

中文里夹用英文（`中文 English` vs `中文English`）这件事，两派都有依据：中文排版惯例
不加空格（靠字体在行内自动留白），西文出版物则常要求加。**我们没有资格替作者定风格**，
所以 `cjk_latin_spacing_mixed` 只报一种情况：**同一部作品里两种写法混用**
（例如本书里 12 处加了空格、156 处没加）。那是客观问题——导出后每页疏密都不一样。
依据栏里也如实写明"不判定加空格与不加空格哪种对，只判定本书内部是否一致"。

### 上下文分块的位置策略（Lost in the Middle）

论文结论：长上下文里模型对**开头与结尾**的信息利用最好，夹在中间的最容易被忽略，
且上下文越长偏差越明显。

我们这里还有一层放大效应：**超预算时的裁剪是"保头保尾、压中段"**
（`build_agent_context` 末尾：先压缩其它章摘录，再把 `text[:keep_head] + 中段压缩标记 +
text[-keep_tail:]` 拼回去）。两件事叠加之后，位置就不只是"读起来顺不顺"，
而直接决定**哪些事实会被模型看到**：放头部的会逐字保留，放中段的会被压掉。

于是把分块按"如果模型忽略它会怎样"分成三组（`agent_context._SECTION_ORDER`）：

| 组 | 内容 | 理由 |
|---|---|---|
| **头部** | 硬规则、角色、关系、地点、bible、检索命中的设定条目与关联实体、长程/全局/对话记忆 | 这是这一轮的地基，而且会被裁剪原样保留 |
| **中段** | 章节目录、其它章摘录、写作参考卡、**作者上传的参考文档（上限 12000 字）**、变量、立绘 | 量大但通常不决定"这一步怎么写"；超预算时第一个被压的就是这里 |
| **尾部** | 文风样例、当前章正文、用户选区 → 再接末尾的硬规则、输出契约、作者硬规则 | 贴着本次请求（最近优先），最后那一小段是"当场生效"区 |

**这条改动修掉的真问题**：参考文档过去排在分块列表第 9 位（在角色/关系/地点之前），
而它是最大的一块（最多 12000 字）——超预算时头部被逐字保留，于是**参考文档占住了头部，
把「角色 / 关系」挤进被压缩的中段**。现在参考文档进中段，高价值块进头部。

`tests/test_context_ordering.py` 断言的是结构性不变量而不是文案：位置表与代码里的 key
完全一致（漏登记会被静默排到最后）、硬规则在最前且末尾重复、地基块在中段块之前、
当前章正文落在尾部窗口、**参考文档很大时角色/关系/设定必须仍在**（回归守卫）。

### 记忆探针：一次真实的发现（LongMemEval 那套维度的价值）

`core/memory_probe.py` 按 LongMemEval 的维度造探针，**只组装上下文、不调模型**，
回答的是"该有的证据有没有进上下文"。它第一次运行就有三个维度是红的，
顺着查下去发现了**同一类缺陷的三处**——全都源于"只看脚本块、不看正文"：

1. **`agent_context.plain_of` 只读 blocks**：纯正文工程里「当前章节」只剩一个标题，
   模型被要求"紧接正文末尾续写"却看不到那段正文（正文写作是本作品的主写作面！）。
2. **`chapter_digest._collect_lines` 只遍历 blocks**：正文写作的章节收集到 0 行 →
   摘要变成「（空章）」、openHook/closeHook 全空 → 账本里既没有章末钩子也没有出场角色
   （"保存即攒记忆"对小说作者整条失效；轻小说模板当初不得不预置伏笔，根因就在这）。
3. **`chapter_content_hash` 不含 prose**：改了正文指纹不变，于是摘要/账本被判定为
   "没变"而**永不刷新**——前两条即使修好，也不会在保存时生效。

三处都已改为**正文优先**，与本作品其它流水线（`consistency_scan`、`writing_stats`、
`novel_craft`、导出链路）统一口径。这类问题的表现与"模型记不住"**一模一样**，
但修法完全不同——这正是把记忆拆成可分别测量的维度的意义。

探针的五维映射与限制写在 `core/memory_probe.py` 的模块说明里，其中"知识更新"一栏
**如实留空**：账本与长程记忆是 HTTP 层拼好传进上下文构建器的字符串，探针看不到它们的构造过程。

### 选项分类（Choice Poetics / Dunyazad）：只判结构，不判心理

三篇讲的是"玩家的体验"：选择的意义来自**玩家放弃了什么**（[Choice Poetics](https://cs.wellesley.edu/~pmwh/research/papers/towards-choice-poetics-fdg-2014.pdf)），
作者应当**有意识地混用** relaxed / obvious / dilemma 三类（[Intentionally Generating Choices](https://computationalcreativity.net/iccc2015/proceedings/13_4Mateas.pdf)、
[Dunyazad](https://ojs.aaai.org/index.php/AIIDE/article/view/12791)）。体验需要真人，
而剧本里**客观可判**的只有结构。所以 `core/choice_poetics.py` 把三类落成结构判据：

| 类 | 我们的结构判据 |
|---|---|
| `relaxed`（怎么选都一样） | 与同菜单另一个选项的后果完全相同（同目标、同变量改动） |
| `obvious`（意图明确） | 后果与其它选项不同，但不与任何选项争同一个状态位 |
| `dilemma`（两难） | 与同菜单另一个选项在**同一个变量上取不同的值** → 选了 A 就拿不到 B |

判"两难"用"同一状态位取互斥值"而不是"分支不再汇合"：后者要看跨 label 可达性，
在真实剧本里容易把"分开很久又合流"误判成永久分叉；而"玩家真的拿不到两样东西"是结构上
能确定的事实。

**我们不做**：不判"选项文案写得好不好""玩家会不会犹豫"——那需要真人，模型打分也不可靠
（见 Art or Artifice?）。也**不把"没有两难"当错误**：日常系作品的轻松选择是有意为之，
所以这类提示一律只报 info，并给出"缺哪一类、有几个菜单"的量。

接进现有链路：`recommend_branch_improvements` 会多出 `choiceVariety` 段与两条 info 建议
（`menu_all_relaxed` / `no_dilemma_choice`，都带**具体改法**），前端在「分析 → 改进建议」
里显示类别分布与"怎么选都一样"的选择点。

### 只作参考、不改代码的那几篇（附理由）

清单里剩下的论文不是"没读"，而是读了之后判断**不需要为此改代码**。理由逐条写明，
免得以后有人以为漏了：

| 文献 | 为什么不动代码 |
|---|---|
| [Plan-and-Write](https://arxiv.org/abs/1811.05701) | "先大纲后成文"我们已经这么做（`beatSheet` + `harnessRuns` + 大纲任务档）。它的贡献是"阶段划分方式影响连贯"，我们已经在节拍表里体现；没有新的可执行结论 |
| [Re3](https://arxiv.org/abs/2210.06774) | 递归重提示 + 修订 = 我们的"续写 + 责编润色"两段式（含"体检全过就不调模型"）。它在 2022 年要解决的问题，现在由长上下文模型 + 我们的检索层分担 |
| [LongWriter](https://proceedings.iclr.cc/paper_files/paper/2025/hash/59f278de1619bdb6b53fd04e8e0976e0-Abstract-Conference.html) | 它的解法在**训练侧**（长输出数据合成 / 后训练），我们是调用方，动不了模型权重。可借鉴的"长输出后半段会崩"这一点，已经体现在"章节目标字数 + 分段续写"的产品选择里 |
| [CALYPSO](https://arxiv.org/abs/2308.07540) | 跑团助手的分层生成思路与我们的 pipeline 一致（先定场景/角色，再生成），但没有可搬的具体机制 |
| [Riedl & Young, Narrative Planning](https://dl.acm.org/doi/10.5555/1946417.1946422) | plot / character 的权衡是**解读框架**，不是算法。它已经体现在情绪弧与伏笔回收率的解读措辞里；做成规则会变成"叙事应该怎样"的教条 |
| [Art or Artifice?](https://dl.acm.org/doi/fullHtml/10.1145/3613904.3642731) | 它的结论是**不要**用模型打文学分。我们已经是"结构量 + 人工盲测"，属于"照它说的做了"，无需再改 |
| [The Silent Judge](https://arxiv.org/abs/2509.26072) | 提醒 judge 的位置/长度偏好。我们目前**没有**任何"模型当裁判"的自动评分环节（多变体是给人挑的），所以它是一条"将来若引入 judge 必须遵守"的约束，记在这里即可 |
| [Merging Facts, Crafting Fallacies](https://aclanthology.org/2024.findings-acl.160.pdf) | 它指出原子事实法在"聚合后的矛盾"上失效——这正是我们分片扫描的固有局限，已经写在 `docs/longrange-consistency-and-eval.md` 的残余风险里 |
| [Self-Refine](https://www.ijcai.org/proceedings/2024/0693.pdf) | "必须有外部反馈"我们已经落在 `harness_editor_pass`：先跑确定性体检，体检全过就不调模型。照它说的做了 |
| [MemGPT](https://raw.githubusercontent.com/lhl/agentic-memory/32e2bec4f65aa1286c81b6866fe815d7a61b71c2/references/packer-memgpt.md) | 分页换出对应我们的「快照 / 章节记忆」；它是**编排框架**，我们的编排已经存在，换框架的收益不足以抵掉风险 |

真正需要改代码的只剩三条（都列在下面的待办里）：Dror 的区间报告、Best-of-N 的自洽度选择、
Tail at Scale 的 hedging 决策。

### 目标设定理论落到哪（Locke & Latham）
理论的关键词是：**具体**、**有难度但可达**、**反馈及时**、**承诺度**。逐条对照现状：

| 理论要点 | 我们的做法 |
|---|---|
| 目标要具体 | `writingGoals` 三档（本章/本卷/今日）都是具体字数，不是"多写点" |
| 反馈要及时 | **本轮补的**：连载页与写作辅助的"今日净增"过去只在切章时刷新（作者写完回来看还是旧值，等于没有反馈），现在停在该页时每 30 秒自动补拉一次，页面不可见时不拉 |
| 目标要有难度但可达 | **本轮补的**：`calibrateDailyGoal` 用**近 7 个日历日的日均**（没写的天按 0 算）与日更目标对照，给中性事实：`comfortable / stretch / unreachable`。差得远时建议调低目标，而不是让人硬撑；样本不足（产出 < 2 天）时不下结论 |
| 承诺度 | 目标存在作品里（换设备也在），且永远由作者自己设——工具不预设"你该日更 3000" |

**刻意不做**：排行榜、连续天数惩罚、"你落后了"的催促、把目标当考核。
理论说的是目标与反馈要服务于动机，催和比会直接摧毁它。

### 投稿规定：为什么不做平台对齐

各平台/出版社的投稿要求各不相同、还经常改，**检索到的只有二手说法**（论坛帖、第三方仓库），
拿它当依据既不诚实也留不住。所以这一条落成了两件事：

1. **导出默认值照"最常被要求的那几项"来**（首行缩进 2 字符、每章另起一页、文末标字数、
   梗概默认不带、可一章一个文件），每一项都能在界面上关掉——默认值不是规范，是起点。
2. **投稿前自检**（`frontend/src/lib/submissionPreflight.ts`）：检查的是**我们自己写明的
   默认值**与**作者自己作品的状态**——空章、重复标题、引号不配对（导出时会吞台词，
   唯一算 blocker 的一条）、元信息没填、字数是否明显偏离作者自己设的单章目标。
   条目少、结论明确，回答的是"现在这一包能不能交出去"。

作者仍需自己核对的（工具不猜、也无法代劳）：目标平台要求的字数区间、章节数上限、
是否要投稿信、是否要求特定字体字号、文件名格式。

没有公开规范可依、只能靠作品自身一致性的：人名变体、视角偏移、称呼漂移、别字词表——
依据里如实写成"作品自身的一致性（启发式）"，不假借国标。

---

## 二、技术指导（论文 → 改哪个决定）

### 长程一致性与记忆
| 文献 | 结论 | 我们的落点 |
|---|---|---|
| [Lost in the Middle](https://arxiv.org/abs/2307.03172) | 模型对上下文中段的利用最差 | **已落进代码**：`agent_context._SECTION_ORDER`（见下方专节） |
| [Distance between Relevant Information Pieces Causes Bias](https://aclanthology.org/2025.findings-acl.28/) | 证据片段之间的**距离**本身造成偏差 | **已落进代码**：`core/scan_exposure.py` 把"跨章矛盾能否同窗"变成可测量的覆盖率，并据此把分片默认值从 6/2 改成 12/4（数字与推导见 `longrange-consistency-and-eval.md` §三.1） |
| [LongMemEval](https://arxiv.org/abs/2410.10813) | 长期记忆该按"问答式"维度评测（信息抽取 / 多会话推理 / 时间推理 / 知识更新 / 拒答） | **已落进代码**：`core/memory_probe.py`（零模型调用的检索层探针），并因此抓到三个真缺陷（见下方专节） |
| [MemGPT](https://raw.githubusercontent.com/lhl/agentic-memory/32e2bec4f65aa1286c81b6866fe815d7a61b71c2/references/packer-memgpt.md) / 图谱化检索（[Clue-RAG 为例](https://arxiv.org/abs/2507.08445)） | 分页换出 / 分层图谱检索 | 「快照 / 章节记忆」路线；`loreEntries.links` + 时间线本质是图——**`graph_hop` 探针**把"沿 links 走一步能不能走到关联实体"变成可测项 |

### 长文生成与规划
| 文献 | 结论 | 我们的落点 |
|---|---|---|
| [Plan-and-Write](https://arxiv.org/abs/1811.05701) | 先大纲后成文，阶段划分影响全局连贯 | `beatSheet` / `harnessRuns` 的节拍表设计 |
| [Re3](https://arxiv.org/abs/2210.06774) | 递归重提示 + 修订优于一次生成长文 | "续写 + 责编润色"两段式；解释了一次生成整章为何掉质量 |
| [LongWriter](https://proceedings.iclr.cc/paper_files/paper/2025/hash/59f278de1619bdb6b53fd04e8e0976e0-Abstract-Conference.html) | 长输出的失效机制与数据合成 | 长章生成的参数与预期管理 |
| [CALYPSO](https://arxiv.org/abs/2308.07540) | LLM 做跑团助手的分层生成 | VN 剧本 / `pipeline` 的分层生成思路 |

### 分支叙事与选择设计
| 文献 | 结论 | 我们的落点 |
|---|---|---|
| [Towards a Theory of Choice Poetics](https://cs.wellesley.edu/~pmwh/research/papers/towards-choice-poetics-fdg-2014.pdf) | 选择的意义来自玩家放弃了什么 | `branchAdvice` 的判定语言（**待办**：现在只有统计驱动） |
| [Intentionally Generating Choices](https://computationalcreativity.net/iccc2015/proceedings/13_4Mateas.pdf) / [Dunyazad 的三分类](https://ojs.aaai.org/index.php/AIIDE/article/view/12791) | relaxed / obvious / dilemma 三种选择类型 | 选项分类词典（**待办**） |
| [Riedl & Young, Narrative Planning](https://dl.acm.org/doi/10.5555/1946417.1946422) | plot 与 character 的权衡 | 情绪弧与伏笔回收率的解读框架 |

### 评估
| 文献 | 结论 | 我们的落点 |
|---|---|---|
| [Art or Artifice?](https://dl.acm.org/doi/fullHtml/10.1145/3613904.3642731) | LLM 的"创造力"判断与人类作家系统性不一致 | 支持我们的做法：结构量（暴露率/检出率）+ 人工盲测，而不是让模型打分 |
| [The Silent Judge](https://arxiv.org/abs/2509.26072) | LLM-as-judge 存在捷径偏差（位置/长度） | 任何"模型当裁判"的环节（A/B、多变体）都要控偏差 |
| [Dror et al., 显著性检验指南](https://aclanthology.org/P18-1128/) | 报告差异要给统计检验 | A/B 盲测报告应给区间而非单点差值（**待办**） |
| [Merging Facts, Crafting Fallacies](https://aclanthology.org/2024.findings-acl.160.pdf) | 原子事实法在"聚合后的矛盾"上失效 | `consistency_scan` 跨窗聚合的固有局限（已写进文档的残余风险） |
| [Self-Refine](https://www.ijcai.org/proceedings/2024/0693.pdf) | 需要外部反馈才有增益，纯自我批评会退化 | `harness_editor_pass`：先跑确定性体检、体检全过就不调模型 |
| [Best-of-N Selection via Self-Certainty](https://proceedings.neurips.cc/paper_files/paper/2025/hash/1c7eff166a8e345f664f0faa8f4e4d2e-Abstract-Conference.html) | 多变体应按自洽度/不确定性选，而不是抽签 | `processMark(..., 3)` 的多变体取舍（**待办**） |

### 工程实务
| 文献 | 结论 | 我们的落点 |
|---|---|---|
| Dean & Barroso, *The Tail at Scale*（CACM 56(2), 2013） | 长尾才是问题；对策之一是 hedged request（发两路取先返回） | `llm_budget.py` 现在是"给足预算"，慢思考档可加 hedging 削 P99（**待办**） |
| 幂等性与重试 | 只有幂等请求才该重试 | 已实现：连接类错误才重试，读超时不重试 |

---

## 三、别指望论文的地方（免得白花时间）

1. **超时预算该设多少秒**——没有论文能给；只能像现在这样做实测（`docs/llm-timeout-budget.md`）。
2. **中文别字/标点的产品级零误报口径**——[SIGHAN 中文拼写检查评测](https://aclanthology.org/W13-4406/)（[后续一届](https://aclanthology.org/W15-3121/)）与
   [CSC/CGEC 综述](https://arxiv.org/abs/2504.00977) 给的是模型能力天花板与数据集构造法。
   它们印证了现在的选择（词表只收零歧义项、其余交给模型）；要往上做该顺着这条线（训练/微调），
   而不是继续拍词表。
3. **章末"钩子强度"**——没有学术指标；可借的是叙事学里关于悬念发生的结构性理论（定性框架），
   不能直接变成 0–1 分数。现在的评分标成 heuristic 是对的。
4. **读者建模**——检索下来只有平台/媒介研究（例如 [韩国平台连载网文的媒介形态](https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId=ART003372687)、
   [类型小说的叙事兴趣与出版生态](https://ila.onlinelibrary.wiley.com/doi/pdf/10.1002/rrq.70098)），
   没有可复用的算法论文。这块找产品对标比找论文有用。

---

## 四、待办（按本文从上到下推进，做完划掉）

- [x] 规则依据层：`_RULE_BASIS` / `RULE_BASIS` + 界面上显示依据 + 防分叉守卫
- [x] GB/T 15834 新增三条：书名号嵌套、引号嵌套层次、连接号（数字区间用半角连字符）
- [x] GB/T 15835：数值范围（`dash_ascii_range`）、公历年份用阿拉伯数字（`cjk_year_digits`）、
      「几」表约数用汉字（`arabic_with_ji`）、概数不用顿号（`arabic_dunhao_range`）
- [x] CY/T 154-2017：中英间距**内部一致性**（`cjk_latin_spacing_mixed`）+ 为什么只判一致性
- [ ] GB/T 15835 剩余：百分号与计量单位的写法（中文正文里 `%`/`％`、`km`/`公里` 的统一）
- [x] W3C Ruby：新增 `core/ruby_render.py`（源写法 → W3C `<ruby>/<rt>` / `<rp>` 回退），
      接进 Markdown、docx（含投稿稿）、.rpy 三条导出链路；
      **顺带修掉一个真实缺陷**：Ren'Py 字符串过去只转义 `\` 与 `"`，正文里的 `{` `}`
      （包括注音花括号写法）会让导出的脚本报"未知文本标签"
- [ ] W3C Ruby 剩余：Word 原生注音（`w:ruby`）；Ren'Py 内联注音标签（未能确证语法，
      不往用户脚本里写未经验证的标签）
- [ ] JTF 样式指南：日文注音/送假名（日文稿子真正落地时）
- [x] 目标设定理论：核对现有设计 + 补"反馈及时"（连载页与写作辅助每 30 秒自动刷新）
      + 补目标难度校准（`calibrateDailyGoal`，日历日均对照，差得远就建议调低）
- [x] 投稿规定：导出默认值写明 + **投稿前自检**（`submissionPreflight`），
      不做平台对齐（没有可核对的权威规范，理由写在正文）
- [x] Lost in the Middle：新增 `agent_context._SECTION_ORDER`（三段位置策略 + 与裁剪的交互）
      + `tests/test_context_ordering.py`（7 项）；修掉"参考文档占住头部、把角色/关系挤进中段"
- [x] Distance…：`core/scan_exposure.py`（章覆盖 / 按距离分桶的对暴露率 / 预算下的书覆盖）
      + 12 项测试；**实测推出"同窗上限 = overlap"并把默认值从 6/2 改成 12/4**
      （16 窗覆盖 66→132 章，距离上限 2→4）；前端加了读后端源码的防漂移守卫
- [x] LongMemEval：`core/memory_probe.py`（五维探针，零模型调用）+ 11 项测试；
      **探针抓到三个真缺陷**（上下文/摘要/指纹都只看脚本块、不看正文），已全部修复
- [x] MemGPT / GraphRAG：`graph_hop` 探针把"沿条目 links 走一步"变成可测项；
      分页/分层本身仍是「快照 / 章节记忆」路线，未另做
- [x] 时间线进上下文：`agent_context._timeline_lines`（焦点章之前的事件；跳过 stale 并说明）
      ——这是"时间推理"维度第一次运行就红掉的那个缺口
- [x] Choice Poetics + Dunyazad：`core/choice_poetics.py`（relaxed / obvious / dilemma 的
      **结构代理**：同后果 / 不同结果 / 同一状态位取互斥值）+ 13 项后端测试；
      接进 `branch_recommendations`（新增 `choiceVariety` 段与两条 info 建议），
      前端在「分析 → 改进建议」显示类别分布与"怎么选都一样"的选择点（7 项测试）
- [x] Riedl&Young / Plan-and-Write / Re3 / LongWriter / CALYPSO /
      Art or Artifice? / Silent Judge / Merging Facts / Self-Refine / MemGPT：
      **判定为"参考不改代码"并逐条写明理由**（见上方专节）——不是漏做
- [ ] Dror：A/B 报告给区间（现在只给单点差值）
- [ ] Best-of-N：多变体按自洽度选（现在靠挑）
- [ ] Tail at Scale：慢思考档的 hedged request（要先算清 2× token 成本这笔账）
