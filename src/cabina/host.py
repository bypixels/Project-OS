"""Platform glue: open files/folders, desktop notifications, locate the claude binary."""
import os, shutil, subprocess, sys

HOME = os.path.expanduser("~")


def default_dirs():
    """Platform-aware defaults. Tool homes are ~/.claude and ~/.codex on every OS
    (that is where the tools put them); cabina's own dirs follow each platform's convention."""
    if os.name == "nt":
        cfg = os.path.join(os.environ.get("APPDATA") or os.path.join(HOME, "AppData", "Roaming"), "cabina")
        st = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.join(HOME, "AppData", "Local"), "cabina")
    else:
        cfg = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config"), "cabina")
        st = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(HOME, ".local", "share"), "cabina")
    return {"config": cfg, "state": st,
            "claude_home": os.path.join(HOME, ".claude"), "codex_home": os.path.join(HOME, ".codex"),
            "roots": [os.path.join(HOME, "Documents"), os.path.join(HOME, "Desktop")]}


def has(tool):
    return shutil.which(tool) is not None


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
        elif os.name == "nt":
            ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
                  "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                  f"$t.GetElementsByTagName('text')[0].AppendChild($t.CreateTextNode('{title}')) > $null;"
                  f"$t.GetElementsByTagName('text')[1].AppendChild($t.CreateTextNode('{body}')) > $null;"
                  "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('cabina').Show([Windows.UI.Notifications.ToastNotification]::new($t))")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=10)
        elif shutil.which("notify-send"):
            subprocess.run(["notify-send", "-u", "critical" if urgent else "normal", title, body],
                           capture_output=True, timeout=5)
    except Exception:
        pass


def claude_bin(claude_home):
    """`claude` is often a shell alias, invisible to cron/launchd. Look in known places first."""
    cands = [os.path.join(claude_home, "local", "claude"), "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]
    if os.name == "nt":
        cands = [os.path.join(claude_home, "local", "claude.exe"), os.path.join(claude_home, "local", "claude.cmd")]
    for c in cands:
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
