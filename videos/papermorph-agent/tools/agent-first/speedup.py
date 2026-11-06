"""Create a pitch-preserving 1.15x cut with synchronized subtitles."""
from pathlib import Path
import subprocess
import imageio_ffmpeg
from subtitles import build

ROOT = Path(__file__).resolve().parents[2]
EXPORTS = ROOT / 'exports'
SPEED = 1.15


ass = build(ROOT, SPEED)
output = EXPORTS / 'agent-01-papermorph-1.15x.mp4'
temporary = output.with_suffix('.tmp.mp4')
# Burn captions into the clean source; do not include a second, player-styled subtitle track.
subprocess.run([
    imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-y',
    '-i', str(EXPORTS / 'ch01.mp4'),
    '-map', '0:v:0', '-map', '0:a:0',
    '-vf', f"setpts=(PTS-STARTPTS)/{SPEED},ass='{ass}'", '-af', f'atempo={SPEED},asetpts=N/SR/TB',
    '-r', '30', '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
    '-movflags', '+faststart', str(temporary),
], check=True)
temporary.replace(output)
