"""`project-os fleet` — terminal TUI (curses, stdlib) over the live provider + cached scan."""
import time, sys, os
try:
    import curses
except ImportError:          # Windows: no curses in the stdlib
    curses = None
from . import live as LIVE, scan
from .roster import Roster


def available():
    return curses is not None

ICON = {"working": "●", "done": "✓", "idle": "○", "unknown": "·"}
VIEWS = ["Live", "Agents", "Projects"]


def run(cfg):
    if not available():
        print("project-os fleet needs a curses-capable terminal (not available on this Python/OS). Use `project-os` for the web UI.")
        return 2
    prov = LIVE.get(cfg)
    data = scan.ensure(cfg)
    rows_agents, items = Roster(cfg, data).load(refresh_usage=False)
    state = {"view": 0, "sel": [0, 0, 0], "top": [0, 0, 0], "live": prov.list(), "t": 0, "msg": "", "msg_t": 0}

    def rows():
        v = state["view"]
        if v == 0:
            return [(a["status"], f'{a["agent"]:<7} {a["workspace"][:20]:<21} {(a["task"] or "—")[:60]}', a) for a in state["live"]["agents"]]
        if v == 1:
            out = []
            for proj, r, path in rows_agents:
                if not r.is_agent:
                    continue
                u = items.get(r.name, {})
                out.append((r.category, f'{r.name[:26]:<27} {proj[:18]:<19} {(r.fields.get("model") or "—")[:6]:<7} {u.get("n_total", 0):>4}  {r.category}', r))
            return out
        return [("valid", f'{p["name"][:22]:<23} {len(p.get("agents", [])):>3}ag {len(p.get("skills", [])):>3}sk', p) for p in data.get("projects", [])]

    def draw(scr):
        scr.erase(); H, W = scr.getmaxyx()
        if H < 6 or W < 40:
            scr.addstr(0, 0, "terminal too small"[:W - 1]); scr.refresh(); return
        C = curses.color_pair
        rs = rows(); v = state["view"]
        state["sel"][v] = max(0, min(state["sel"][v], len(rs) - 1)) if rs else 0
        cnt = {}
        for a in state["live"]["agents"]:
            cnt[a["status"]] = cnt.get(a["status"], 0) + 1
        head = f" PROJECT-OS  {len(state['live']['agents'])} live agents · provider: {prov.name} "
        scr.addstr(0, 0, head[:W - 1], C(6) | curses.A_BOLD)
        x = len(head) + 1
        for k in ("working", "done", "idle"):
            if cnt.get(k) and x < W - 14:
                s = f"{ICON[k]} {cnt[k]} {k}  "; scr.addstr(0, x, s, C({"working": 2, "done": 3, "idle": 5}[k])); x += len(s)
        x = 1
        for i, n in enumerate(VIEWS):
            lbl = f" {i+1} {n} "
            if x + len(lbl) < W:
                scr.addstr(1, x, lbl, C(1) | curses.A_BOLD if i == v else C(5)); x += len(lbl) + 1
        scr.hline(2, 0, curses.ACS_HLINE, W)
        body = H - 5
        if state["sel"][v] < state["top"][v]: state["top"][v] = state["sel"][v]
        if state["sel"][v] >= state["top"][v] + body: state["top"][v] = state["sel"][v] - body + 1
        for i, (st, txt, _) in enumerate(rs[state["top"][v]: state["top"][v] + body]):
            y = 3 + i; cur = state["top"][v] + i == state["sel"][v]
            attr = curses.A_REVERSE if cur else 0
            col = {"working": 2, "done": 3, "invalid": 4, "warnings": 2, "valid": 3}.get(st, 5)
            try:
                scr.addstr(y, 1, ICON.get(st, "●" if st == "valid" else "·"), C(col) | attr)
                scr.addstr(y, 3, txt[:W - 4], attr)
            except curses.error:
                pass
        if not rs:
            scr.addstr(4, 2, (state["live"].get("reason") or "nothing to show")[:W - 3], C(5))
        scr.hline(H - 2, 0, curses.ACS_HLINE, W)
        foot = " ↑↓ move · ↵ focus (Live) · 1-3 views · q quit"
        if state["msg"] and time.time() - state["msg_t"] < 4:
            foot = " " + state["msg"]
        scr.addstr(H - 1, 0, foot[:W - 1], C(5)); scr.refresh()

    def main(scr):
        curses.use_default_colors()
        for i, c in enumerate([curses.COLOR_GREEN, curses.COLOR_YELLOW, curses.COLOR_GREEN, curses.COLOR_RED, curses.COLOR_BLACK, curses.COLOR_CYAN], 1):
            curses.init_pair(i, c, -1)
        curses.init_pair(5, 8, -1)
        try: curses.curs_set(0)
        except curses.error: pass
        scr.timeout(250)
        while True:
            draw(scr)
            ch = scr.getch(); v = state["view"]
            if ch == -1:
                if time.time() - state["t"] > 1:
                    state["live"] = prov.list(); state["t"] = time.time()
                continue
            if ch in (ord("q"), 27): break
            elif ch in (curses.KEY_DOWN, ord("j")): state["sel"][v] += 1
            elif ch in (curses.KEY_UP, ord("k")): state["sel"][v] = max(0, state["sel"][v] - 1)
            elif ch in (ord("1"), ord("2"), ord("3")): state["view"] = ch - ord("1")
            elif ch == ord("\t"): state["view"] = (v + 1) % 3
            elif ch in (10, 13) and v == 0:
                rs = rows()
                if rs:
                    ok, m = prov.focus(rs[state["sel"][0]][2]["pane"]); state["msg"], state["msg_t"] = m, time.time()
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
