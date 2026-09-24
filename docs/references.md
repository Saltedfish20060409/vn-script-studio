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
| [Lost in the Middle](https://arxiv.org/abs/2307.03172) | 模型对上下文中段的利用最差 | `agent_context.py` 的组装顺序：硬规则首尾重复已经对；检索到的设定条目应避免沉在中段 |
| [Distance between Relevant Information Pieces Causes Bias](https://aclanthology.org/2025.findings-acl.28/) | 证据片段之间的**距离**本身造成偏差 | `consistency_scan` 的分片窗口大小/重叠（**待办**：做一个窗口参数 → 实测暴露率的对照） |
| [LongMemEval](https://arxiv.org/abs/2410.10813) | 长期记忆该按"问答式"维度评测 | 用来自测章节摘要 + 账本 + 滚动记忆"到底记不记得住"（**待办**） |
| [MemGPT](https://raw.githubusercontent.com/lhl/agentic-memory/32e2bec4f65aa1286c81b6866fe815d7a61b71c2/references/packer-memgpt.md) / 图谱化检索（[Clue-RAG 为例](https://arxiv.org/abs/2507.08445)） | 分页换出 / 分层图谱检索 | 「快照 / 章节记忆」路线；`loreEntries.links` + 时间线本质是图，"检索顺带走一步"已对了一半 |

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
- [ ] Lost in the Middle：把"检索结果别放中段"落进 `agent_context.py`
- [ ] 分片窗口参数 → 暴露率对照实验（Distance… 那篇的方法）
- [ ] LongMemEval 式的记忆自测脚本
- [ ] Choice Poetics / Dunyazad：选项分类进 `branchAdvice`
- [ ] Dror：A/B 报告给区间
- [ ] Best-of-N：多变体按自洽度选
- [ ] Tail at Scale：慢思考档的 hedged request
