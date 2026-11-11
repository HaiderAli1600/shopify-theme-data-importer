"""Launcher: server start, app window kholo (Edge/Chrome app mode), window band hone par exit."""
import argparse
import os
import shutil
import subprocess
import sys
import time
import traceback
import webbrowser

from .server import data_dir, start_server
from .version import APP_NAME

HEARTBEAT_TIMEOUT = 150      # minimize par browser timers dheemay ho jaate hain
BYE_GRACE = 6                # reload / navigation ke liye thora wait


def browser_candidates():
    env = os.environ.get
    paths = []
    for root in filter(None, [env("PROGRAMFILES(X86)"), env("PROGRAMFILES"), env("LOCALAPPDATA")]):
        paths += [os.path.join(root, "Microsoft", "Edge", "Application", "msedge.exe"),
                  os.path.join(root, "Google", "Chrome", "Application", "chrome.exe")]
    for name in ("msedge", "microsoft-edge", "google-chrome", "chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            paths.append(found)
    if sys.platform == "darwin":
        paths += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    return [p for p in dict.fromkeys(paths) if p and os.path.exists(p)]


def open_window(url):
    """App jaisa window (address bar ke baghair). Na mile to default browser."""
    profile = data_dir() / "window-profile"
    for exe in browser_candidates():
        try:
            flags = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW
            subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
                              "--no-default-browser-check", "--disable-sync", "--disable-features=Translate",
                              "--window-size=1440,920", "--window-position=80,40"],
                             creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return exe
        except OSError:
            continue
    webbrowser.open(url)
    return "default-browser"


def crash_box(msg):
    log = data_dir() / "crash.log"
    log.write_text(msg, "utf-8")
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f"Tool start nahi ho saka.\n\n{msg[-600:]}\n\nLog: {log}",
                                             APP_NAME, 0x10)
        except Exception:  # noqa: BLE001
            pass


def main(argv=None):
    ap = argparse.ArgumentParser(prog=APP_NAME)
    ap.add_argument("--no-window", action="store_true", help="sirf server (testing)")
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args(argv)
    app, httpd = start_server(args.port)
    url = f"http://127.0.0.1:{app.port}/?k={app.key}"
    if args.no_window:
        print(url, flush=True)
    else:
        open_window(url)
    started = time.time()
    try:
        while True:
            time.sleep(1)
            now = time.time()
            if args.no_window:
                continue
            if app.bye_at and now - app.bye_at > BYE_GRACE and app.last_ping < app.bye_at:
                break
            if not app.ever_pinged and now - started > 90:
                webbrowser.open(url)                                    # window nahi khula -- browser me kholo
                started = now + 10 ** 6
            if app.ever_pinged and now - app.last_ping > HEARTBEAT_TIMEOUT:
                break
    except KeyboardInterrupt:
        pass
    for job in app.jobs.running():
        job.cancel()
    time.sleep(0.5)
    httpd.shutdown()


def run():
    try:
        main()
    except Exception:  # noqa: BLE001
        crash_box(traceback.format_exc())
        raise


if __name__ == "__main__":
    run()
