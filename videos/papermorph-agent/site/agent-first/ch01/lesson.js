'use strict';
const CHAPTER = {number: 1, title: '工具与循环：Agent 为什么能动手？', minutes: 4, language: 'zh', lead: false};
const AG = {model: '#13796c', tool: '#b65331', history: '#416a9c', ink: '#213e3b', muted: '#596c65', line: '#c6cdbf'};

function agText(p, value, x, y, size = 32, fill = AG.ink, anchor = 'start', weight = 500) {
  return T(p, value, {x, y, size, fill, anchor, weight});
}
function agReveal(e, at, dx = 0) {
  const {x, y} = st(e);
  put(e, {o: 0, x: x + dx, y: y + 14});
  tw(e, {o: 1, x, y}, at, .65, out);
  return e;
}
function agBase(n, title, subtitle) {
  const p = panel(0);
  mk('rect', {x: 0, y: 0, width: 1600, height: 900, fill: '#f5f0e5'}, p);
  for (let x = 60; x < 1600; x += 40) {
    for (let y = 75; y < 900; y += 40) mk('circle', {cx: x, cy: y, r: 1, fill: '#213e3b', opacity: .055}, p);
  }
  agText(p, '从零开始理解 AGENT  /  01', 90, 76, 23, AG.model, 'start', 700);
  agText(p, String(n).padStart(2, '0') + ' / 10', 1510, 76, 23, AG.muted, 'end');
  agText(p, title, 90, 164, 52, AG.ink, 'start', 650);
  if (subtitle) agText(p, subtitle, 92, 216, 26, AG.muted);
  return p;
}
function agCard(p, x, y, w, h, title, lines, color = AG.model, at = 0) {
  const g = G(p);
  mk('rect', {x, y, width: w, height: h, rx: 22, fill: '#fffaf1', stroke: color, 'stroke-width': 2}, g);
  mk('rect', {x: x + 24, y: y + 27, width: 6, height: 34, rx: 3, fill: color}, g);
  agText(g, title, x + 46, y + 55, 34, color, 'start', 650);
  lines.forEach((line, i) => agText(g, line, x + 30, y + 110 + i * 43, 27));
  agReveal(g, at);
  return g;
}
function agArrow(p, d, at, color = AG.model) {
  const e = path(p, d, {stroke: color, 'stroke-width': 5, fill: 'none', 'stroke-linecap': 'round', 'stroke-linejoin': 'round'}, {d: 0});
  draw(e, at, .8);
  return e;
}
function agNote(p, value, at, color = AG.model) {
  const g = G(p);
  mk('rect', {x: 90, y: 740, width: 1420, height: 76, rx: 16, fill: color, opacity: .08}, g);
  agText(g, value, 800, 789, 29, color, 'middle', 650);
  agReveal(g, at);
}
function agPacket(p, label, from, to, at, color = AG.model) {
  const g = G(p, {x: from[0], y: from[1], o: 0});
  mk('rect', {x: -72, y: -26, width: 144, height: 52, rx: 26, fill: color}, g);
  agText(g, label, 0, 10, 23, '#ffffff', 'middle', 650);
  tw(g, {o: 1}, at, .18);
  tw(g, {x: to[0], y: to[1]}, at + .2, 1.2, io);
  tw(g, {o: 0}, at + 1.45, .22);
}
function agHistory(p, rows, at, rowTimes = []) {
  const g = agCard(p, 975, 285, 535, 400, 'messages · 工作记录', [], AG.history, at);
  rows.forEach((row, i) => {
    const label = agText(g, row, 1005, 395 + i * 43, 27);
    agReveal(label, rowTimes[i] ?? at);
  });
  return g;
}

const BEATS = [
  ['intro', '为什么 Agent 能动手', (m) => {
    const p = agBase(1, '同一个模型，为什么能从“说”变成“做”？', '从一个约 100 行的最小实现，看到 Agent 的核心闭环');
    agCard(p, 160, 330, 470, 250, '只生成文本', ['告诉你怎么操作', '你来执行'], AG.history, m('question'));
    agCard(p, 970, 330, 470, 250, '接上工具与循环', ['提出动作 → 程序执行', '看见结果 → 再决定'], AG.model, m('answer'));
    agArrow(p, 'M680 455 H920 M900 435 L920 455 L900 475', m('answer'));
    agNote(p, '不是换一颗大脑，而是接上手脚，让结果回来。', m('answer') + 1);
  }],
  ['contrast', '从建议到行动', (m) => {
    const p = agBase(2, '同一个目标，两种运行方式', '目标：统计 Python 文件数量，并写入 count.txt');
    agCard(p, 90, 295, 650, 340, '文本建议', ['模型：给你统计命令', '你：复制、执行、写文件', '动作仍然由人完成'], AG.history, m('chat'));
    agCard(p, 860, 295, 650, 340, '工具闭环', ['模型：请求统计', '程序：执行并返回数量', '模型：根据结果请求写入'], AG.model, m('agent'));
    agPacket(p, '实际行动', [800, 660], [1185, 660], m('agent') + 1, AG.tool);
    agNote(p, '这里比较的是运行模式，不是给聊天产品划死边界。', m('agent') + 4);
  }],
  ['parts', '大脑、手脚与循环', (m) => {
    const p = agBase(3, '最小 Agent = 大模型 + 工具 + 循环', '大脑提出动作，手脚执行；结果回来，才有下一次决定');
    agCard(p, 110, 315, 440, 245, '大模型 · 大脑', ['决定下一步', '选择工具与参数'], AG.model, m('brain'));
    agCard(p, 1050, 315, 440, 245, '工具 · 手脚', ['真正操作环境', '返回结果或错误'], AG.tool, m('hands'));
    agArrow(p, 'M570 385 H1030 M1010 365 L1030 385 L1010 405', m('loop'), AG.model);
    agArrow(p, 'M1050 590 V665 H330 V580 M310 600 L330 580 L350 600', m('loop') + 1, AG.history);
    agReveal(agText(p, '调用意图', 800, 350, 28, AG.model, 'middle'), m('loop'));
    agReveal(agText(p, '执行结果回传', 800, 648, 28, AG.history, 'middle'), m('loop') + 1);
    agPacket(p, '动作', [590, 385], [1010, 385], m('loop') + .3);
    agNote(p, '循环不是重复同一句话，而是带着新结果继续判断。', m('loop') + 3);
  }],
  ['tools', '工具说明不是工具执行', (m) => {
    const p = agBase(4, '工具说明书，连接模型与程序', '工具名 + 用途 + 参数：模型据此表达调用意图');
    agCard(p, 90, 290, 440, 385, 'tools · 说明书', ['execute_bash(command)', 'read_file(path)', 'write_file(path, content)', '描述能力，不执行动作'], AG.history, m('manual'));
    agCard(p, 620, 290, 390, 385, '模型输出', ['工具名：write_file', '参数：path, content', '这是一份调用请求'], AG.model, m('intent'));
    agCard(p, 1100, 290, 410, 385, 'Python 执行', ['解析工具名与参数', '找到对应函数', '操作文件并返回结果'], AG.tool, m('execute'));
    agArrow(p, 'M545 480 H600 M580 460 L600 480 L580 500', m('intent'));
    agArrow(p, 'M1025 480 H1080 M1060 460 L1080 480 L1060 500', m('execute'), AG.tool);
    agNote(p, '模型说“请调用”；宿主程序负责真正调用。', m('execute') + 1);
  }],
  ['first', '第一轮：先统计', (m) => {
    const p = agBase(5, '第一轮：先获取事实', '演示流程与数字来自文章示例，不代表本次真实运行');
    agCard(p, 90, 285, 760, 140, '用户目标', ['统计 Python 文件，并写入 count.txt'], AG.model, m('task'));
    agCard(p, 90, 450, 760, 205, '工具调用 → 程序执行', ["find . -name '*.py' | wc -l", 'execute_bash(command=...)'], AG.tool, m('call'));
    agHistory(p, ['user：统计并写入', 'assistant：请求统计', 'tool：42（示例值）'], m('history'));
    const result = G(p);
    agText(result, '42', 800, 560, 68, AG.tool, 'end', 700);
    agReveal(result, m('result'));
    agPacket(p, '结果 42', [800, 625], [1200, 625], m('history'), AG.history);
    agNote(p, '不是模型猜出数量，而是工具执行后返回数量。', m('history') + 1.8);
  }],
  ['second', '第二轮：再写文件', (m) => {
    const p = agBase(6, '第二轮：带着结果，再决定下一步', '有了数量，模型才提出写入请求');
    agHistory(p, ['user：统计并写入', 'assistant → tool：统计', 'tool：42（示例值）', 'assistant → tool：写入', 'tool：写入成功'], m('history'), [m('history'), m('history'), m('history'), m('write'), m('success')]);
    agCard(p, 90, 285, 760, 290, 'write_file', ['path: count.txt', 'content: Python files: 42', 'Python 执行实际文件写入'], AG.tool, m('write'));
    const file = G(p);
    mk('rect', {x: 90, y: 605, width: 760, height: 85, rx: 16, fill: '#13796c'}, file);
    agText(file, 'count.txt  ✓  写入成功', 470, 659, 32, '#ffffff', 'middle', 650);
    agReveal(file, m('success'));
    agPacket(p, '执行结果', [820, 645], [1190, 645], m('success') + .5, AG.history);
    agNote(p, '这一步由模型根据历史决定，不是程序预先写死的任务顺序。', m('success') + 2);
  }],
  ['stop', '第三轮：返回与停止', (m) => {
    const p = agBase(7, '第三轮：没有工具调用，就返回答案', '这是最小实现的停止条件，不是正确性的证明');
    agCard(p, 90, 310, 665, 300, '模型返回普通文本', ['“已统计完成，', '结果已写入 count.txt。”', 'tool_calls 为空 → 返回'], AG.model, m('answer'));
    agCard(p, 865, 310, 645, 300, '另一条停止路径', ['达到 max_iterations', '返回迭代上限提示', '防止无限循环'], AG.tool, m('limit'));
    agNote(p, '停下来 ≠ 一定做对。需要时检查文件与执行结果。', m('limit') + 3, AG.tool);
  }],
  ['messages', '工作记录如何接上每一轮', (m) => {
    const p = agBase(8, 'messages：本次任务的工作记录', '不是每一轮重新开始，而是把行动与观察一起交回模型');
    const rows = ['用户：统计并写入', '模型：请求统计 → 工具：42', '模型：请求写入 → 工具：成功'];
    rows.forEach((row, i) => agCard(p, 100, 280 + i * 130, 890, 112, row, [], AG.history, m('record') + i * .65));
    agCard(p, 1110, 350, 390, 245, '下一轮模型', ['看到完整记录', '再决定下一步'], AG.model, m('feedback'));
    agArrow(p, 'M1010 460 H1090 M1070 440 L1090 460 L1070 480', m('feedback'), AG.history);
    agPacket(p, '历史记录', [1010, 520], [1300, 520], m('feedback') + .4, AG.history);
    agNote(p, '这里仅有运行内上下文；跨次记忆，留到下一篇。', m('temporary'));
  }],
  ['boundary', '能动手，也需要边界', (m) => {
    const p = agBase(9, '最小闭环，离可靠使用还有边界', '约 100 行帮助看清机制，不代表工程能力已经齐全');
    agCard(p, 90, 310, 650, 300, '强能力，也有风险', ['任意 shell 命令', '读取敏感文件', '覆盖重要内容'], AG.tool, m('risk'));
    agCard(p, 860, 310, 650, 300, '需要补上的约束', ['工具权限与参数检查', '敏感操作确认', '结果验证与运行隔离'], AG.model, m('guard'));
    agNote(p, '迭代上限只管次数，不负责权限与安全。', m('guard') + 1, AG.tool);
  }],
  ['wrap', '决定、行动、观察', (m) => {
    const p = agBase(10, '先抓住这条闭环，再看复杂 Agent', '从零开始理解 Agent（一）  ·  工具与循环');
    agCard(p, 90, 330, 420, 230, '大模型', ['负责决定'], AG.model, m('formula'));
    agCard(p, 590, 330, 420, 230, '工具', ['负责执行'], AG.tool, m('formula') + .8);
    agCard(p, 1090, 330, 420, 230, '循环', ['带着结果继续'], AG.history, m('formula') + 1.6);
    agArrow(p, 'M530 445 H570 M550 425 L570 445 L550 465', m('formula') + .4);
    agArrow(p, 'M1030 445 H1070 M1050 425 L1070 445 L1050 465', m('formula') + 1.2, AG.tool);
    agArrow(p, 'M1300 590 V665 H300 V590 M280 610 L300 590 L320 610', m('key'), AG.history);
    agReveal(agText(p, '决定 → 行动 → 观察 → 再决定', 800, 640, 37, AG.ink, 'middle', 650), m('key'));
    agNote(p, '下一篇：Memory，让任务记录跨越一次运行。', m('key') + 3);
  }]
].map(([id, title, run]) => ({id, title, run}));
boot();
