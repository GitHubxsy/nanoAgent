"""Create a pitch-preserving 1.15x cut with synchronized subtitles."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
EXPORTS = ROOT / 'exports'
SPEED = 1.15


def retime(match):
    h, m, s, ms = map(int, match.groups())
    total = round(((h * 3600 + m * 60 + s) * 1000 + ms) / SPEED)
    return f'{total // 3600000:02d}:{total // 60000 % 60:02d}:{total // 1000 % 60:02d},{total % 1000:03d}'


subtitles = EXPORTS / 'agent-01-papermorph-1.15x.srt'
subtitles.write_text(re.sub(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})', retime,
                           (EXPORTS / 'ch01.srt').read_text(encoding='utf-8')), encoding='utf-8')
subprocess.run([
    'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
    '-i', str(EXPORTS / 'agent-01-papermorph.mp4'), '-i', str(subtitles),
    '-map', '0:v:0', '-map', '0:a:0', '-map', '1:0',
    '-vf', f'setpts=(PTS-STARTPTS)/{SPEED}', '-af', f'atempo={SPEED},asetpts=N/SR/TB',
    '-r', '30', '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', '-c:s', 'mov_text',
    '-metadata:s:s:0', 'language=zho', '-disposition:s:0', 'default',
    '-movflags', '+faststart', str(EXPORTS / 'agent-01-papermorph-1.15x.mp4'),
], check=True)
