# 从零开始写好 Skill（二）：一个好 Skill 长什么样——SKILL.md 的解剖

> **「从零开始写好 Skill」系列** —— 上一个系列我们用 7 篇文章拆解了 Agent 的骨架，这个系列教你给 Agent 写"工作手册"。
>
> - 第一篇：[Skill 是什么？为什么你应该关心它](./skill-01-what-is-skill.md)
> - **第二篇：一个好 Skill 长什么样（本文）**
> - 第三篇：手把手写你的第一个 Skill（即将更新）

-----

## 开场：看到结构 ≠ 会写结构

上一篇，我们看到了 wespy-fetcher 的 SKILL.md，知道它分成几个部分，也感受到了"有 Skill vs 没 Skill"的巨大差距。

但"看到"和"会写"是两回事。

同样是写 description，为什么有的 Skill 一触即发，有的被 Agent 视而不见？同样是写操作步骤，为什么有的让 Agent 一步到位，有的让 Agent 反复出错？

这篇我们就拿 wespy-fetcher 的真实 SKILL.md 开刀，逐段拆解。不是再讲一遍"这段是什么"——上一篇已经讲过了。这次讲的是：**这段怎么写才有效，写错了会怎样**。

-----

## 一、先看全貌：一个 Skill 的四层骨架

把 wespy-fetcher 的 SKILL.md 完整放一次，这次不加批注，先看原貌：

```markdown
---
name: wespy-fetcher
description: 获取并转换微信公众号/网页文章为 Markdown 的封装 Skill，
  完整支持 WeSpy 的单篇抓取、微信专辑批量下载、专辑列表获取、
  HTML/JSON/Markdown 多格式输出。
  Use when user asks to 抓取微信公众号文章、公众号专辑批量下载、
  URL 转 Markdown、保存微信文章、mp.weixin.qq.com to markdown.
---

# WeSpy Fetcher

封装 tianchangNorth/WeSpy 的完整能力。

## 功能范围（与 WeSpy 对齐）

- 单篇文章抓取（微信公众号 / 通用网页 / 掘金）
- 微信专辑文章列表获取（--album-only）
- 微信专辑批量下载（--max-articles）
- 多格式输出（Markdown 默认，支持 HTML / JSON / 全部）

## 使用

脚本位置：scripts/wespy_cli.py

# 单篇文章（默认输出 markdown）
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx"

# 专辑批量下载
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/mp/appmsgalbum?..." --max-articles 20

## 实现说明

- 优先使用本地源码路径 ~/Documents/QNSZ/project/WeSpy
- 若本地不存在则自动执行 git clone 到该目录
- 通过导入 wespy.main.main 直接调用上游 CLI，保持行为一致
```

这份文件虽然不长，但有清晰的四层结构。Agent 读取它的过程，就像你面试一个人一样，是**分层递进**的：

**第一层：头部（YAML frontmatter）—— 简历筛选**

Agent 启动时扫描所有 Skill 的 description，判断"这个任务该不该用这个 Skill"。绝大多数 Skill 在这一步就被跳过了。如果你的 description 写得不好，Agent 根本不会往下读。

**第二层：概述（标题 + 功能范围）—— 电话面试**

通过了第一层筛选，Agent 会快速读一下概述，确认能力范围是否匹配。"这个 Skill 能处理专辑批量下载吗？"——扫一眼功能范围列表就知道了。

**第三层：操作指南（使用方式、命令、参数）—— 入职培训**

确认要用这个 Skill 了，Agent 开始读具体的操作步骤。"脚本在哪？怎么调用？参数怎么传？"——这一层给出所有执行细节。

**第四层：补充说明（实现细节、依赖、兜底逻辑）—— 应急手册**

执行过程中遇到问题了，Agent 来查这一层。"WeSpy 没装怎么办？"——补充说明告诉它自动 clone。

记住这个分层逻辑，它决定了你写 SKILL.md 时每一段应该放什么、不应该放什么。

-----

## 二、头部：description 是触发器，不是摘要

头部的 YAML frontmatter 是整个 Skill 最关键的几行。写错了，后面的内容写得再好也没用——因为 Agent 根本不会读到后面。

再看一遍 wespy-fetcher 的 description：

```yaml
description: 获取并转换微信公众号/网页文章为 Markdown 的封装 Skill，
  完整支持 WeSpy 的单篇抓取、微信专辑批量下载、专辑列表获取、
  HTML/JSON/Markdown 多格式输出。
  Use when user asks to 抓取微信公众号文章、公众号专辑批量下载、
  URL 转 Markdown、保存微信文章、mp.weixin.qq.com to markdown.
```

这段 description 做对了三件事：

**第一，前半段是能力声明——"我能做什么"。**

"获取并转换微信公众号/网页文章为 Markdown"，一句话讲清楚核心能力。Agent 扫到这里就知道：这是一个处理公众号文章的 Skill，不是处理视频的，不是处理 PDF 的。

**第二，后半段是触发词列表——"用户怎么说时该想到我"。**

"Use when user asks to"后面跟了一串关键词：抓取微信公众号文章、公众号专辑批量下载、URL 转 Markdown、保存微信文章、mp.weixin.qq.com to markdown。

这些不是给人看的，是给 Agent 看的。用户说"帮我抓取这篇公众号"，Agent 拿"抓取"和"公众号"去匹配所有 Skill 的 description，命中了"抓取微信公众号文章"，于是加载这个 Skill。

**第三，覆盖了用户的多种说法。**

同一件事，不同的人会用不同的词。有人说"抓取"，有人说"下载"，有人说"保存"，有人直接丢一个 mp.weixin.qq.com 的链接。好的 description 把这些变体都列上了。

现在看一个反面。假如 description 写成这样：

```yaml
description: 一个用于处理微信文章的工具。
```

问题在哪？

"处理"太模糊了——是抓取？翻译？排版？总结？Agent 无法判断这个 Skill 是否匹配当前任务。触发词也太少，用户说"帮我下载这篇公众号文章"的时候，"下载"和"处理"匹配不上。

再看一个另外的极端——写太长了：

```yaml
description: 这是一个非常强大的工具，可以帮助你从微信公众号平台上
  获取任意文章的完整内容，包括文字、图片和格式信息，它使用了
  先进的爬虫技术来绕过微信的反爬机制，支持多种输出格式，
  并且可以批量处理微信专辑中的所有文章......
```

问题：Agent 扫描 description 时需要快速判断，不是来读论文的。冗长的描述反而增加了误匹配的风险，而且真正有用的触发词被淹没在废话里了。

**description 的写作公式：**

> 一句话能力声明 + "Use when user asks to" + 用户可能说的各种关键词

简洁、精准、覆盖变体。就这样。

-----

## 三、概述：划边界，不是做广告

通过了 description 的筛选，Agent 开始读概述。wespy-fetcher 的概述只有一句话：

> 封装 tianchangNorth/WeSpy 的完整能力。

这句话的价值不在于它说了什么，而在于它**划了边界**。它告诉 Agent：这个 Skill 的能力范围 = WeSpy 的能力范围，不多不少。Agent 不会拿它去干 WeSpy 做不到的事。

接着是"功能范围"列表：

```markdown
- 单篇文章抓取（微信公众号 / 通用网页 / 掘金）
- 微信专辑文章列表获取（--album-only）
- 微信专辑批量下载（--max-articles）
- 多格式输出（Markdown 默认，支持 HTML / JSON / 全部）
```

这段的作用是**让 Agent 快速做能力匹配**。用户说"帮我批量下载这个专辑"，Agent 扫一眼功能范围，看到"微信专辑批量下载"，确认匹配，往下读操作步骤。用户说"帮我把这篇文章翻译成英文"，Agent 扫一眼，没有"翻译"相关的功能，跳过这个 Skill，去找别的。

这里有个常见的坑：**在概述里塞太多操作细节**。

比如有人会在功能范围里写：

```markdown
- 单篇文章抓取（使用 python3 scripts/wespy_cli.py 命令，
  需要先确保 WeSpy 已安装在 ~/Documents/QNSZ/project/WeSpy 目录，
  如果没有安装会自动 git clone...）
```

这样写的问题是：Agent 在概述阶段只需要判断"能不能做"，不需要知道"具体怎么做"。操作细节应该放在下一层。概述阶段塞太多信息，反而干扰了 Agent 的匹配判断。

**概述的写作原则：说清楚能做什么、不能做什么，其他的一概不说。**

-----

## 四、操作指南：Agent 的执行剧本

确认要用这个 Skill 了，Agent 进入操作指南。这是 Skill 的核心——Agent 拿到任务后，具体按什么步骤做。

wespy-fetcher 的操作指南长这样：

```markdown
## 使用

脚本位置：scripts/wespy_cli.py

# 单篇文章（默认输出 markdown）
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx"

# 专辑批量下载
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/mp/appmsgalbum?..." --max-articles 20
```

注意它做对了什么：**给了多个具体场景的命令示例**，而不是只给一个通用命令。

"单篇文章"和"专辑批量下载"是两个不同的使用场景，用户的需求可能是其中任何一个。Agent 看到这些示例，能根据用户的具体需求选择最匹配的命令，而不是每次都用同一个。

如果操作指南只写成这样：

```markdown
## 使用
python3 scripts/wespy_cli.py [URL] [OPTIONS]
```

Agent 就得自己猜：用户要批量下载的时候，OPTIONS 该填什么？`--max-articles` 还是 `--batch`？`--album-only` 是什么意思？猜错了就执行失败。

**操作指南的第一原则：给具体场景的示例，不要给抽象的通用模板。**

不过，这里要指出一个重要的事实：wespy-fetcher 用的是"命令示例"这种写法，因为它本质上是一个**工具封装**——把一个已有的命令行工具包装成 Skill，教 Agent 怎么调用。

但不是所有 Skill 都是工具封装。不同类型的 Skill，操作指南的写法完全不同：

如果你的 Skill 是一个**生成器**（比如"生成技术报告"），操作指南应该写成：加载模板 → 向用户收集信息 → 填充模板 → 输出文档。

如果你的 Skill 是一个**审查器**（比如"代码审查"），操作指南应该写成：加载审查清单 → 逐条检查用户代码 → 按严重程度分组 → 输出结构化报告。

如果你的 Skill 是一个**流水线**（比如"从代码生成 API 文档"），操作指南应该写成：步骤1 → 检查点（用户确认）→ 步骤2 → 检查点 → 步骤3。

如果你的 Skill 是一个**反转**（比如"项目规划"），操作指南应该写成：按顺序提问 → 等待用户回答 → 收集完信息后再综合输出。不允许 Agent 在收集完之前就开始行动。

**操作指南的写法取决于你的 Skill 属于哪种类型，没有万能格式。** 这些类型我们在后续文章会展开讲，这里先建立一个认知：看到一个 Skill 的操作指南，先判断它是哪种类型，再评估它写得好不好。

-----

## 五、补充说明：你以为不重要的部分，其实最防坑

wespy-fetcher 的"实现说明"：

```markdown
- 优先使用本地源码路径 ~/Documents/QNSZ/project/WeSpy
- 若本地不存在则自动执行 git clone 到该目录
- 通过导入 wespy.main.main 直接调用上游 CLI，保持行为一致
```

很多人写 Skill 的时候，把精力花在 description 和操作指南上，补充说明随便写两句甚至不写。这是一个很大的误区。

想想看：Agent 按照操作指南开始执行，调用 `python3 scripts/wespy_cli.py`，结果发现 WeSpy 没安装。怎么办？

如果没有补充说明，Agent 有几种可能的反应：

- 直接报错："WeSpy 未安装，请手动安装后重试"——回到了上一篇那个"甩锅"的状态
- 自己猜一个安装方式：`pip install wespy`——如果猜错了，装了个完全不相关的包
- 去网上搜索安装方法——浪费时间，而且可能搜到过时的信息

但有了这三行补充说明，Agent 知道：先检查 `~/Documents/QNSZ/project/WeSpy` 这个路径，有就用，没有就 `git clone` 到这里。流程闭环，不会卡死。

这就是补充说明的核心价值：**把 Agent 执行过程中可能遇到的"岔路口"提前堵死。**

什么是"岔路口"？就是那些 Agent 需要做判断、可能判断错的地方：

- 依赖不存在怎么办
- 网络超时怎么办
- 输入格式不对怎么办
- 输出目录不存在怎么办
- 同名文件已经存在，覆盖还是跳过

每一个你踩过的坑，都应该写进补充说明。**Skill 会随着使用越来越"聪明"，就是因为踩过的坑都沉淀在这里了。**

-----

## 六、纠正一个简化：Skill 不只是一个文件

第一篇为了降低门槛，我们说"Skill 就是一个 Markdown 文件"。这个说法帮你建立了最初的认知，但严格来说不够准确。

**Skill 是一个文件夹**，SKILL.md 只是入口。

一个完整的 Skill 文件夹可以包含：

```
wespy-fetcher/
├── SKILL.md            ← 入口文件，Agent 首先读这个
├── scripts/
│   └── wespy_cli.py    ← 可执行脚本，Agent 调用它来完成任务
├── references/         ← 参考资料（API 文档、编码规范等）
└── assets/             ← 模板、示例输出、配置文件等
```

SKILL.md 是大脑——告诉 Agent 该做什么。scripts/ 是手脚——提供实际执行的脚本。references/ 是参考书——存放 Agent 可能需要查阅的背景知识。assets/ 是工具箱——存放模板、配置等辅助资源。

Agent 不是读完 SKILL.md 就凭空干活——它会探索整个文件夹，在需要的时候读取对应的文件。wespy-fetcher 的操作指南里写了 `scripts/wespy_cli.py`，Agent 执行时就会去 scripts/ 目录下找这个脚本。

这引出一个重要的实践原则：**SKILL.md 本身应该保持精简，建议控制在 500 行以内。** 超出的内容拆分到子文件里，在 SKILL.md 中用相对路径引用。

为什么？因为 Agent 的上下文窗口是有限的。如果你把一个 3000 行的 API 文档塞进 SKILL.md，Agent 每次加载这个 Skill 都要吃掉大量的上下文空间，留给其他任务的空间就少了。

更好的做法是：SKILL.md 里写"详细的 API 规范见 references/api.md"，Agent 只在真正需要查 API 的时候才去加载那个文件。这就是**渐进式揭示**——按需加载，不一次性全塞进去。

-----

## 七、一个检查清单：你的 SKILL.md 写对了吗？

拆解完了，给你一份可以直接带走的检查清单。下次写完一个 SKILL.md，对照着过一遍：

**头部（description）：**

- [ ] 写的是触发条件，不是功能摘要
- [ ] 包含"Use when user asks to"或类似的触发词列表
- [ ] 覆盖了用户可能的多种表达方式（同一件事的不同说法）
- [ ] 长度适中，不超过 5 行

**概述：**

- [ ] 一句话说清楚这个 Skill 的能力边界
- [ ] 功能范围列表只列"能做什么"，不包含操作细节

**操作指南：**

- [ ] 给了具体场景的命令或步骤示例
- [ ] 不同使用场景有不同的示例（不只是一个通用模板）
- [ ] 写法匹配 Skill 的类型（工具封装、生成器、审查器、流水线、反转）

**补充说明：**

- [ ] 覆盖了依赖缺失的兜底方案
- [ ] 覆盖了常见的错误场景和处理方式
- [ ] 踩过的坑都沉淀在这里了

**整体结构：**

- [ ] SKILL.md 控制在 500 行以内
- [ ] 超出的内容拆到了 references/、scripts/、assets/ 子目录
- [ ] 四层结构清晰：头部 → 概述 → 操作指南 → 补充说明

-----

## 下一篇预告

现在你知道了一个好 Skill 长什么样，也有了检查清单可以对照。但纸上得来终觉浅——读一百个别人的 Skill，不如自己从零写一个。

下一篇，我们从一个真实需求出发，手把手写一个 Skill。你会看到完整的迭代过程：第一版写得很粗糙，Agent 用着各种出错；一步步修改，踩坑，补充，直到第三版终于好用。这个"从烂到好"的过程，比直接看一个成品更有价值。

-----

*「从零开始写好 Skill」系列是「从零开始理解 Agent」系列的姊妹篇。如果你还没有读过 Agent 系列，建议先从 [第一篇：Agent 的底层原理](./nanoAgent-01-essence.md) 开始。*
