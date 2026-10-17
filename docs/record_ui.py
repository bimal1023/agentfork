"""Record a narrated demo video of the agentfork web UI.

    pip install playwright                 # uses your installed Google Chrome
    python docs/record_ui.py               # OpenAI voice (needs OPENAI_API_KEY)
    python docs/record_ui.py --voice say   # free macOS voice
    python docs/record_ui.py --voice none  # captions only

Records one real run of examples/refund_agent_cents.py into a temporary folder,
starts the UI on it, walks through finding the bug and testing fixes, and writes
docs/ui-demo-1440p.mp4 (sharpest), docs/ui-demo.mp4 (1080p, for social posts), both
with narration, and docs/ui-demo.gif (for the README). Each caption stays on screen until its narration finishes, so voice and
video stay in sync. A recording costs about $0.01 in API calls.
"""
import argparse, base64, hashlib, inspect, os, re, shutil, socket, subprocess, sys, tempfile, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs"
WIDTH, HEIGHT = 1280, 720
SCALE = 2  # render at 2x pixel density, like a Retina screen, for sharp text
SYSTEM = "You are a support agent. Look up the order, then refund the full order amount in USD."
FIX = " Order amounts from the API are in cents; divide by 100 before refunding."
VOICE_STYLE = "Upbeat, friendly narrator for a short developer product demo. Brisk pace, no long pauses, clear and confident."
# Trim silence at both ends and speed up slightly so the narration fits a short social video.
TIGHTEN = ("silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
           "silenceremove=start_periods=1:start_threshold=-45dB,areverse,atempo=1.12")

# Caption on screen -> what the narrator says, when the two differ.
SPOKEN = {
    "agentfork: fork your agent at any step, test fixes with evidence":
        "Agent fork. Fork your agent at any step, and test fixes with evidence.",
}

CURSOR_AND_CAPTIONS = """
window.addEventListener('DOMContentLoaded', () => {
  const cursor = document.createElement('div');
  cursor.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24"><path d="M5 3l14 8-6 1.5L10 19z" fill="#17202b" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  cursor.style.cssText = 'position:fixed;z-index:100000;left:-50px;top:-50px;pointer-events:none;transition:transform .12s';
  document.body.appendChild(cursor);
  document.addEventListener('mousemove', e => { cursor.style.left = e.clientX - 5 + 'px'; cursor.style.top = e.clientY - 3 + 'px'; }, true);
  document.addEventListener('mousedown', () => cursor.style.transform = 'scale(.8)', true);
  document.addEventListener('mouseup', () => cursor.style.transform = '', true);

  const cap = document.createElement('div');
  cap.style.cssText = 'position:fixed;z-index:99999;left:50%;bottom:18px;transform:translateX(-50%);max-width:80%;' +
    'background:rgba(23,32,43,.58);-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);color:#fff;' +
    'font:600 20px/1.35 "Instrument Sans",sans-serif;padding:8px 18px;border-radius:8px;' +
    'opacity:0;transition:opacity .3s;text-align:center;pointer-events:none';
  document.body.appendChild(cap);
  window.__caption = text => { cap.style.opacity = text ? 1 : 0; if (text) cap.textContent = text; };
});
"""

def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout)

class Narrator:
    """Speaks captions as audio clips, cached in docs/.voice so re-recording doesn't pay twice."""
    def __init__(self, voice):
        self.voice = voice
        self.cache = OUT / ".voice"
        self.cache.mkdir(exist_ok=True)
        if voice == "openai":
            from openai import OpenAI
            self.client = OpenAI()

    def clip(self, text):
        if self.voice == "none":
            return None, 0.0
        spoken = SPOKEN.get(text, text)
        key = hashlib.sha1(f"{self.voice}|{VOICE_STYLE}|{spoken}".encode()).hexdigest()[:16]
        path = self.cache / f"{key}.m4a"
        if not path.exists():
            raw = self.cache / f"{key}.raw.{'mp3' if self.voice == 'openai' else 'aiff'}"
            if self.voice == "openai":
                audio = self.client.audio.speech.create(model="gpt-4o-mini-tts", voice="coral", input=spoken,
                                                        instructions=VOICE_STYLE, response_format="mp3")
                raw.write_bytes(audio.content)
            else:
                subprocess.run(["say", "-v", "Samantha", "-r", "185", "-o", str(raw), spoken], check=True)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-af", TIGHTEN, str(path)], check=True)
            raw.unlink()
        return path, duration(path)

class Screencast:
    """Captures the page frame by frame straight from Chrome at full pixel density.

    Sharper than Playwright's built-in video, which records at 1x and compresses heavily.
    """
    def __init__(self, page, folder):
        self.folder, self.frames, self.ended = folder, [], None  # frames: (wall-clock time, path)
        folder.mkdir(parents=True)
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._frame)
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 95, "everyNthFrame": 1,
                                               "maxWidth": WIDTH * SCALE, "maxHeight": HEIGHT * SCALE})

    def _frame(self, event):
        path = self.folder / f"{len(self.frames):06d}.jpg"
        path.write_bytes(base64.b64decode(event["data"]))
        self.frames.append((time.time(), path))
        self.cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})

    @property
    def start(self):
        return self.frames[0][0]

    def stop(self):
        self.cdp.send("Page.stopScreencast")
        self.ended = time.time()

    def sequence(self, fps):
        """Image-sequence pattern at a constant `fps`: each slot links to the frame on screen at that moment.

        (ffmpeg's concat input can't be used: it shows every image for at least 1/25 s, and Chrome sends
        frames every 1/60 s while things move, so the video would drift behind the narration.)
        """
        seq = self.folder / "seq"
        seq.mkdir()
        i, slot = 0, 0
        while self.start + slot / fps < self.ended:
            now = self.start + slot / fps
            while i + 1 < len(self.frames) and self.frames[i + 1][0] <= now:
                i += 1
            (seq / f"{slot:06d}.jpg").symlink_to(self.frames[i][1])
            slot += 1
        return str(seq / "%06d.jpg")

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def record_run(db_dir):
    env = dict(os.environ, AGENTFORK_DIR=str(db_dir))
    subprocess.run([sys.executable, str(ROOT / "examples" / "refund_agent_cents.py")], env=env, check=True)

def start_server(port):
    import uvicorn
    from agentfork.server import app
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server

def walkthrough(page, caption, port):
    def show(selector, hold=600, block="center"):
        page.locator(selector).first.evaluate(f"el => el.scrollIntoView({{behavior: 'smooth', block: '{block}'}})")
        page.wait_for_timeout(hold)

    def click(selector, hold=500):
        el = page.locator(selector).first
        el.scroll_into_view_if_needed()
        box = el.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=30)
        page.wait_for_timeout(250)
        el.click()
        page.wait_for_timeout(hold)

    page.goto(f"http://127.0.0.1:{port}/")
    page.wait_for_selector("#step-3")
    page.wait_for_timeout(500)
    page.mouse.move(WIDTH * 0.6, HEIGHT * 0.4)
    caption("A refund agent just refunded $4,999 for a $49.99 laptop", 600)
    click("[data-guide-close]", 300)

    caption("Every LLM and tool call is recorded, step by step", 300)
    show("#step-2", 600)
    caption("The order API returns 4999, in cents", 400)
    show("#step-3", 300)
    caption("At step 3, the model refunds 4999 dollars. That's the bug.", 500)

    caption("So let's test several fixes at that step", 0)
    click("#step-3 [data-action=sweep]", 300)
    # Bring the whole form into view once, so nothing jumps while it's filled in.
    show("#step-3 .panel", 900, block="start")
    click("#step-3 .seg [data-kind=system]", 300)
    caption("Change 1 keeps the original prompt. Change 2 adds one sentence.", 0)
    click("#step-3 [data-add]", 300)
    second = page.locator("#step-3 [data-v]").nth(1)
    second.fill(SYSTEM)  # leaves the cursor at the end; pressing End would scroll the page
    second.type(FIX, delay=18)
    page.wait_for_timeout(400)
    click("#step-3 input[name=expect]", 200)
    page.keyboard.type("49.99", delay=90)
    page.wait_for_timeout(200)
    caption("A run passes if the final answer contains 49.99", 600)

    caption("Earlier steps replay from cache, and the runs go four at a time", 0)
    click("#step-3 button[type=submit]", 0)
    page.wait_for_selector("#step-3 .results table", timeout=180_000)
    show("#step-3 .results", 600)
    caption("You get pass rates, cost, and example output for every change", 600)
    show("#step-3 .verdict", 300)
    caption("The one-sentence fix passes every time", 600)

    click("#step-3 .verdict [data-goto]", 600)
    show("#step-3", 300)
    caption("Open a fixed run, and now the model refunds 49.99", 600)
    click("[data-cmp]", 600)
    show(".cmp tr.first", 300)
    caption("Compare the two runs, and they split exactly at step 3", 600)
    caption("agentfork: fork your agent at any step, test fixes with evidence", 1200)

def main():
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--voice", choices=["openai", "say", "none"], default="openai")
    args = parser.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("Set OPENAI_API_KEY: the demo records a real run and a real sweep.")

    narrator = Narrator(args.voice)
    # Make every clip before recording; generating one mid-recording would leave a silent gap.
    for text in re.findall(r'caption\("([^"]+)"', inspect.getsource(walkthrough)):
        narrator.clip(text)
    work = Path(tempfile.mkdtemp(prefix="agentfork-demo-"))
    os.environ["AGENTFORK_DIR"] = str(work / "db")
    record_run(work / "db")
    port = free_port()
    server = start_server(port)
    cues = []  # (wall-clock time, audio clip)

    with sync_playwright() as p:
        # Without an explicit window size, Chrome renders the page shorter than the frame.
        browser = p.chromium.launch(channel="chrome", args=[f"--window-size={WIDTH},{HEIGHT}"])
        context = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=SCALE)
        context.add_init_script(CURSOR_AND_CAPTIONS)
        page = context.new_page()
        cast = Screencast(page, work / "frames")

        def caption(text, pause):
            """Show a caption, speak it, and hold until the narration ends plus `pause` ms."""
            clip, seconds = narrator.clip(text)
            page.evaluate("t => window.__caption(t)", text)
            if clip:
                cues.append((time.time(), clip))
            page.wait_for_timeout(int(seconds * 1000) + pause + (0 if clip else 1800))

        walkthrough(page, caption, port)
        cast.stop()
        context.close()
        browser.close()
    server.should_exit = True

    master, mp4, gif = OUT / "ui-demo-1440p.mp4", OUT / "ui-demo.mp4", OUT / "ui-demo.gif"
    w, h = WIDTH * SCALE, HEIGHT * SCALE
    fps = 30
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", cast.sequence(fps)]
    for _, clip in cues:
        cmd += ["-i", str(clip)]
    graph = f"[0:v]scale={w}:{h}:flags=lanczos,format=yuv420p[v]"
    if cues:
        graph += "".join(f";[{i + 1}:a]adelay={int((t - cast.start) * 1000)}:all=1[a{i}]" for i, (t, _) in enumerate(cues))
        graph += ";" + "".join(f"[a{i}]" for i in range(len(cues))) + f"amix=inputs={len(cues)}:normalize=0[voice]"
        cmd += ["-filter_complex", graph, "-map", "[v]", "-map", "[voice]", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-filter_complex", graph, "-map", "[v]"]
    cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", "16", "-movflags", "+faststart", str(master)]
    subprocess.run(cmd, check=True)
    # 1080p for social posts: sites re-compress anything larger, and downscaling from 2x keeps text crisp.
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(master), "-vf", "scale=1920:1080:flags=lanczos",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-c:a", "copy", "-movflags", "+faststart",
                    str(mp4)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4), "-vf",
                    "fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
                    str(gif)], check=True)
    shutil.rmtree(work, ignore_errors=True)  # raw frames and the throwaway run database
    print(f"Wrote {master}, {mp4} ({duration(mp4):.0f}s, {len(cues)} narration clips) and {gif}")

if __name__ == "__main__":
    main()
