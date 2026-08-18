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


def open_terminal(path):
    """Open a terminal emulator AT `path` and nothing else -- never types or runs a command
    inside it. Returns (ok, message). The terminal binary is always chosen HERE from a fixed
    per-OS allowlist, never from caller input, and every launch is an argument list (never
    shell=True, never a path interpolated into a string a shell would re-parse)."""
    if not os.path.isdir(path):
        return False, "not a directory"
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-a", "Terminal", path])
            return True, "opened"
        if os.name == "nt":
            if shutil.which("wt"):
                subprocess.Popen(["wt", "-d", path])
            else:
                subprocess.Popen(["cmd", "/c", "start", "powershell", "-NoExit", "-Command", "Set-Location", path])
            return True, "opened"
        if shutil.which("x-terminal-emulator"):
            subprocess.Popen(["x-terminal-emulator", f"--working-directory={path}"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, "opened"
        if shutil.which("gnome-terminal"):
            subprocess.Popen(["gnome-terminal", f"--working-directory={path}"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, "opened"
        if shutil.which("konsole"):
            subprocess.Popen(["konsole", "--workdir", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, "opened"
        if shutil.which("xterm"):
            subprocess.Popen(["xterm"], cwd=path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, "opened"
        return False, "no terminal emulator found"
    except Exception as e:
        return False, str(e)


def notify(title, body, urgent=False):
    """Best-effort desktop notification. Silent no-op if unsupported.
    Text is passed OUT-OF-BAND (environment variables), never interpolated into a script."""
    env = {**os.environ, "CABINA_TITLE": str(title), "CABINA_BODY": str(body)}
    try:
        if sys.platform == "darwin":
            script = 'display notification (system attribute "CABINA_BODY") with title (system attribute "CABINA_TITLE")'
            if urgent:
                script += ' sound name "Basso"'
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5, env=env)
        elif os.name == "nt":
            ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
                  "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                  "$t.GetElementsByTagName('text')[0].AppendChild($t.CreateTextNode($env:CABINA_TITLE)) > $null;"
                  "$t.GetElementsByTagName('text')[1].AppendChild($t.CreateTextNode($env:CABINA_BODY)) > $null;"
                  "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('cabina').Show([Windows.UI.Notifications.ToastNotification]::new($t))")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=10, env=env)
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
