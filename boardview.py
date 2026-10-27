"""
BoardView - read-only on-screen viewer for the MainBoard bookings.

    python boardview.py            # live data from the Access DB (settings in boarddata.py)
    python boardview.py --demo     # fake data, no database needed

Which engineer shows on which board, your initials and the zoom level are
kept in boardview_settings.json next to this file (Engineers & boards...).
"""
import sys
from datetime import date, datetime, timedelta
from collections import defaultdict

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox

from boarddata import (F_FITTERID, monday_of, fmt_num, fetch_week, fetch_fitters,
                       demo_week, demo_fitters, summarise_week, default_board)
from boardsettings import Settings, UNASSIGNED
from engineers_dialog import EngineersDialog

# ---- look ----
C = {
    "bg": "#ffffff", "grid": "#b9c3d2", "grid_light": "#dde3ec", "band": "#e3ecf8",
    "bar": "#3f86d4", "bar_fg": "#ffffff", "bar_btn": "#6aa7e8",
    "tools": "#eef3fa",
    "tab": "#dbe5f3", "tab_fg": "#333333", "tab_active": "#2f6fc0", "tab_unassigned": "#f6c26b",
    "head": "#d8e2f2", "head_fg": "#1f3b63", "date_bg": "#fbe8b0", "weekend": "#fff27a",
    "today_head": "#7fd17f", "today": "#eefaee", "today_band": "#d9efd9",
    "text": "#000000", "red": "#e00000", "dim": "#b8b8b8",
    "mine": "#00a651", "match": "#ff8c00", "select": "#2f6fc0",
}
KIND_COLOURS = {            # kind -> (text, background)
    "normal": (C["text"], None),
    "prov":   ("#ffffff", "#ff0000"),
    "wrs":    ("#000000", "#ffff00"),
    "both":   ("#e00000", "#ffff00"),
    "status": (C["red"], None),
}
FONT_FAMILY = "Segoe UI"
BASE_SIZES = {"reg": 9, "bold": 9, "small": 8, "head": 10, "headb": 10, "big": 13}

# base sizes at 100% zoom (pixels)
W_ID, W_NAME, W_JOB, W_HRS, W_TOTAL = 36, 225, 136, 34, 56
ROW_PAD, HEAD_H = 4, 44
ZOOM_MIN, ZOOM_MAX = 0.7, 2.0


def fit_text(font, text, avail):
    if font.measure(text) <= avail:
        return text
    while text and font.measure(text + "…") > avail:
        text = text[:-1]
    return text + "…"


class Tooltip:
    def __init__(self, master):
        self.win = tk.Toplevel(master)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.label = tk.Label(self.win, justify="left", bg="#ffffe1", relief="solid", bd=1,
                              padx=6, pady=4, font=(FONT_FAMILY, 9))
        self.label.pack()

    def show(self, x, y, text):
        self.label.configure(text=text)
        self.win.geometry(f"+{x + 14}+{y + 14}")
        self.win.deiconify()
        self.win.lift()

    def hide(self):
        self.win.withdraw()


class BoardView(tk.Tk):
    def __init__(self, demo=False):
        super().__init__()
        self.demo = demo
        self.title("BoardView" + (" (demo data)" if demo else ""))
        self.geometry("1600x880")
        self.configure(bg=C["bg"])

        self.settings = Settings()
        boards = self.settings.boards
        last = self.settings["last_board"]
        self.board = last if last in boards + [UNASSIGNED] else (boards[0] if boards else UNASSIGNED)
        self.week_start = monday_of(date.today())
        self.cache = {}            # week_start -> summarise_week(...)
        self.booking_info = {}     # canvas tag -> (fitter, day, booking, mine)
        self.row_spans = []        # (y0, y1, fitter) for right-click
        self._after = {}
        self._tab_keys = None

        self.zoom = min(ZOOM_MAX, max(ZOOM_MIN, float(self.settings["zoom"] or 1.0)))
        self.fonts = {k: tkfont.Font(self, family=FONT_FAMILY, size=v,
                                     weight="bold" if k in ("bold", "headb", "big") else "normal")
                      for k, v in BASE_SIZES.items()}
        self._apply_zoom_fonts()

        self.stats_var = tk.StringVar()
        self.week_var = tk.StringVar()
        self.jump_var = tk.StringVar()
        self.info_var = tk.StringVar(value="Click a booking for details. Right-click an engineer to move them to another board.")
        self.initials_var = tk.StringVar(value=self.settings["my_initials"])
        self.mine_only_var = tk.BooleanVar(value=bool(self.settings["mine_only"]))
        self.find_var = tk.StringVar()
        self.zoom_var = tk.StringVar()

        self._build_tabs()
        self._build_bar()
        self._build_tools()
        self._build_grid()
        self._build_status()
        self.tooltip = Tooltip(self)

        self.initials_var.trace_add("write", lambda *a: self._debounce("initials", 300, self._initials_changed))
        self.find_var.trace_add("write", lambda *a: self._debounce("find", 200, self.render))
        self.bind("<F5>", lambda e: self.load(force=True))
        self.bind("<Prior>", lambda e: self.shift(-7))
        self.bind("<Next>", lambda e: self.shift(7))
        self.bind("<Control-f>", lambda e: (self.find_entry.focus_set(), "break"))
        self.bind("<Control-plus>", lambda e: self.set_zoom(self.zoom + 0.1))
        self.bind("<Control-equal>", lambda e: self.set_zoom(self.zoom + 0.1))
        self.bind("<Control-minus>", lambda e: self.set_zoom(self.zoom - 0.1))
        self.bind("<Control-0>", lambda e: self.set_zoom(1.0))
        for i in range(1, 10):
            self.bind(f"<Control-Key-{i}>", lambda e, i=i: self._tab_by_index(i - 1))
        self.protocol("WM_DELETE_WINDOW", self._close)

        if self.settings.load_error:
            self.after(100, lambda: messagebox.showwarning("Settings", self.settings.load_error))
        self.after(50, self.load)

    # ------------------------------------------------------------ chrome
    def _build_tabs(self):
        row = tk.Frame(self, bg=C["bg"]); row.pack(fill="x", padx=4, pady=(4, 0))
        self.tab_frame = tk.Frame(row, bg=C["bg"]); self.tab_frame.pack(side="left")
        ttk.Button(row, text="Engineers & boards…", command=self.open_engineers).pack(side="right", padx=4)
        self.tab_btns = {}

    def _bar_button(self, parent, text, cmd):
        b = tk.Button(parent, text=text, command=cmd, relief="flat", bg=C["bar_btn"], fg="white",
                      activebackground=C["tab_active"], activeforeground="white", padx=12, bd=0)
        return b

    def _build_bar(self):
        bar = tk.Frame(self, bg=C["bar"]); bar.pack(fill="x", padx=4, pady=(4, 0))
        tk.Label(bar, textvariable=self.stats_var, bg=C["bar"], fg=C["bar_fg"],
                 font=(FONT_FAMILY, 10)).pack(side="left", padx=8, pady=6)

        self._bar_button(bar, "Refresh (F5)", lambda: self.load(force=True)).pack(side="right", padx=(2, 8), pady=4)
        go = self._bar_button(bar, "Go", self.jump); go.pack(side="right", padx=2)
        e = ttk.Entry(bar, textvariable=self.jump_var, width=11); e.pack(side="right")
        e.bind("<Return>", lambda ev: self.jump())
        tk.Label(bar, text="Jump to", bg=C["bar"], fg=C["bar_fg"]).pack(side="right", padx=(12, 4))
        self._bar_button(bar, "This week", self.today).pack(side="right", padx=2)
        self._bar_button(bar, "Next  ▶", lambda: self.shift(7)).pack(side="right", padx=2)
        tk.Label(bar, textvariable=self.week_var, bg=C["bar"], fg=C["bar_fg"],
                 font=(FONT_FAMILY, 10, "bold"), width=30).pack(side="right")
        self._bar_button(bar, "◀  Previous", lambda: self.shift(-7)).pack(side="right", padx=2)

    def _build_tools(self):
        t = tk.Frame(self, bg=C["tools"]); t.pack(fill="x", padx=4)
        tk.Label(t, text="My initials:", bg=C["tools"]).pack(side="left", padx=(8, 4), pady=5)
        ttk.Entry(t, textvariable=self.initials_var, width=8).pack(side="left")
        ttk.Checkbutton(t, text="Only my jobs (grey out the rest)", variable=self.mine_only_var,
                        command=self._mine_only_changed).pack(side="left", padx=(8, 20))

        tk.Label(t, text="Find:", bg=C["tools"]).pack(side="left", padx=(0, 4))
        self.find_entry = ttk.Entry(t, textvariable=self.find_var, width=18)
        self.find_entry.pack(side="left")
        self.find_entry.bind("<Escape>", lambda e: self.find_var.set(""))
        ttk.Button(t, text="✕", width=3, command=lambda: self.find_var.set("")).pack(side="left", padx=2)
        tk.Label(t, text="job no, postcode or initials", bg=C["tools"], fg="#777").pack(side="left", padx=4)

        ttk.Button(t, text="+", width=3, command=lambda: self.set_zoom(self.zoom + 0.1)).pack(side="right", padx=(2, 8))
        tk.Label(t, textvariable=self.zoom_var, bg=C["tools"], width=5).pack(side="right")
        ttk.Button(t, text="−", width=3, command=lambda: self.set_zoom(self.zoom - 0.1)).pack(side="right", padx=2)
        tk.Label(t, text="Zoom", bg=C["tools"]).pack(side="right", padx=4)
        self.zoom_var.set(f"{round(self.zoom * 100)}%")

    def _build_grid(self):
        g = tk.Frame(self, bg=C["bg"]); g.pack(fill="both", expand=True, padx=4, pady=4)
        g.rowconfigure(1, weight=1); g.columnconfigure(1, weight=1)
        kw = dict(bg=C["bg"], highlightthickness=0)
        self.corner = tk.Canvas(g, **kw)
        self.head = tk.Canvas(g, **kw)
        self.names = tk.Canvas(g, **kw)
        self.body = tk.Canvas(g, **kw)
        self.vs = ttk.Scrollbar(g, orient="vertical", command=self.body.yview)
        self.hs = ttk.Scrollbar(g, orient="horizontal", command=self.body.xview)
        # body drives the scrolling; header and name column follow it
        self.body.configure(yscrollcommand=self._on_body_y, xscrollcommand=self._on_body_x)
        self.corner.grid(row=0, column=0, sticky="nsew")
        self.head.grid(row=0, column=1, sticky="ew")
        self.names.grid(row=1, column=0, sticky="ns")
        self.body.grid(row=1, column=1, sticky="nsew")
        self.vs.grid(row=1, column=2, sticky="ns")
        self.hs.grid(row=2, column=1, sticky="ew")

        for c in (self.body, self.names):
            c.bind("<MouseWheel>", self._wheel)
            c.bind("<Shift-MouseWheel>", lambda e: self.body.xview_scroll(-e.delta // 120, "units"))
            c.bind("<Control-MouseWheel>", lambda e: self.set_zoom(self.zoom + (0.1 if e.delta > 0 else -0.1)))
            c.bind("<Button-4>", lambda e: self.body.yview_scroll(-3, "units"))
            c.bind("<Button-5>", lambda e: self.body.yview_scroll(3, "units"))
            c.bind("<Button-3>", lambda e, c=c: self._row_menu(e, c))
        self.body.tag_bind("booking", "<Button-1>", self._on_booking_click)
        self.body.tag_bind("booking", "<Double-Button-1>", self._on_booking_double)
        self.body.tag_bind("booking", "<Enter>", self._on_booking_enter)
        self.body.tag_bind("booking", "<Leave>", self._on_booking_leave)
        self.body.bind("<Leave>", self._on_booking_leave)

    def _build_status(self):
        s = tk.Frame(self, bg=C["tools"]); s.pack(fill="x", side="bottom", before=self.body.master)
        tk.Label(s, textvariable=self.info_var, bg=C["tools"], anchor="w",
                 font=(FONT_FAMILY, 10)).pack(side="left", fill="x", expand=True, padx=8, pady=4)
        for text, fg, bg, outline in [
            ("Provisional", *KIND_COLOURS["prov"], None),
            ("WRSREQ", *KIND_COLOURS["wrs"], None),
            ("Prov + WRSREQ", *KIND_COLOURS["both"], None),
            ("My job", C["text"], C["bg"], C["mine"]),
            ("Find match", C["text"], C["bg"], C["match"]),
            ("Today", C["text"], C["today_band"], None),
        ]:
            tk.Label(s, text=text, fg=fg, bg=bg, padx=6, font=(FONT_FAMILY, 8, "bold" if outline == C["mine"] else "normal"),
                     highlightthickness=2 if outline else 0, highlightbackground=outline or bg
                     ).pack(side="right", padx=3, pady=4)
        tk.Label(s, text="Key:", bg=C["tools"], fg="#555").pack(side="right", padx=(8, 0))

    def _on_body_y(self, a, b):
        self.vs.set(a, b); self.names.yview_moveto(a)

    def _on_body_x(self, a, b):
        self.hs.set(a, b); self.head.xview_moveto(a)

    def _wheel(self, e):
        self.body.yview_scroll(-e.delta // 120 or (-1 if e.delta > 0 else 1), "units")

    def _debounce(self, key, ms, fn):
        if key in self._after:
            self.after_cancel(self._after[key])
        self._after[key] = self.after(ms, fn)

    # ------------------------------------------------------------ settings
    def _save_settings(self):
        try:
            self.settings.save()
        except OSError as e:
            self.info_var.set(f"Could not save settings: {e}")

    def _initials_changed(self):
        self.settings["my_initials"] = self.initials_var.get().strip().upper()
        self._save_settings(); self.render()

    def _mine_only_changed(self):
        self.settings["mine_only"] = self.mine_only_var.get()
        self._save_settings(); self.render()
        if self.mine_only_var.get() and not self.settings.my_initials():
            self.info_var.set("Type your initials in 'My initials' first (e.g. AR).")

    def _apply_zoom_fonts(self):
        for k, v in BASE_SIZES.items():
            self.fonts[k].configure(size=max(6, round(v * self.zoom)))

    def set_zoom(self, z):
        self.zoom = round(min(ZOOM_MAX, max(ZOOM_MIN, z)), 1)
        self.zoom_var.set(f"{round(self.zoom * 100)}%")
        self.settings["zoom"] = self.zoom
        self._apply_zoom_fonts()
        self._save_settings(); self.render()

    def _close(self):
        self.settings["last_board"] = self.board
        self._save_settings()
        self.destroy()

    # ------------------------------------------------------------ boards
    def board_for(self, name, info):
        b = self.settings.board_of(name)
        if b:
            return b
        d = default_board(info["office"]) if info else None
        return d if d in self.settings.boards else UNASSIGNED

    def board_members(self):
        members = defaultdict(set)
        for n, info in self.week.items():
            if not self.settings.is_hidden(n):
                members[self.board_for(n, info)].add(n)
        for b in self.settings.boards:
            members[b] |= set(self.settings.pinned_to(b))
        return members

    def tab_list(self, members):
        tabs = list(self.settings.boards)
        if members.get(UNASSIGNED) or self.board == UNASSIGNED:
            tabs.append(UNASSIGNED)
        return tabs

    def _paint_tabs(self, members):
        tabs = self.tab_list(members)
        if tabs != self._tab_keys:
            for w in self.tab_frame.winfo_children():
                w.destroy()
            self.tab_btns = {}
            for b in tabs:
                lbl = tk.Label(self.tab_frame, font=(FONT_FAMILY, 10), padx=14, pady=7, cursor="hand2")
                lbl.pack(side="left", padx=(0, 2))
                lbl.bind("<Button-1>", lambda e, b=b: self.set_board(b))
                self.tab_btns[b] = lbl
            self._tab_keys = tabs
        for b, lbl in self.tab_btns.items():
            on = b == self.board
            idle = C["tab_unassigned"] if b == UNASSIGNED else C["tab"]
            lbl.configure(text=f"{b}  ({len(members.get(b, ()))})",
                          bg=C["tab_active"] if on else idle, fg="white" if on else C["tab_fg"])

    def set_board(self, board):
        self.board = board
        self.settings["last_board"] = board
        self.body.yview_moveto(0)
        self.render()

    def _tab_by_index(self, i):
        if self._tab_keys and i < len(self._tab_keys):
            self.set_board(self._tab_keys[i])

    def _move_engineer(self, name, board):
        self.settings.set_board(name, board)
        self._save_settings(); self.render()
        self.info_var.set(f"{name} now shows on {board}." if board != UNASSIGNED
                          else f"{name} cleared - follows their OfficeID again.")

    def _hide_engineer(self, name):
        self.settings.set_hidden(name, True)
        self._save_settings(); self.render()
        self.info_var.set(f"{name} hidden. Use Engineers & boards… to show them again.")

    def _row_menu(self, event, canvas):
        y = canvas.canvasy(event.y)
        name = next((n for y0, y1, n in self.row_spans if y0 <= y < y1), None)
        if not name:
            return
        m = tk.Menu(self, tearoff=0)
        m.add_command(label=name, state="disabled")
        m.add_separator()
        self._menu_var = tk.StringVar(value=self.board)
        for b in self.settings.boards:
            m.add_radiobutton(label=f"Show on {b}", variable=self._menu_var, value=b,
                              command=lambda b=b: self._move_engineer(name, b))
        m.add_command(label="Clear (follow OfficeID)", command=lambda: self._move_engineer(name, UNASSIGNED))
        m.add_separator()
        m.add_command(label="Hide this engineer", command=lambda: self._hide_engineer(name))
        m.add_command(label="Engineers & boards…", command=self.open_engineers)
        m.tk_popup(event.x_root, event.y_root)

    def open_engineers(self):
        note = ""
        try:
            names = demo_fitters() if self.demo else fetch_fitters()
        except Exception as e:
            names, note = [], f"Couldn't read engineers from the database ({e.__class__.__name__})."
        offices = {}
        for week in self.cache.values():
            for n, info in week.items():
                names.append(n)
                offices.setdefault(n, info["office"])
        EngineersDialog(self, self.settings, names,
                        default_board_of=lambda n: default_board(offices.get(n, "")),
                        on_save=self._after_engineers_saved, note=note)

    def _after_engineers_saved(self):
        if self.board not in self.settings.boards + [UNASSIGNED]:
            self.board = self.settings.boards[0] if self.settings.boards else UNASSIGNED
        self._tab_keys = None
        self.render()

    # ------------------------------------------------------------ navigation / data
    def shift(self, days):
        self.week_start += timedelta(days=days); self.load()

    def today(self):
        self.week_start = monday_of(date.today()); self.load()

    def jump(self):
        txt = self.jump_var.get().strip()
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d"):
            try:
                self.week_start = monday_of(datetime.strptime(txt, fmt).date())
                return self.load()
            except ValueError:
                pass
        messagebox.showwarning("Jump to", "Enter a date like 24/09/2026")

    @property
    def week(self):
        return self.cache.get(self.week_start, {})

    def load(self, force=False):
        start = self.week_start
        end = start + timedelta(days=6)
        self.jump_var.set(f"{start:%d/%m/%Y}")
        self.week_var.set(f"Week {start.isocalendar()[1]}  ·  {start:%d %b} – {end:%d %b %Y}")
        if force or start not in self.cache:
            self.info_var.set("Loading…"); self.config(cursor="watch"); self.update_idletasks()
            try:
                df = (demo_week if self.demo else fetch_week)(start, end)
                self.cache[start] = summarise_week(df, start)
                self.info_var.set(f"Loaded {datetime.now():%H:%M:%S}.")
            except Exception as e:
                self.info_var.set("")
                messagebox.showerror("Database", f"Could not read the board:\n\n{e}")
            finally:
                self.config(cursor="")
        self.render()

    # ------------------------------------------------------------ drawing
    def render(self):
        self.tooltip.hide()
        members = self.board_members()
        self._paint_tabs(members)

        f = self.fonts
        S = lambda v: max(1, int(round(v * self.zoom)))
        w_id = S(W_ID) if F_FITTERID else 0
        left_w = w_id + S(W_NAME)
        w_job, w_hrs, w_tot = S(W_JOB), S(W_HRS), S(W_TOTAL)
        day_w = w_job + w_hrs
        width = 7 * day_w + w_tot
        head_h, pad = S(HEAD_H), S(ROW_PAD)
        line_h = f["bold"].metrics("linespace") + S(3)
        days = [self.week_start + timedelta(days=i) for i in range(7)]
        today = date.today()

        mine_set = self.settings.my_initials()
        mine_only = self.mine_only_var.get() and bool(mine_set)
        find = self.find_var.get().strip().upper()

        for c in (self.corner, self.head, self.names, self.body):
            c.delete("all")
        self.corner.configure(width=left_w, height=head_h)
        self.head.configure(height=head_h)
        self.names.configure(width=left_w)
        self.booking_info, self.row_spans = {}, []

        # -- corner + header
        half = head_h / 2
        self.corner.create_rectangle(0, 0, left_w, head_h, fill=C["head"], outline=C["grid"])
        self.corner.create_text(S(6), half / 2 + 1, anchor="w", font=f["head"], fill=C["head_fg"], text="Week No:")
        self.corner.create_text(S(78), half / 2 + 1, anchor="w", font=f["big"], fill=C["red"],
                                text=str(days[0].isocalendar()[1]))
        self.corner.create_text(left_w / 2, half * 1.5, font=f["head"], fill=C["head_fg"], text="Fitter")
        for i, d in enumerate(days):
            x0, x1 = i * day_w, (i + 1) * day_w
            is_today = d == today
            top = C["today_head"] if is_today else C["weekend"] if d.weekday() >= 5 else C["head"]
            self.head.create_rectangle(x0, 0, x1, half, fill=top, outline=C["grid"])
            self.head.create_rectangle(x0, half, x1, head_h, fill=C["today_head"] if is_today else C["date_bg"], outline=C["grid"])
            font = f["headb"] if is_today else f["head"]
            self.head.create_text((x0 + x1) / 2, half / 2, font=font, fill=C["head_fg"],
                                  text=d.strftime("%a") + ("  • today" if is_today else ""))
            self.head.create_text((x0 + x1) / 2, half * 1.5, font=font, text=d.strftime("%d-%b-%y"))
        self.head.create_rectangle(7 * day_w, 0, width, head_h, fill=C["head"], outline=C["grid"])
        self.head.create_text(7 * day_w + w_tot / 2, half * 1.5, font=f["head"], fill=C["head_fg"], text="Hrs")

        # -- rows
        rows = sorted(members.get(self.board, ()))
        jobs, hours, mine_total, y = set(), 0.0, 0, 0
        for n, name in enumerate(rows):
            info = self.week.get(name) or {"id": "", "days": [[] for _ in days]}
            lines = max([1] + [len(b) for b in info["days"]])
            rh = lines * line_h + 2 * pad
            band = C["band"] if n % 2 else C["bg"]
            self.names.create_rectangle(0, y, left_w, y + rh, fill=band, outline="")
            for i, d in enumerate(days):
                fill = (C["today_band"] if n % 2 else C["today"]) if d == today else band
                self.body.create_rectangle(i * day_w, y, (i + 1) * day_w, y + rh, fill=fill, outline="")
            self.body.create_rectangle(7 * day_w, y, width, y + rh, fill=band, outline="")

            ty, row_total, row_mine = y + pad, 0.0, 0
            for i, bookings in enumerate(info["days"]):
                for k, bk in enumerate(bookings):
                    mine = bool(bk["pm_init"]) and bk["pm_init"] in mine_set
                    match = bool(find) and find in (bk["label"] + " " + " ".join(bk["details"])).upper()
                    dim = (mine_only and not mine) or (bool(find) and not match)
                    self._draw_booking(i * day_w, ty + k * line_h, w_job, w_hrs, line_h,
                                       bk, mine, match, dim, name, days[i])
                    row_total += bk["hrs"]; row_mine += mine
                    if bk["job"]:
                        jobs.add(bk["job"])
            hours += row_total; mine_total += row_mine

            name_fg = C["dim"] if mine_only and not row_mine else C["text"]
            if F_FITTERID:
                self.names.create_text(S(4), ty, anchor="nw", font=f["reg"], fill=name_fg, text=info["id"])
            badge_w = 0
            if row_mine:
                t = self.names.create_text(left_w - S(8), ty + line_h / 2, anchor="e", font=f["small"],
                                           fill="white", text=f"{row_mine} mine")
                x0, y0, x1, y1 = self.names.bbox(t)
                self.names.create_rectangle(x0 - S(4), y0, x1 + S(4), y1, fill=C["mine"], outline="")
                self.names.tag_raise(t)
                badge_w = x1 - x0 + S(14)
            self.names.create_text(w_id + S(5), ty + line_h / 2, anchor="w", fill=name_fg,
                                   font=f["bold"] if row_mine and mine_only else f["reg"],
                                   text=fit_text(f["reg"], name, left_w - w_id - S(10) - badge_w))
            self.body.create_text(7 * day_w + w_tot / 2, ty + line_h / 2, font=f["reg"],
                                  fill=C["dim"] if mine_only and not row_mine else C["text"],
                                  text=fmt_num(row_total))
            self.row_spans.append((y, y + rh, name))
            y += rh
            self.names.create_line(0, y, left_w, y, fill=C["grid"])
            self.body.create_line(0, y, width, y, fill=C["grid"])

        if not rows:
            msg = ("Nobody on this board yet - right-click an engineer on another tab, "
                   "or use Engineers & boards…" if self.board != UNASSIGNED else "Everyone is assigned.")
            self.body.create_text(S(20), S(20), anchor="nw", font=f["head"], fill="#777", text=msg)
        bottom = max(y, 1)
        for i in range(7):
            self.body.create_line(i * day_w + w_job, 0, i * day_w + w_job, bottom, fill=C["grid_light"])
        for i in range(8):
            self.body.create_line(i * day_w, 0, i * day_w, bottom, fill=C["grid"])
        self.body.create_line(width - 1, 0, width - 1, bottom, fill=C["grid"])
        if w_id:
            self.names.create_line(w_id, 0, w_id, bottom, fill=C["grid"])
        self.names.create_line(left_w - 1, 0, left_w - 1, bottom, fill=C["grid"])

        self.body.configure(scrollregion=(0, 0, width, y))
        self.names.configure(scrollregion=(0, 0, left_w, y))
        self.head.configure(scrollregion=(0, 0, width, head_h))
        self.names.yview_moveto(self.body.yview()[0])
        self.head.xview_moveto(self.body.xview()[0])

        stats = f"{self.board}:   Fitters {len(rows)}    Jobs {len(jobs)}    Hours {fmt_num(hours)}"
        if mine_set:
            stats += f"    My bookings ({' '.join(sorted(mine_set))}) {mine_total}"
        self.stats_var.set(stats)

    def _draw_booking(self, x, y, w_job, w_hrs, line_h, bk, mine, match, dim, fitter, day):
        b, f = self.body, self.fonts
        tag = f"bk{len(self.booking_info)}"
        tags = ("booking", tag)
        self.booking_info[tag] = (fitter, day, bk, mine)
        fg, bg = (C["dim"], None) if dim else KIND_COLOURS[bk["kind"]]
        font = f["bold"] if mine and not dim else f["reg"]
        cy = y + line_h / 2
        edge = max(4, round(4 * self.zoom))

        label = fit_text(font, bk["label"], w_job - 3 * edge)
        t = b.create_text(x + w_job / 2 + (edge / 2 if mine else 0), cy, font=font, fill=fg, text=label, tags=tags)
        x0, y0, x1, y1 = b.bbox(t)
        outline = C["mine"] if mine and not dim else C["match"] if match else ""
        if bg or outline:
            r = b.create_rectangle(x0 - 3, y0, x1 + 3, y1, fill=bg or "", outline=outline,
                                   width=2 if outline else 0, tags=tags)
            b.tag_raise(t, r)
        if mine and not dim:
            b.create_rectangle(x + 2, y + 1, x + 2 + edge, y + line_h - 1, fill=C["mine"], outline="", tags=tags)
        hrs_fg = C["dim"] if dim else C["red"] if bk["hrs"] == 0 else C["text"]
        b.create_text(x + w_job + w_hrs / 2, cy, font=f["reg"], fill=hrs_fg,
                      text=fmt_num(bk["hrs"]), tags=tags)

    # ------------------------------------------------------------ booking events
    def _current_tag(self):
        return next((t for t in self.body.gettags("current") if t.startswith("bk")), None)

    def _describe(self, tag, sep):
        fitter, day, bk, mine = self.booking_info[tag]
        parts = [fitter, f"{day:%a %d %b}"] + bk["details"] + (["MY JOB"] if mine else [])
        return sep.join(parts)

    def _on_booking_click(self, e):
        tag = self._current_tag()
        if not tag:
            return
        self.body.delete("sel")
        x0, y0, x1, y1 = self.body.bbox(tag)
        self.body.create_rectangle(x0 - 2, y0 - 1, x1 + 2, y1 + 1, outline=C["select"], width=2, tags="sel")
        self.info_var.set(self._describe(tag, "   ·   "))

    def _on_booking_double(self, e):
        tag = self._current_tag()
        job = tag and self.booking_info[tag][2]["job"]
        if job:
            self.clipboard_clear(); self.clipboard_append(job)
            self.info_var.set(f"Copied job {job} to the clipboard.")

    def _on_booking_enter(self, e):
        tag = self._current_tag()
        if tag:
            self.body.config(cursor="hand2")
            self.tooltip.show(e.x_root, e.y_root, self._describe(tag, "\n"))

    def _on_booking_leave(self, e):
        self.body.config(cursor="")
        self.tooltip.hide()


if __name__ == "__main__":
    BoardView(demo="--demo" in sys.argv).mainloop()
