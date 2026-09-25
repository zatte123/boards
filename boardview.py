"""
BoardView - read-only on-screen viewer for the MainBoard bookings.

Opens a window laid out like the Digital Board Manager: one row per fitter,
one column per day (booking + hours), weekly hours on the right.
Nothing is written to the database and nothing is exported/sent.

    python boardview.py            # live data from the Access DB
    python boardview.py --demo     # fake data, no database needed
"""
import os, sys, shutil, tempfile, random
from datetime import date, datetime, timedelta
from collections import defaultdict

import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox

# ========= EDIT THESE =========
ACCDB_PATH = r"C:\access\DBM215.accdb"
TABLE      = "MainBoard"
JOBS_TABLE = "Jobs"

# Tabs across the top: label -> OfficeID code in MainBoard.
# Add the other boards once you know their codes, e.g. "East": "CE".
BOARDS = {
    "London": "CL",
}
BRANCH_MATCH = "exact"   # "exact" | "startswith" | "contains"

# Leave SHOW_ONLY_INCLUDED False to show every fitter booked on the board.
# Set it True to show only these names (they appear even with no bookings).
SHOW_ONLY_INCLUDED = False
INCLUDE_NAMES = [
    "ACQUAYE, ISAAC","ALBERTELLI, JADEN","DUNN, KALLAM","FAULKNER, JASON",
    "GRAY, BILLY","HUMPHREYS, CONNOR","HUMPHREYS, STEPHEN",
    "JANES, DANIEL","JANES, PETER","JOYCE, ADAM","MCKEOWN, ELLIOT",
    "RODELL, WILLIAM","SMITH, JAKE","WELCH, LEE","YIANNOPOULOS, MARCO",
]
# ==============================

# ---- exact field names (MainBoard) ----
F_FITTER      = "FitterName"
F_FITTERID    = None          # e.g. "FitterID" to show the number column; None = hide
F_DATE        = "JobDate"
F_JOBNO       = "JobNo"
F_HOURS       = "Hours"
F_HOL         = "Holiday"
F_SICK        = "Sick"
F_BHOL        = "BHoliday"
F_UNPAID      = "Unpaid"
F_PROJECTMGR  = "ProjectMgr"
F_JOBPOSTCODE = "JobPostCode"
F_PROVISIONAL = "Provisional"
F_WRSREQ      = "WRSREQ"
F_OFFICEID    = "OfficeID"

# ---- Jobs table (PM by JobNo) ----
F_JOBNO_JOBS   = "JOBNO"
F_PM_JOBS      = "ProjectMgr"
F_PM_EFFECTIVE = "PM_Effective"   # derived

# ---- look ----
C = {
    "bg": "#ffffff", "grid": "#b9c3d2", "band": "#e3ecf8",
    "bar": "#4a90d9", "bar_fg": "#ffffff",
    "tab": "#dbe5f3", "tab_active": "#2f6fc0",
    "head": "#d8e2f2", "head_fg": "#1f3b63", "date_bg": "#fbe8b0",
    "weekend": "#fff27a",
    "text": "#000000", "status": "#e00000", "hrs_zero": "#e00000",
    "prov_bg": "#ff0000", "prov_fg": "#ffffff",
    "wrs_bg": "#ffff00", "wrs_fg": "#000000",
    "both_fg": "#e00000",
    "select": "#2f6fc0",
}
FONT      = ("Segoe UI", 9)
FONT_B    = ("Segoe UI", 9, "bold")
FONT_HEAD = ("Segoe UI", 10)
FONT_BIG  = ("Segoe UI", 13, "bold")

W_ID, W_NAME, W_JOB, W_HRS, W_TOTAL = 36, 190, 132, 56, 80
LINE_H, ROW_PAD, HEAD_H = 16, 4, 44


# ---------------------------------------------------------------- helpers
def monday_of(d): return d - timedelta(days=d.weekday())

def to_bool(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return False
    if isinstance(v, (int, float)):
        return v != 0
    return str(v).strip().lower() in ("yes", "true", "1", "-1", "y", "t")

def to_job_str(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, (int, float)):
        return str(int(v)) if float(v).is_integer() else str(v)
    return str(v).strip()

def to_hours(v):
    try:
        f = float(v)
        return 0.0 if pd.isna(f) else f
    except (TypeError, ValueError):
        return 0.0

def fmt_num(f):
    return str(int(f)) if float(f).is_integer() else f"{f:g}"

def clean_str(s):
    return s.fillna("").astype(str).str.replace("\u00a0", " ", regex=False).str.strip()

def pm_initials(pm):
    parts = pm.replace(",", " ").split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return pm[:2].upper()


# ---------------------------------------------------------------- data
def connect_access(db_path):
    import pyodbc
    cs = r"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={};READONLY=1;"
    try:
        return pyodbc.connect(cs.format(db_path), autocommit=True), None
    except pyodbc.Error:
        # DB locked by the Access front end -> read a temp copy instead
        tmp = os.path.join(tempfile.gettempdir(), os.path.basename(db_path))
        shutil.copy2(db_path, tmp)
        return pyodbc.connect(cs.format(tmp), autocommit=True), tmp


def fetch_week(start, end, branch):
    cols = [F_FITTER, F_DATE, F_JOBNO, F_HOURS, F_HOL, F_SICK, F_BHOL, F_UNPAID,
            F_PROJECTMGR, F_JOBPOSTCODE, F_PROVISIONAL, F_WRSREQ, F_OFFICEID]
    if F_FITTERID:
        cols.append(F_FITTERID)
    # ISO dates: Access reads #dd/mm/yyyy# as US mm/dd when the day is <= 12
    sql_mb = (
        f"SELECT {', '.join(f'[{c}]' for c in cols)} FROM [{TABLE}] "
        f"WHERE [{F_DATE}] BETWEEN #{start:%Y-%m-%d}# AND #{end:%Y-%m-%d}#;"
    )
    sql_jobs = (f"SELECT [{F_JOBNO_JOBS}] AS JOBNO_RAW, [{F_PM_JOBS}] AS PM_FromJobs "
                f"FROM [{JOBS_TABLE}];")

    conn, tmp = connect_access(ACCDB_PATH)
    try:
        df = pd.read_sql(sql_mb, conn)
        jobs = pd.read_sql(sql_jobs, conn)
    finally:
        conn.close()
        if tmp and os.path.exists(tmp):
            try: os.remove(tmp)
            except OSError: pass

    if df.empty:
        return df
    df = filter_branch(df, branch)

    df["JobNo_STR"] = df[F_JOBNO].apply(to_job_str)
    jobs["JobNo_STR"] = jobs["JOBNO_RAW"].apply(to_job_str)
    jobs["PM_FromJobs"] = clean_str(jobs["PM_FromJobs"])
    jobs = jobs[jobs["JobNo_STR"].isin(set(df["JobNo_STR"]))]
    jobs = jobs.drop_duplicates(subset=["JobNo_STR"], keep="last")
    df = df.merge(jobs[["JobNo_STR", "PM_FromJobs"]], on="JobNo_STR", how="left")
    return normalise(df)


def filter_branch(df, branch):
    office = clean_str(df[F_OFFICEID]).str.upper()
    if BRANCH_MATCH == "startswith":
        return df[office.str.startswith(branch)]
    if BRANCH_MATCH == "contains":
        return df[office.str.contains(branch, regex=False)]
    return df[office == branch]


def normalise(df):
    df = df.copy()
    df[F_DATE] = pd.to_datetime(df[F_DATE]).dt.date
    for c in [F_FITTER, F_PROJECTMGR, F_JOBPOSTCODE]:
        df[c] = clean_str(df[c])
    for c in [F_HOL, F_SICK, F_BHOL, F_UNPAID, F_PROVISIONAL, F_WRSREQ]:
        df[c] = df[c].apply(to_bool)
    if "JobNo_STR" not in df:
        df["JobNo_STR"] = df[F_JOBNO].apply(to_job_str)
    pm_jobs = clean_str(df.get("PM_FromJobs", pd.Series("", index=df.index)))
    df[F_PM_EFFECTIVE] = pm_jobs.where(pm_jobs != "", df[F_PROJECTMGR])
    return df


def demo_week(start, end, branch):
    """Random but stable data so the window can be tried without Access."""
    rnd = random.Random(f"{start}{branch}")
    pms = ["Adam Taylor", "Emma Thompson", "Ben Smith", "Alice Roberts", "Sam Jones"]
    pcs = ["N6", "W2", "SW14", "HA4", "SW1", "OX4", "E17", "SE16", "SL6", "N18",
           "TW8", "LU1", "RG5", "EC2M", "UB4", "UB3", "NW9", "E16", "W12", "NR4"]
    jobs = [(rnd.randint(114000, 120500), rnd.choice(pms), rnd.choice(pcs)) for _ in range(25)]
    rows = []
    for i, name in enumerate(INCLUDE_NAMES):
        for d in range(7):
            day = start + timedelta(days=d)
            base = dict.fromkeys([F_HOL, F_SICK, F_BHOL, F_UNPAID, F_PROVISIONAL, F_WRSREQ], False)
            base.update({F_FITTER: name, F_DATE: day, F_OFFICEID: branch,
                         F_JOBNO: None, F_HOURS: 0, F_PROJECTMGR: "", F_JOBPOSTCODE: ""})
            if F_FITTERID:
                base[F_FITTERID] = 100 + i
            if d >= 5 and rnd.random() > 0.1:
                continue
            r = rnd.random()
            if r < 0.06:
                rows.append({**base, F_HOL: True, F_HOURS: 10}); continue
            if r < 0.09:
                rows.append({**base, F_UNPAID: True}); continue
            split = rnd.random() < 0.2
            for hrs in ([8, 2] if split else [10 if d < 4 else 9]):
                job, pm, pc = rnd.choice(jobs)
                rows.append({**base, F_JOBNO: job, F_HOURS: hrs, F_PROJECTMGR: pm,
                             F_JOBPOSTCODE: pc, F_PROVISIONAL: rnd.random() < 0.12,
                             F_WRSREQ: rnd.random() < 0.2})
    return normalise(pd.DataFrame(rows))


# ---------------------------------------------------------------- board model
def booking_from_row(r):
    """Return a dict describing one line in a day cell, or None to skip."""
    hrs = to_hours(r.get(F_HOURS))
    for flag, text in ((F_HOL, "HOLS"), (F_SICK, "SICK"), (F_BHOL, "BHOL"), (F_UNPAID, "UNPD")):
        if r.get(flag):
            return {"label": text, "hrs": hrs, "bg": None, "fg": C["status"],
                    "status": True, "info": text}

    job = r.get("JobNo_STR", "")
    if job == "0":
        job = ""
    pm = r.get(F_PM_EFFECTIVE, "")
    pc = r.get(F_JOBPOSTCODE, "")
    if not (job or pc):
        return None

    prov, wrs = r.get(F_PROVISIONAL), r.get(F_WRSREQ)
    label = f"{pm_initials(pm) + '-' if pm else ''}{job}- {pc}".strip()
    if prov and wrs:
        bg, fg = C["wrs_bg"], C["both_fg"]
    elif prov:
        bg, fg = C["prov_bg"], C["prov_fg"]
    elif wrs:
        bg, fg = C["wrs_bg"], C["wrs_fg"]
    else:
        bg, fg = None, C["text"]

    flags = [t for t, on in (("PROVISIONAL", prov), ("WRSREQ", wrs)) if on]
    info = "   |   ".join(x for x in [
        f"Job {job}" if job else "", f"PM: {pm}" if pm else "",
        f"Postcode: {pc}" if pc else "", f"{fmt_num(hrs)} hrs", " ".join(flags)] if x)
    return {"label": label, "hrs": hrs, "bg": bg, "fg": fg, "status": False,
            "info": info, "job": job}


def build_board(df, week_start):
    days = [week_start + timedelta(days=i) for i in range(7)]
    cells = defaultdict(lambda: defaultdict(list))
    ids = {}
    if not df.empty:
        df = df.sort_values([F_FITTER, F_DATE])
        for _, r in df.iterrows():
            name = r[F_FITTER] or "(Unassigned)"
            cells[name]   # a fitter with an empty row still gets a line
            if F_FITTERID and name not in ids:
                ids[name] = to_job_str(r.get(F_FITTERID))
            b = booking_from_row(r)
            if b:
                cells[name][r[F_DATE]].append(b)

    names = sorted(cells, key=str.lower)
    if SHOW_ONLY_INCLUDED:
        wanted = {n.upper() for n in INCLUDE_NAMES}
        names = sorted({n for n in names if n.upper() in wanted} | set(INCLUDE_NAMES), key=str.lower)

    rows = []
    for n in names:
        daymap = cells.get(n, {})
        total = sum(b["hrs"] for d in days for b in daymap.get(d, []))
        rows.append({"name": n, "id": ids.get(n, ""), "days": [daymap.get(d, []) for d in days],
                     "total": total})
    jobs = {b["job"] for row in rows for day in row["days"] for b in day if b.get("job")}
    return days, rows, {"fitters": len(rows), "jobs": len(jobs),
                        "hours": sum(r["total"] for r in rows)}


# ---------------------------------------------------------------- UI
class BoardView(tk.Tk):
    def __init__(self, demo=False):
        super().__init__()
        self.demo = demo
        self.title("BoardView" + (" (demo data)" if demo else ""))
        self.geometry("1600x850")
        self.configure(bg=C["bg"])

        self.board = next(iter(BOARDS))
        self.week_start = monday_of(date.today())
        self.selected = None
        self.info_var = tk.StringVar()
        self.stats_var = tk.StringVar()
        self.week_var = tk.StringVar()
        self.jump_var = tk.StringVar()

        self._build_tabs()
        self._build_bar()
        self._build_grid()
        self.bind("<F5>", lambda e: self.load())
        self.bind("<Prior>", lambda e: self.shift(-7))
        self.bind("<Next>", lambda e: self.shift(7))
        self.after(50, self.load)

    # -- chrome
    def _build_tabs(self):
        f = tk.Frame(self, bg=C["bg"]); f.pack(fill="x", padx=4, pady=(4, 0))
        self.tab_btns = {}
        for label in BOARDS:
            b = tk.Label(f, text=label, font=FONT_HEAD, width=11, pady=8, cursor="hand2")
            b.pack(side="left", padx=(0, 2))
            b.bind("<Button-1>", lambda e, l=label: self.set_board(l))
            self.tab_btns[label] = b
        self._paint_tabs()

        right = tk.Frame(f, bg=C["bg"]); right.pack(side="right")
        tk.Label(right, text="Jump To", bg=C["bg"], font=FONT_HEAD).pack(side="left", padx=4)
        e = ttk.Entry(right, textvariable=self.jump_var, width=11)
        e.pack(side="left")
        e.bind("<Return>", lambda ev: self.jump())
        ttk.Button(right, text="Go", width=4, command=self.jump).pack(side="left", padx=(2, 8))
        ttk.Button(right, text="Today", command=self.today).pack(side="left", padx=2)
        ttk.Button(right, text="Refresh (F5)", command=self.load).pack(side="left", padx=2)

    def _paint_tabs(self):
        for label, b in self.tab_btns.items():
            on = label == self.board
            b.configure(bg=C["tab_active"] if on else C["tab"], fg="white" if on else "#333")

    def _build_bar(self):
        bar = tk.Frame(self, bg=C["bar"]); bar.pack(fill="x", padx=4, pady=4)
        tk.Label(bar, textvariable=self.stats_var, bg=C["bar"], fg=C["bar_fg"],
                 font=FONT_HEAD).pack(side="left", padx=8, pady=6)
        tk.Label(bar, text="Cell info", bg=C["bar"], fg=C["bar_fg"], font=FONT).pack(side="left", padx=(16, 4))
        ttk.Entry(bar, textvariable=self.info_var, width=80, state="readonly").pack(side="left", pady=6)
        tk.Button(bar, text="Next  \u25b6", command=lambda: self.shift(7), relief="flat",
                  bg="#6aa7e8", fg="white", padx=14).pack(side="right", padx=(2, 8))
        tk.Button(bar, text="\u25c0  Previous", command=lambda: self.shift(-7), relief="flat",
                  bg="#6aa7e8", fg="white", padx=14).pack(side="right", padx=2)

    def _build_grid(self):
        outer = tk.Frame(self, bg=C["bg"]); outer.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        outer.rowconfigure(1, weight=1); outer.columnconfigure(0, weight=1)
        self.head = tk.Canvas(outer, height=HEAD_H, bg=C["bg"], highlightthickness=0)
        self.body = tk.Canvas(outer, bg=C["bg"], highlightthickness=0)
        vs = ttk.Scrollbar(outer, orient="vertical", command=self.body.yview)
        hs = ttk.Scrollbar(outer, orient="horizontal", command=self._xview)
        self.body.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.head.grid(row=0, column=0, sticky="ew")
        self.body.grid(row=1, column=0, sticky="nsew")
        vs.grid(row=1, column=1, sticky="ns"); hs.grid(row=2, column=0, sticky="ew")
        self.body.bind("<MouseWheel>", lambda e: self.body.yview_scroll(-e.delta // 120, "units"))
        self.body.bind("<Shift-MouseWheel>", lambda e: self._xview("scroll", -e.delta // 120, "units"))
        self.body.bind("<Button-4>", lambda e: self.body.yview_scroll(-3, "units"))
        self.body.bind("<Button-5>", lambda e: self.body.yview_scroll(3, "units"))

    def _xview(self, *args):
        self.body.xview(*args); self.head.xview(*args)

    # -- navigation
    def set_board(self, label):
        self.board = label; self._paint_tabs(); self.load()

    def shift(self, days):
        self.week_start += timedelta(days=days); self.load()

    def today(self):
        self.week_start = monday_of(date.today()); self.load()

    def jump(self):
        txt = self.jump_var.get().strip()
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                self.week_start = monday_of(datetime.strptime(txt, fmt).date())
                return self.load()
            except ValueError:
                pass
        messagebox.showwarning("Jump To", "Enter a date like 24/09/2026")

    # -- data
    def load(self):
        start = self.week_start
        end = start + timedelta(days=6)
        branch = BOARDS[self.board].strip().upper()
        self.jump_var.set(f"{start:%d/%m/%Y}")
        self.info_var.set("Loading…"); self.config(cursor="watch"); self.update_idletasks()
        try:
            df = (demo_week if self.demo else fetch_week)(start, end, branch)
        except Exception as e:
            self.config(cursor="")
            self.info_var.set("")
            messagebox.showerror("Database", f"Could not read the board:\n\n{e}")
            return
        finally:
            self.config(cursor="")
        days, rows, stats = build_board(df, start)
        self.stats_var.set(f"Fitters: {stats['fitters']}    Jobs: {stats['jobs']}    "
                           f"Total Hours: {fmt_num(stats['hours'])}")
        self.info_var.set("")
        self.draw(days, rows)

    # -- drawing
    def _cols(self):
        x = W_ID if F_FITTERID else 0
        name_x = x
        x += W_NAME
        day_x = []
        for _ in range(7):
            day_x.append(x); x += W_JOB + W_HRS
        return name_x, day_x, x, x + W_TOTAL

    def draw(self, days, rows):
        self.selected = None
        name_x, day_x, total_x, width = self._cols()
        h, b = self.head, self.body
        h.delete("all"); b.delete("all")

        # header: day names over dates, like the Access board
        half = HEAD_H // 2
        h.create_rectangle(0, 0, name_x + W_NAME, HEAD_H, fill=C["head"], outline="")
        h.create_text(6, half // 2 + 1, anchor="w", font=FONT_HEAD, fill=C["head_fg"], text="Week No:")
        h.create_text(90, half // 2 + 1, anchor="w", font=FONT_BIG, fill="#e00000",
                      text=str(days[0].isocalendar()[1]))
        h.create_text(name_x + W_NAME // 2, half + half // 2, font=FONT_HEAD, fill=C["head_fg"], text="Fitter")
        for i, d in enumerate(days):
            x0, x1 = day_x[i], day_x[i] + W_JOB + W_HRS
            weekend = d.weekday() >= 5
            h.create_rectangle(x0, 0, x1, half, fill=C["weekend"] if weekend else C["head"], outline=C["grid"])
            h.create_rectangle(x0, half, x1, HEAD_H, fill=C["date_bg"], outline=C["grid"])
            h.create_text((x0 + x1) / 2, half / 2, font=FONT_HEAD, fill=C["head_fg"], text=d.strftime("%a"))
            h.create_text((x0 + x1) / 2, half * 1.5, font=FONT_HEAD, text=d.strftime("%d-%b-%y"))
        h.create_rectangle(total_x, half, width, HEAD_H, fill=C["head"], outline=C["grid"])
        h.create_text(total_x + 6, half * 1.5, anchor="w", font=FONT_HEAD, fill=C["head_fg"], text="Hrs")

        # rows
        y = 0
        for n, row in enumerate(rows):
            lines = max([1] + [len(d) for d in row["days"]])
            rh = lines * LINE_H + ROW_PAD * 2
            if n % 2:
                b.create_rectangle(0, y, width, y + rh, fill=C["band"], outline="")
            ty = y + ROW_PAD
            if F_FITTERID:
                b.create_text(4, ty, anchor="nw", font=FONT, text=row["id"])
            b.create_text(name_x + 4, ty, anchor="nw", font=FONT, text=row["name"])
            for i, bookings in enumerate(row["days"]):
                for k, bk in enumerate(bookings):
                    self._draw_booking(day_x[i], ty + k * LINE_H, bk, row["name"], days[i])
            b.create_text(total_x + 6, ty, anchor="nw", font=FONT, text=fmt_num(row["total"]))
            y += rh
            b.create_line(0, y, width, y, fill=C["grid"])

        if not rows:
            b.create_text(20, 20, anchor="nw", font=FONT_HEAD, fill="#777",
                          text="No bookings for this board this week.")
            y = 60
        for x in [name_x] + day_x + [x + W_JOB for x in day_x] + [total_x, width]:
            if x:
                b.create_line(x, 0, x, y, fill=C["grid"])
        b.configure(scrollregion=(0, 0, width, y))
        h.configure(scrollregion=(0, 0, width, HEAD_H))

    def _draw_booking(self, x, y, bk, fitter, day):
        b = self.body
        tag = f"bk{id(bk)}"
        cx = x + W_JOB / 2
        t = b.create_text(cx, y + LINE_H / 2, font=FONT, fill=bk["fg"], text=bk["label"], tags=tag)
        if bk["bg"]:
            x0, y0, x1, y1 = b.bbox(t)
            b.create_rectangle(x0 - 2, y0, x1 + 2, y1, fill=bk["bg"], outline="", tags=tag)
            b.tag_raise(t)
        hrs_fg = C["hrs_zero"] if bk["hrs"] == 0 else C["text"]
        b.create_text(x + W_JOB + W_HRS / 2, y + LINE_H / 2, font=FONT, fill=hrs_fg,
                      text=fmt_num(bk["hrs"]), tags=tag)
        info = f"{fitter}   |   {day:%a %d %b}   |   {bk['info']}"
        b.tag_bind(tag, "<Button-1>", lambda e: self._select(tag, info))
        b.tag_bind(tag, "<Enter>", lambda e: b.config(cursor="hand2"))
        b.tag_bind(tag, "<Leave>", lambda e: b.config(cursor=""))

    def _select(self, tag, info):
        b = self.body
        b.delete("sel")
        x0, y0, x1, y1 = b.bbox(tag)
        b.create_rectangle(x0 - 1, y0 - 1, x1 + 1, y1 + 1, outline=C["select"], width=2, tags="sel")
        self.info_var.set(info)


if __name__ == "__main__":
    BoardView(demo="--demo" in sys.argv).mainloop()
