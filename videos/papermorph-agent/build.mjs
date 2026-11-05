import {readFileSync, writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname, join} from 'node:path';

const root = dirname(fileURLToPath(import.meta.url));
const chapter = join(root, 'site/agent-first/ch01');
const code = readFileSync(join(chapter, 'lesson.js'), 'utf8');
// Papermorph's static checker reads beat declarations from the inline chapter.
writeFileSync(join(chapter, 'index.html'), `<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>从零开始理解 Agent（一）：工具与循环</title>
<link rel="stylesheet" href="../lib/engine.css">
<link rel="expect" href="#bar" blocking="render">
</head>
<body>
<script src="../lib/engine.js"></script>
<script src="audio/zh/timings.js"></script>
<script>
${code}
</script>
</body>
</html>
`);
