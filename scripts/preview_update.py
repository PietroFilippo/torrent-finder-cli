"""Export a browser replay of the real terminal renderer; never runs an update.

Run from the repository root: python -m scripts.preview_update
Then open dist/update-preview/index.html in a browser.
"""

import io
import json
from pathlib import Path

from rich.console import Console
from rich.terminal_theme import MONOKAI

from torrent_finder.ui.update_progress import preview_view, update_panel


def export_preview(destination=Path("dist/update-preview/index.html")):
    frames = {}
    for width in (48, 80):
        for outcome in ("success", "failure"):
            key = f"{width}-{outcome}"
            frames[key] = []
            for tick in range(81):
                elapsed = tick / 8
                console = Console(file=io.StringIO(), width=width, record=True, color_system="truecolor", legacy_windows=False)
                console.print(update_panel(preview_view(elapsed, outcome), min(elapsed, 7), min(72, width)))
                frames[key].append(console.export_html(inline_styles=True, code_format="{code}", theme=MONOKAI))
    html = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Torrent Finder — Update preview</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#0b0e14;color:#e4eaf5;font:16px system-ui,sans-serif}
main{max-width:1100px;margin:60px auto;padding:0 28px}h1{font-size:32px;margin:12px 0}
.eyebrow{color:#79dce3;letter-spacing:.13em;font-size:12px;font-weight:700}p{color:#aeb9cc;line-height:1.6;max-width:790px}
.controls{display:flex;gap:12px;flex-wrap:wrap;margin:28px 0 16px;align-items:center}
button,select{background:#1e2737;color:#e4eaf5;border:1px solid #41516c;border-radius:8px;padding:10px 14px;font:inherit}
button{cursor:pointer;background:#a7edf0;color:#102325;font-weight:650}button:focus-visible,select:focus-visible{outline:3px solid #fff}
label{display:flex;align-items:center;gap:8px}.terminal{border:1px solid #33405a;border-radius:12px;overflow:hidden;background:#0c0c0c}
.titlebar{padding:12px 18px;background:#192030;font-size:13px;color:#bbc8dd;display:flex;justify-content:space-between}
.badge{color:#ffd880}.screen{overflow-x:auto;padding:18px}pre{margin:0;font:15px/1.35 Consolas,'Courier New',monospace;min-height:260px}
.note{font-size:14px}code{color:#c0eef0}
</style>
<main><div class="eyebrow">TORRENT FINDER · VISUAL PREVIEW</div>
<h1>See the update screen now.</h1>
<p>This replay uses frames from the app’s actual terminal renderer. The moving bar shows activity;
it becomes full only when the update succeeds. No percentage is estimated.</p>
<div class="controls"><button id="replay">Replay animation</button>
<label>Outcome <select id="outcome"><option value="success">Success</option><option value="failure">Failure</option></select></label>
<label>Terminal <select id="width"><option value="80">Normal · 80 columns</option><option value="48">Compact · 48 columns</option></select></label></div>
<div class="terminal"><div class="titlebar"><span>Update progress</span><span class="badge">PREVIEW ONLY · NOTHING IS INSTALLED</span></div>
<div class="screen"><pre id="frame" aria-label="Terminal update preview"></pre></div></div>
<p class="note">After a successful Windows update, Torrent Finder reopens automatically after three seconds and the updater window closes.
Closing the progress display early does not stop the update or automatic reopening. This preview never opens the app.</p>
<p class="note">Try it in your terminal: <code>python -m torrent_finder --preview-update</code><br>
Preview a failure: <code>python -m torrent_finder --preview-update failure</code></p></main>
<script>
const frames=FRAMES_JSON;
const frame=document.getElementById('frame'), outcome=document.getElementById('outcome'), width=document.getElementById('width');
let start=performance.now(), animation;
function replay(){cancelAnimationFrame(animation);start=performance.now();animation=requestAnimationFrame(draw);}
document.getElementById('replay').onclick=replay;outcome.onchange=replay;width.onchange=replay;
function draw(now){const series=frames[width.value+'-'+outcome.value];const tick=Math.min(series.length-1,Math.floor((now-start)/125));frame.innerHTML=series[tick];if(tick<series.length-1)animation=requestAnimationFrame(draw);}
replay();
</script></html>'''
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html.replace("FRAMES_JSON", json.dumps(frames)), encoding="utf-8")
    return destination.resolve()


if __name__ == "__main__":
    print(export_preview())
