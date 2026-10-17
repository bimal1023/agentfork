"""Record a demo video of the agentfork web UI.

    pip install playwright        # uses your installed Google Chrome
    python docs/record_ui.py      # needs OPENAI_API_KEY; costs about $0.01

Records one real run of examples/refund_agent_cents.py into a temporary folder,
starts the UI on it, walks through finding the bug and testing fixes, and writes
docs/ui-demo.mp4 (for social posts) and docs/ui-demo.gif (for the README).
"""
import os, socket, subprocess, sys, tempfile, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs"
WIDTH, HEIGHT = 1280, 720
SYSTEM = "You are a support agent. Look up the order, then refund the full order amount in USD."
FIX = " Order amounts from the API are in cents; divide by 100 before refunding."

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
  cap.style.cssText = 'position:fixed;z-index:99999;left:50%;bottom:28px;transform:translateX(-50%);max-width:80%;' +
    'background:#17202b;color:#fff;font:600 21px/1.35 "Instrument Sans",sans-serif;padding:12px 22px;border-radius:10px;' +
    'box-shadow:0 6px 24px rgba(0,0,0,.25);opacity:0;transition:opacity .3s;text-align:center;pointer-events:none';
  document.body.appendChild(cap);
  window.__caption = text => { cap.style.opacity = text ? 1 : 0; if (text) cap.textContent = text; };
});
"""

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

def main():
    from playwright.sync_api import sync_playwright

    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("Set OPENAI_API_KEY: the demo records a real run and a real sweep.")
    work = Path(tempfile.mkdtemp(prefix="agentfork-demo-"))
    os.environ["AGENTFORK_DIR"] = str(work / "db")
    record_run(work / "db")
    port = free_port()
    server = start_server(port)

    with sync_playwright() as p:
        # Without an explicit window size, Chrome renders the page shorter than the video frame.
        browser = p.chromium.launch(channel="chrome", args=[f"--window-size={WIDTH},{HEIGHT}"])
        context = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT},
                                      record_video_dir=str(work / "video"),
                                      record_video_size={"width": WIDTH, "height": HEIGHT})
        context.add_init_script(CURSOR_AND_CAPTIONS)
        page = context.new_page()

        def caption(text, hold=0):
            page.evaluate("t => window.__caption(t)", text)
            page.wait_for_timeout(hold)

        def show(selector, hold=600):
            page.locator(selector).first.evaluate("el => el.scrollIntoView({behavior: 'smooth', block: 'center'})")
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
        caption("A refund agent just refunded $4,999 for a $49.99 laptop", 2600)
        click("[data-guide-close]", 400)

        caption("Every LLM and tool call is recorded, step by step", 1200)
        show("#step-2", 1600)
        caption("The order API says 4999... in cents", 2200)
        show("#step-3", 400)
        caption("Step 3: the model refunds 4999 dollars. That's the bug.", 2600)

        caption("Test several fixes at that step", 600)
        click("#step-3 [data-action=sweep]", 600)
        click("#step-3 .seg [data-kind=system]", 900)
        caption("Change 1 keeps the original prompt. Change 2 adds one sentence.", 400)
        click("#step-3 [data-add]", 300)
        second = page.locator("#step-3 [data-v]").nth(1)
        second.fill(SYSTEM)
        second.press("End")
        second.type(FIX, delay=18)
        page.wait_for_timeout(500)
        click("#step-3 input[name=expect]", 200)
        page.keyboard.type("49.99", delay=90)
        caption("A run passes if the final answer contains 49.99", 1200)
        show("#step-3 .go", 1800)

        caption("Earlier steps replay from cache. Runs go 4 at a time.", 300)
        click("#step-3 button[type=submit]", 0)
        page.wait_for_selector("#step-3 .results table", timeout=180_000)
        caption("", 300)
        show("#step-3 .results", 900)
        caption("Pass rates, cost and example output for every change", 3200)
        show("#step-3 .verdict", 300)
        caption("The one-sentence fix passes every time", 2600)

        click("#step-3 .verdict [data-goto]", 900)
        caption("Open a fixed run", 300)
        show("#step-3", 1800)
        caption("Now the model refunds 49.99", 2200)
        click("[data-cmp]", 900)
        show(".cmp tr.first", 600)
        caption("Compare: the runs split exactly at step 3", 3000)
        caption("agentfork: fork your agent at any step, test fixes with evidence", 3200)

        video = page.video.path()
        context.close()
        browser.close()
    server.should_exit = True

    mp4, gif = OUT / "ui-demo.mp4", OUT / "ui-demo.gif"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-c:v", "libx264", "-preset", "slow",
                    "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-vf",
                    "fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
                    str(gif)], check=True)
    print(f"Wrote {mp4} and {gif}")

if __name__ == "__main__":
    main()
