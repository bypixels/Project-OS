"""Platform glue: open files/folders, desktop notifications, locate the claude binary."""
import os, shutil, subprocess, sys


def open_path(path):
    """Open a file or folder with the OS default handler. Returns (ok, message)."""
    if not os.path.exists(path):
        return False, "does not exist"
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, "opened"
    except Exception as e:
        return False, str(e)


def notify(title, body, urgent=False):
    """Best-effort desktop notification. Silent no-op if unsupported."""
    try:
        if sys.platform == "darwin":
            snd = ' sound name "Basso"' if urgent else ""
            subprocess.run(["osascript", "-e", f'display notification "{body}" with title "{title}"{snd}'],
                           capture_output=True, timeout=5)
        elif shutil.which("notify-send"):
            subprocess.run(["notify-send", "-u", "critical" if urgent else "normal", title, body],
                           capture_output=True, timeout=5)
    except Exception:
        pass


def claude_bin(claude_home):
    """`claude` is often a shell alias, invisible to cron/launchd. Look in known places first."""
    for c in (os.path.join(claude_home, "local", "claude"), "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return shutil.which("claude")


def run(args, timeout=30):
    """Run a command; return stdout or '' on any failure."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""
