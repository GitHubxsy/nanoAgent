"""Build short, word-aligned single-line captions from the TTS word cache."""
import json
import re


def stamp(seconds, ass=False):
    factor = 100 if ass else 1000
    n = round(seconds * factor)
    h, n = divmod(n, 3600 * factor)
    m, n = divmod(n, 60 * factor)
    s, fraction = divmod(n, factor)
    return f'{h}:{m:02d}:{s:02d}.{fraction:02d}' if ass else f'{h:02d}:{m:02d}:{s:02d},{fraction:03d}'


def chunks(text):
    start = 0
    while start < len(text):
        width, end = 0, start
        punctuation = []
        while end < len(text):
            token = re.match(r'[A-Za-z0-9]+|.', text[end:]).group()
            units = sum(1 if ord(c) < 128 else 2 for c in token)
            if width + units > 44 and end > start:
                break
            width += units
            end += len(token)
            if token in '，。？！；：、' and width >= 18:
                punctuation.append(end)
            if token in '。？！':
                break
        if end < len(text) and text[end - 1] not in '。？！' and punctuation:
            end = punctuation[-1]
        yield start, end, text[start:end]
        start = end


def build(root, speed):
    content = root / 'content/agent-first/ch01'
    source = json.loads((content / 'narration.zh.json').read_text())
    cache = json.loads((content / 'narration.zh.timings.json').read_text())
    offset, cues = 0.0, []
    for beat, raw in source['beats'].items():
        text = re.sub(r'\[\[\w+\]\]', '', raw)
        data = cache[beat]
        cursor, positions = 0, []
        for t, word in data['words']:
            i = text.find(word, cursor)
            if i >= 0:
                positions.append((i, t))
                cursor = i + len(word)
        pieces = list(chunks(text))
        starts = [next((t for pos, t in positions if pos >= begin), data['dur'])
                  for begin, _, _ in pieces]
        for i, (_, _, line) in enumerate(pieces):
            begin = starts[i]
            end = starts[i + 1] if i + 1 < len(starts) else data['dur']
            if end <= begin:
                raise ValueError(f'Caption has no duration: {beat}: {line}')
            cues.append(((offset + begin) / speed, (offset + end) / speed, line))
        # Match the 30 fps source export's rounded per-beat duration, including its hold.
        offset += round((data['dur'] + .6) * 30) / 30
    assert ''.join(c[2] for c in cues) == re.sub(r'\[\[\w+\]\]', '', ''.join(source['beats'].values()))
    exports = root / 'exports'
    srt = exports / 'agent-01-papermorph-1.15x.srt'
    srt.write_text('\n\n'.join(f'{i}\n{stamp(a)} --> {stamp(b)}\n{line}'
                              for i, (a, b, line) in enumerate(cues, 1)) + '\n', encoding='utf-8')
    ass = exports / 'captions.ass'
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Bottom,PingFang SC,32,&H00FFFFFF,&H00FFFFFF,&H00203835,&H60000000,0,0,0,0,100,100,0,0,1,1.5,0,2,80,80,18,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    ass.write_text(header + ''.join(f'Dialogue: 0,{stamp(a, True)},{stamp(b, True)},Bottom,,0,0,0,,{line}\n'
                                    for a, b, line in cues), encoding='utf-8')
    print(f'{len(cues)} single-line captions, 32px, bottom centre, 18px bottom margin')
    return ass
