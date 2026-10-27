"""
Database access and the board model for BoardView.  Read-only: nothing is
ever written back to the Access database.
"""
import os, shutil, tempfile, random
from datetime import date, timedelta
from collections import Counter, defaultdict

import pandas as pd

# ========= EDIT THESE =========
ACCDB_PATH = r"C:\access\DBM215.accdb"
TABLE      = "MainBoard"
JOBS_TABLE = "Jobs"

# Engineers you haven't put on a board yet (Engineers... window) land on the
# board matching the OfficeID of their bookings; anything else -> Unassigned.
OFFICE_CODES = {
    "CL": "London",
}
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

FLAGS = [F_HOL, F_SICK, F_BHOL, F_UNPAID, F_PROVISIONAL, F_WRSREQ]
STATUS_LABELS = ((F_HOL, "HOLS"), (F_SICK, "SICK"), (F_BHOL, "BHOL"), (F_UNPAID, "UNPD"))


# ---------------------------------------------------------------- helpers
def monday_of(d): return d - timedelta(days=d.weekday())

def name_key(name):
    return " ".join(str(name).split()).upper()

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
    if not parts:
        return ""
    if len(parts) == 1:
        # already initials ("AR") or a single name
        return parts[0].upper() if len(parts[0]) <= 3 else parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


# ---------------------------------------------------------------- database
def _run_queries(*sqls):
    import pyodbc
    cs = r"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={};READONLY=1;"
    tmp = None
    try:
        conn = pyodbc.connect(cs.format(ACCDB_PATH), autocommit=True)
    except pyodbc.Error:
        # DB locked by the Access front end -> read a temp copy instead
        tmp = os.path.join(tempfile.gettempdir(), os.path.basename(ACCDB_PATH))
        shutil.copy2(ACCDB_PATH, tmp)
        conn = pyodbc.connect(cs.format(tmp), autocommit=True)
    try:
        return [pd.read_sql(sql, conn) for sql in sqls]
    finally:
        conn.close()
        if tmp and os.path.exists(tmp):
            try: os.remove(tmp)
            except OSError: pass


def fetch_week(start, end):
    """All MainBoard rows for the week, every office."""
    cols = [F_FITTER, F_DATE, F_JOBNO, F_HOURS, F_PROJECTMGR, F_JOBPOSTCODE, F_OFFICEID] + FLAGS
    if F_FITTERID:
        cols.append(F_FITTERID)
    # ISO dates: Access reads #dd/mm/yyyy# as US mm/dd when the day is <= 12
    sql_mb = (f"SELECT {', '.join(f'[{c}]' for c in cols)} FROM [{TABLE}] "
              f"WHERE [{F_DATE}] BETWEEN #{start:%Y-%m-%d}# AND #{end:%Y-%m-%d}#;")
    sql_jobs = (f"SELECT [{F_JOBNO_JOBS}] AS JOBNO_RAW, [{F_PM_JOBS}] AS PM_FromJobs "
                f"FROM [{JOBS_TABLE}];")
    df, jobs = _run_queries(sql_mb, sql_jobs)
    if df.empty:
        return df

    df["JobNo_STR"] = df[F_JOBNO].apply(to_job_str)
    jobs["JobNo_STR"] = jobs["JOBNO_RAW"].apply(to_job_str)
    jobs["PM_FromJobs"] = clean_str(jobs["PM_FromJobs"])
    jobs = jobs[jobs["JobNo_STR"].isin(set(df["JobNo_STR"]))]
    jobs = jobs.drop_duplicates(subset=["JobNo_STR"], keep="last")
    df = df.merge(jobs[["JobNo_STR", "PM_FromJobs"]], on="JobNo_STR", how="left")
    return normalise(df)


def fetch_fitters(days_back=120, days_ahead=90):
    """Distinct fitter names booked around today (for the Engineers window)."""
    lo, hi = date.today() - timedelta(days=days_back), date.today() + timedelta(days=days_ahead)
    (df,) = _run_queries(
        f"SELECT DISTINCT [{F_FITTER}] FROM [{TABLE}] "
        f"WHERE [{F_DATE}] BETWEEN #{lo:%Y-%m-%d}# AND #{hi:%Y-%m-%d}#;")
    return sorted({name_key(n) for n in clean_str(df[F_FITTER]) if n})


def normalise(df):
    df = df.copy()
    df[F_DATE] = pd.to_datetime(df[F_DATE]).dt.date
    for c in [F_FITTER, F_PROJECTMGR, F_JOBPOSTCODE, F_OFFICEID]:
        df[c] = clean_str(df[c])
    df[F_FITTER] = df[F_FITTER].map(name_key)
    df[F_OFFICEID] = df[F_OFFICEID].str.upper()
    for c in FLAGS:
        df[c] = df[c].apply(to_bool)
    if "JobNo_STR" not in df:
        df["JobNo_STR"] = df[F_JOBNO].apply(to_job_str)
    pm_jobs = clean_str(df.get("PM_FromJobs", pd.Series("", index=df.index)))
    df[F_PM_EFFECTIVE] = pm_jobs.where(pm_jobs != "", df[F_PROJECTMGR])
    return df


# ---------------------------------------------------------------- demo data
DEMO_FITTERS = [
    ("ACQUAYE, ISAAC", "CL"), ("ALBERTELLI, JADEN", "CL"), ("DAMS, CAELAN", "CL"),
    ("DUNN, KALLAM", "CL"), ("FAULKNER, JASON", "CL"), ("GOODING, HARVEY", "CL"),
    ("GRAY, BILLY", "CL"), ("HUMPHREYS, CONNOR", "CL"), ("HUMPHREYS, STEPHEN", "CL"),
    ("JOYCE, ADAM", "CL"), ("KENNY, CALLUM", "CL"), ("LEEDER, JOSEF", "CW"),
    ("LEEDER, RHYS", "CW"), ("MARRIAGE, LUKE", "CL"), ("MCNAMARA, DAVID", "CE"),
    ("PELTIER, XAVIER", "CE"), ("TASSADAQ, NAQQASH", "CS"), ("WELCH, LEE", "CL"),
    ("YIANNOPOULOS, MARCO", "CL"),
]

def demo_fitters():
    return sorted(n for n, _ in DEMO_FITTERS)

def demo_week(start, end):
    """Random but stable data so the window can be tried without Access."""
    rnd = random.Random(str(start))
    pms = ["Ali Rashid", "Adam Taylor", "Emma Thompson", "Ben Smith", "Sam Jones", "Ella Turner"]
    pcs = ["N6", "W2", "SW14", "HA4", "SW1", "OX4", "E17", "SE16", "SL6", "N18",
           "TW8", "LU1", "RG5", "EC2M", "UB4", "UB3", "NW9", "E16", "W12", "NR4"]
    jobs = [(rnd.randint(114000, 120500), rnd.choice(pms), rnd.choice(pcs)) for _ in range(28)]
    rows = []
    for i, (name, office) in enumerate(DEMO_FITTERS):
        if name == "GOODING, HARVEY":
            continue   # no bookings: shows as an empty row if assigned to a board
        for d in range(7):
            day = start + timedelta(days=d)
            base = dict.fromkeys(FLAGS, False)
            base.update({F_FITTER: name, F_DATE: day, F_OFFICEID: office,
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
    """One line in a day cell, or None for an empty row."""
    hrs = to_hours(r.get(F_HOURS))
    for flag, text in STATUS_LABELS:
        if r.get(flag):
            return {"label": text, "hrs": hrs, "kind": "status", "pm": "", "pm_init": "",
                    "job": "", "pc": "", "details": [text]}

    job = r.get("JobNo_STR", "")
    if job == "0":
        job = ""
    pm = r.get(F_PM_EFFECTIVE, "")
    pc = r.get(F_JOBPOSTCODE, "")
    if not (job or pc):
        return None

    prov, wrs = bool(r.get(F_PROVISIONAL)), bool(r.get(F_WRSREQ))
    init = pm_initials(pm) if pm else ""
    kind = "both" if prov and wrs else "prov" if prov else "wrs" if wrs else "normal"
    details = [x for x in [
        f"Job {job}" if job else "", f"PM: {pm}" if pm else "",
        f"Postcode: {pc}" if pc else "", f"{fmt_num(hrs)} hrs",
        "PROVISIONAL" if prov else "", "WRSREQ" if wrs else ""] if x]
    return {"label": f"{init + '-' if init else ''}{job}- {pc}".strip(), "hrs": hrs,
            "kind": kind, "pm": pm, "pm_init": init, "job": job, "pc": pc,
            "details": details}


def summarise_week(df, week_start):
    """{fitter: {"id", "office", "days": [7 lists of bookings]}}"""
    days = [week_start + timedelta(days=i) for i in range(7)]
    out = {}
    if df is None or df.empty:
        return out
    offices = defaultdict(Counter)
    for _, r in df.sort_values([F_FITTER, F_DATE]).iterrows():
        name = r[F_FITTER] or "(UNASSIGNED)"
        f = out.setdefault(name, {"id": "", "office": "", "days": {d: [] for d in days}})
        if F_FITTERID and not f["id"]:
            f["id"] = to_job_str(r.get(F_FITTERID))
        if r[F_OFFICEID]:
            offices[name][r[F_OFFICEID]] += 1
        b = booking_from_row(r)
        if b and r[F_DATE] in f["days"]:
            f["days"][r[F_DATE]].append(b)
    for name, f in out.items():
        f["days"] = [f["days"][d] for d in days]
        f["office"] = offices[name].most_common(1)[0][0] if offices[name] else ""
    return out


def default_board(office):
    return OFFICE_CODES.get(office)
