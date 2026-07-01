"""
Team Attendance Planner â€” Flask backend.

Single job: show whether every team has enough people working each day,
and let each person set their own daily status.

Run:
    python -m venv .venv
    .venv\\Scripts\\activate        (Windows)   /   source .venv/bin/activate  (mac/Linux)
    pip install -r requirements.txt
    python app.py
Then open http://127.0.0.1:8080
"""

import os
import secrets
import sqlite3
from datetime import date, timedelta
from calendar import monthrange
from functools import wraps

from flask import Flask, request, jsonify, render_template, redirect, url_for, session, abort

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "attendance.db")

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "1234"

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(16)


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            abort(403)
        return view(*args, **kwargs)
    return wrapped

# ------------------------------------------------------------------ #
#  Status configuration (shared with the front-end via the template)  #
# ------------------------------------------------------------------ #
STATUS = {
    "ofc": {"label": "In office",         "color": "#16A34A", "working": True},
    "wfh": {"label": "Home office",       "color": "#2563EB", "working": True},
    "trp": {"label": "Business trip",     "color": "#7C3AED", "working": True},
    "vac": {"label": "Vacation",          "color": "#E08600", "working": False},
    "hva": {"label": "Half-day vacation", "color": "#E08600", "working": False},
    "sck": {"label": "Sick",              "color": "#DC2626", "working": False},
    "flx": {"label": "Flexi day",         "color": "#0D9488", "working": False},
    "fre": {"label": "Free",              "color": "#64748B", "working": False},
}
ORDER = ["ofc", "wfh", "trp", "vac", "hva", "sck", "flx", "fre"]
WORKING = {k for k, v in STATUS.items() if v["working"]}

# Vacation days consumed per status (full vacation = 1 day, half-day = 0.5).
VAC_WEIGHT = {"vac": 1.0, "hva": 0.5}

MONTHS = ["", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]
WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]  # date.weekday(): Mon=0


# ------------------------------------------------------------------ #
#  Czech public holidays (incl. movable Easter dates)                 #
# ------------------------------------------------------------------ #
def easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm (Computus)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


_holiday_cache: dict[int, dict[str, str]] = {}


def cz_holidays(year: int) -> dict[str, str]:
    """Return {iso_date: holiday_name} for the given year."""
    if year in _holiday_cache:
        return _holiday_cache[year]
    es = easter_sunday(year)
    items = {
        date(year, 1, 1):   "Den obnovy samostatnĂ©ho ÄŤeskĂ©ho stĂˇtu",
        es - timedelta(days=2): "VelkĂ˝ pĂˇtek",
        es + timedelta(days=1): "VelikonoÄŤnĂ­ pondÄ›lĂ­",
        date(year, 5, 1):   "SvĂˇtek prĂˇce",
        date(year, 5, 8):   "Den vĂ­tÄ›zstvĂ­",
        date(year, 7, 5):   "Den slovanskĂ˝ch vÄ›rozvÄ›stĹŻ Cyrila a MetodÄ›je",
        date(year, 7, 6):   "Den upĂˇlenĂ­ mistra Jana Husa",
        date(year, 9, 28):  "Den ÄŤeskĂ© stĂˇtnosti",
        date(year, 10, 28): "Den vzniku samostatnĂ©ho ÄŤeskoslovenskĂ©ho stĂˇtu",
        date(year, 11, 17): "Den boje za svobodu a demokracii",
        date(year, 12, 24): "Ĺ tÄ›drĂ˝ den",
        date(year, 12, 25): "1. svĂˇtek vĂˇnoÄŤnĂ­",
        date(year, 12, 26): "2. svĂˇtek vĂˇnoÄŤnĂ­",
    }
    result = {d.isoformat(): name for d, name in items.items()}
    _holiday_cache[year] = result
    return result


# ------------------------------------------------------------------ #
#  Database                                                           #
# ------------------------------------------------------------------ #
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS teams (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            min_working INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS members (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT NOT NULL,
            allowance INTEGER NOT NULL DEFAULT 200
        );
        CREATE TABLE IF NOT EXISTS member_teams (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id   INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
            team_id     INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            start_date  TEXT,                 -- ISO date; NULL = since the beginning
            end_date    TEXT                  -- ISO date; NULL = still active
        );
        CREATE TABLE IF NOT EXISTS attendance (
            member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
            day       TEXT NOT NULL,          -- ISO date 'YYYY-MM-DD'
            status    TEXT NOT NULL,          -- one of STATUS keys
            PRIMARY KEY (member_id, day)
        );
        """
    )
    conn.commit()

    # Migrate older DBs that still have members.team_id (a single, current-only
    # team assignment) into member_teams (date-ranged, supports multiple teams
    # and preserves history of past assignments).
    team_col = next((c for c in conn.execute("PRAGMA table_info(members)") if c["name"] == "team_id"), None)
    if team_col:
        rows = conn.execute("SELECT id, team_id FROM members WHERE team_id IS NOT NULL").fetchall()
        if rows:
            conn.executemany(
                "INSERT INTO member_teams(member_id, team_id, start_date, end_date) VALUES (?,?,NULL,NULL)",
                [(r["id"], r["team_id"]) for r in rows],
            )
        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.execute("ALTER TABLE members DROP COLUMN team_id")
        except sqlite3.OperationalError:
            conn.executescript(
                """
                CREATE TABLE members_new (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    name      TEXT NOT NULL,
                    allowance INTEGER NOT NULL DEFAULT 200
                );
                INSERT INTO members_new(id, name, allowance) SELECT id, name, allowance FROM members;
                DROP TABLE members;
                ALTER TABLE members_new RENAME TO members;
                """
            )
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")

    # Seed demo data once, so coverage gaps are visible out of the box.
    if conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0] == 0:
        cur = conn.cursor()
        cur.execute("INSERT INTO teams(name, min_working) VALUES (?,?)", ("Operations", 2))
        ops = cur.lastrowid
        cur.execute("INSERT INTO teams(name, min_working) VALUES (?,?)", ("Risk & Controls", 1))
        risk = cur.lastrowid

        people = [
            ("Anna HorĂˇkovĂˇ", ops, 200),
            ("Marek DvoĹ™Ăˇk", ops, 200),
            ("Petra NovĂˇ", ops, 200),
            ("Jakub ÄŚernĂ˝", risk, 200),
            ("Lucia VeselĂˇ", risk, 240),
        ]
        ids = {}
        for name, team, allow in people:
            cur.execute("INSERT INTO members(name, allowance) VALUES (?,?)", (name, allow))
            ids[name] = cur.lastrowid
            cur.execute(
                "INSERT INTO member_teams(member_id, team_id, start_date, end_date) VALUES (?,?,NULL,NULL)",
                (ids[name], team),
            )

        seed = [
            ("Petra NovĂˇ", "2026-06-01", "wfh"), ("Petra NovĂˇ", "2026-06-08", "wfh"),
            ("Petra NovĂˇ", "2026-06-15", "wfh"), ("Petra NovĂˇ", "2026-06-22", "wfh"),
            ("Anna HorĂˇkovĂˇ", "2026-06-03", "vac"), ("Marek DvoĹ™Ăˇk", "2026-06-03", "wfh"),
            ("Petra NovĂˇ", "2026-06-03", "wfh"),
            ("Petra NovĂˇ", "2026-06-10", "vac"), ("Marek DvoĹ™Ăˇk", "2026-06-10", "sck"),
            ("Anna HorĂˇkovĂˇ", "2026-06-09", "trp"), ("Anna HorĂˇkovĂˇ", "2026-06-10", "trp"),
            ("Marek DvoĹ™Ăˇk", "2026-06-16", "vac"), ("Marek DvoĹ™Ăˇk", "2026-06-17", "vac"),
            ("Marek DvoĹ™Ăˇk", "2026-06-18", "vac"),
            ("Jakub ÄŚernĂ˝", "2026-06-17", "vac"), ("Lucia VeselĂˇ", "2026-06-17", "sck"),
            ("Jakub ÄŚernĂ˝", "2026-06-04", "trp"), ("Jakub ÄŚernĂ˝", "2026-06-05", "trp"),
            ("Lucia VeselĂˇ", "2026-06-11", "flx"), ("Petra NovĂˇ", "2026-06-25", "fre"),
            ("Anna HorĂˇkovĂˇ", "2026-06-29", "flx"),
            ("Petra NovĂˇ", "2026-06-29", "vac"), ("Petra NovĂˇ", "2026-06-30", "vac"),
        ]
        for name, day, status in seed:
            cur.execute("INSERT INTO attendance(member_id, day, status) VALUES (?,?,?)",
                        (ids[name], day, status))
        conn.commit()
    conn.close()


# ------------------------------------------------------------------ #
#  Model building                                                     #
# ------------------------------------------------------------------ #
def effective_status(stored, weekend, holiday):
    """Stored status wins; otherwise normal weekdays default to 'in office'."""
    if stored:
        return stored
    if weekend or holiday:
        return None
    return "ofc"


def vacation_days_used(conn, member_id, year, exclude_dates=None):
    """Total vacation-equivalent days (full=1, half-day=0.5) used by member_id
    in the given calendar year, optionally excluding specific dates (e.g. ones
    about to be overwritten by the current request)."""
    exclude_dates = exclude_dates or set()
    rows = conn.execute(
        "SELECT day, status FROM attendance WHERE member_id=? AND status IN ('vac','hva') AND day LIKE ?",
        (member_id, f"{year}-%"),
    ).fetchall()
    return sum(VAC_WEIGHT[r["status"]] for r in rows if r["day"] not in exclude_dates)


def month_days(year, month):
    holidays = cz_holidays(year)
    today = date.today()
    count = monthrange(year, month)[1]
    days = []
    for d in range(1, count + 1):
        dt = date(year, month, d)
        iso = dt.isoformat()
        wd = dt.weekday()
        days.append({
            "d": d,
            "iso": iso,
            "wd": WD[wd],
            "weekend": wd >= 5,
            "holiday": holidays.get(iso),
            "today": dt == today,
        })
    return days


def build_model(year, month, me_id):
    conn = db()
    teams_rows = conn.execute("SELECT * FROM teams ORDER BY id").fetchall()
    members_rows = conn.execute("SELECT * FROM members ORDER BY id").fetchall()
    membership_rows = conn.execute(
        "SELECT member_id, team_id, start_date, end_date FROM member_teams"
    ).fetchall()
    att_rows = conn.execute(
        "SELECT member_id, day, status FROM attendance WHERE day LIKE ?",
        (f"{year:04d}-{month:02d}-%",),
    ).fetchall()
    conn.close()

    by_member = {}
    for r in att_rows:
        by_member.setdefault(r["member_id"], {})[r["day"]] = r["status"]

    memberships = [
        (r["member_id"], r["team_id"], r["start_date"], r["end_date"])
        for r in membership_rows
    ]

    def teams_on(member_id, day_iso):
        """Team ids member_id was an active member of on day_iso. A member can
        belong to several teams at once; date ranges preserve history when a
        membership is later closed and/or replaced."""
        return {
            team_id for (mid, team_id, start, end) in memberships
            if mid == member_id
            and (not start or start <= day_iso)
            and (not end or end >= day_iso)
        }

    days = month_days(year, month)
    members = [dict(r) for r in members_rows]
    if not any(m["id"] == me_id for m in members) and members:
        me_id = members[0]["id"]

    def build_people(group_members):
        people = []
        for m in group_members:
            stored = by_member.get(m["id"], {})
            cells = []
            for day in days:
                eff = effective_status(stored.get(day["iso"]), day["weekend"], day["holiday"])
                cells.append({
                    "iso": day["iso"],
                    "status": eff,
                    "weekend": day["weekend"],
                    "holiday": bool(day["holiday"]),
                })
            people.append({
                "id": m["id"],
                "name": m["name"],
                "is_me": m["id"] == me_id,
                "cells": cells,
            })
        return people

    teams = []
    for t in teams_rows:
        # who was active in this team on each day of the month
        day_member_ids = {
            day["iso"]: {m["id"] for m in members if t["id"] in teams_on(m["id"], day["iso"])}
            for day in days
        }
        # roster = anyone active in the team on at least one day this month,
        # so a mid-month switch still shows them where they actually were
        roster_ids = set().union(*day_member_ids.values()) if days else set()
        team_members = [m for m in members if m["id"] in roster_ids]

        cov = {}
        for day in days:
            if day["weekend"] or day["holiday"]:
                cov[day["iso"]] = {"state": "off", "working": 0, "min": t["min_working"]}
                continue
            working = 0
            for mid in day_member_ids[day["iso"]]:
                eff = effective_status(by_member.get(mid, {}).get(day["iso"]), False, False)
                if eff in WORKING:
                    working += 1
            min_w = t["min_working"]
            state = "low" if working < min_w else "tight" if working == min_w else "ok"
            cov[day["iso"]] = {"state": state, "working": working, "min": min_w}

        teams.append({
            "id": t["id"],
            "name": t["name"],
            "min": t["min_working"],
            "count": len(team_members),
            "people": build_people(team_members),
            "coverage": [{"iso": d["iso"], **cov[d["iso"]]} for d in days],
        })

    # unassigned = anyone with at least one day this month with no active team
    unassigned_ids = {
        m["id"] for m in members
        if any(not teams_on(m["id"], day["iso"]) for day in days)
    }
    unassigned = build_people([m for m in members if m["id"] in unassigned_ids])

    # admin "People" panel data â€” server-rendered, instant-save per action
    today_iso = date.today().isoformat()
    team_name_by_id = {t["id"]: t["name"] for t in teams_rows}
    current_team_members = {t["id"]: [] for t in teams_rows}
    current_unassigned_members = []
    member_pending_teams = {}   # mid -> [{team_id, team_name, start_date}]
    for m in members:
        tids = sorted(teams_on(m["id"], today_iso))
        if not tids:
            current_unassigned_members.append(m)
        else:
            for tid in tids:
                current_team_members[tid].append(m)
    for mid, team_id, start, end in memberships:
        if not (end and end < today_iso):   # still relevant (active or future)
            if start and start > today_iso:
                member_pending_teams.setdefault(mid, []).append({
                    "team_id": team_id,
                    "team_name": team_name_by_id.get(team_id, "?"),
                    "start_date": start,
                })
            elif end and end >= today_iso:
                member_pending_teams.setdefault(mid, []).append({
                    "team_id": team_id,
                    "team_name": team_name_by_id.get(team_id, "?"),
                    "end_date": end,
                })

    # personal vacation stats for "me"
    me = next((m for m in members if m["id"] == me_id), None)
    used_days = 0
    if me:
        conn = db()
        used_days = round(vacation_days_used(conn, me_id, year), 1)
        conn.close()
    my_stats = None
    if me:
        rem_h = me["allowance"] - used_days * 8
        my_stats = {
            "allowance": me["allowance"],
            "used_days": used_days,
            "rem_days": round(rem_h / 8, 1),
        }

    return {
        "year": year, "month": month, "month_name": MONTHS[month],
        "me_id": me_id, "members": members, "days": days,
        "teams": teams, "unassigned": unassigned, "my_stats": my_stats,
        "today_iso": today_iso,
        "current_team_members": current_team_members,
        "current_unassigned_members": current_unassigned_members,
        "member_pending_teams": member_pending_teams,
    }


# ------------------------------------------------------------------ #
#  Routes                                                             #
# ------------------------------------------------------------------ #
@app.route("/")
def index():
    today = date.today()
    year = request.args.get("year", default=today.year, type=int)
    month = request.args.get("month", default=today.month, type=int)
    me_id = request.args.get("me", default=0, type=int)

    # normalise month over/underflow
    while month < 1:
        month += 12; year -= 1
    while month > 12:
        month -= 12; year += 1

    model = build_model(year, month, me_id)
    prev_m, prev_y = (month - 1, year) if month > 1 else (12, year - 1)
    next_m, next_y = (month + 1, year) if month < 12 else (1, year + 1)
    return render_template(
        "index.html",
        model=model, STATUS=STATUS, ORDER=ORDER,
        prev={"y": prev_y, "m": prev_m},
        next={"y": next_y, "m": next_m},
        today={"y": today.year, "m": today.month},
        is_admin=bool(session.get("is_admin")),
    )


@app.route("/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json(force=True) or {}
    username = data.get("username", "")
    password = data.get("password", "")
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session["is_admin"] = True
        return jsonify(ok=True)
    return jsonify(ok=False, error="Invalid username or password"), 401


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("is_admin", None)
    return jsonify(ok=True)


def vacation_allowance_block(conn, member_id, dates, new_status):
    """Check whether setting new_status (vac or hva) for member_id would use
    more vacation days than their yearly allowance. Returns {"year", "name",
    "allowed_days", "used_before", "used_after"} describing the conflict, or
    None if OK. Allowance resets every calendar year."""
    if new_status not in VAC_WEIGHT:
        return None
    member = conn.execute("SELECT name, allowance FROM members WHERE id=?", (member_id,)).fetchone()
    if not member:
        return None
    allowed_days = member["allowance"] / 8

    by_year = {}
    for d in dates:
        by_year.setdefault(d[:4], []).append(d)

    for year, year_dates in by_year.items():
        existing_used = vacation_days_used(conn, member_id, year, exclude_dates=set(year_dates))
        used_after = round(existing_used + VAC_WEIGHT[new_status] * len(year_dates), 1)
        if used_after > allowed_days:
            return {
                "year": year,
                "name": member["name"],
                "allowed_days": round(allowed_days, 1),
                "used_before": round(existing_used, 1),
                "used_after": used_after,
            }
    return None


@app.route("/api/status", methods=["POST"])
def set_status():
    data = request.get_json(force=True)
    member_id = int(data["member_id"])
    dates = data.get("dates") or [data["date"]]
    status = data.get("status") or None
    if status not in STATUS:
        status = None

    me_id = data.get("me_id")
    if me_id is None or int(me_id) != member_id:
        abort(403)

    non_workdays = [
        d for d in dates
        if date.fromisoformat(d).weekday() >= 5 or d in cz_holidays(int(d[:4]))
    ]
    if non_workdays:
        return jsonify(
            ok=False,
            error="Weekends and public holidays don't carry a status â€” nothing to set on "
                  + ", ".join(non_workdays) + ".",
        ), 409

    conn = db()
    vac_block = vacation_allowance_block(conn, member_id, dates, status)
    if vac_block:
        conn.close()
        return jsonify(
            ok=False,
            error=(f"{vac_block['name']} only has {vac_block['allowed_days']} vacation days "
                   f"for {vac_block['year']} ({vac_block['used_before']} already used) â€” "
                   f"this request would use {vac_block['used_after']}."),
        ), 409

    try:
        for d in dates:
            if status:
                conn.execute(
                    "INSERT INTO attendance(member_id, day, status) VALUES (?,?,?) "
                    "ON CONFLICT(member_id, day) DO UPDATE SET status=excluded.status",
                    (member_id, d, status),
                )
            else:
                conn.execute("DELETE FROM attendance WHERE member_id=? AND day=?", (member_id, d))
        conn.commit()
    finally:
        conn.close()

    year, month = int(dates[0][:4]), int(dates[0][5:7])
    model = build_model(year, month, member_id)
    # a member can belong to several teams at once â€” report coverage for all
    # of the teams they appeared in during this month
    affected_teams = [
        {"team_id": t["id"], "coverage": t["coverage"]}
        for t in model["teams"]
        if any(p["id"] == member_id for p in t["people"])
    ]

    cells = []
    for d in dates:
        dt = date.fromisoformat(d)
        eff = status or effective_status(None, dt.weekday() >= 5, d in cz_holidays(dt.year))
        cells.append({"date": d, "status": eff})

    return jsonify({
        "ok": True,
        "member_id": member_id,
        "cells": cells,
        "teams": affected_teams,
        "my_stats": model["my_stats"],
    })


@app.route("/team", methods=["POST"])
@admin_required
def create_team():
    name = (request.form.get("name") or "").strip()
    min_w = request.form.get("min", type=int) or 0
    if name:
        conn = db()
        conn.execute("INSERT INTO teams(name, min_working) VALUES (?,?)", (name, min_w))
        conn.commit(); conn.close()
    return redirect(request.referrer or url_for("index"))


@app.route("/team/min", methods=["POST"])
@admin_required
def update_min():
    team_id = request.form.get("team_id", type=int)
    min_w = request.form.get("min", type=int) or 0
    conn = db()
    conn.execute("UPDATE teams SET min_working=? WHERE id=?", (min_w, team_id))
    conn.commit(); conn.close()
    return redirect(request.referrer or url_for("index"))


@app.route("/team/delete", methods=["POST"])
@admin_required
def delete_team():
    team_id = request.form.get("team_id", type=int)
    conn = db()
    conn.execute("DELETE FROM teams WHERE id=?", (team_id,))
    conn.commit(); conn.close()
    return redirect(request.referrer or url_for("index"))


@app.route("/member", methods=["POST"])
@admin_required
def add_member():
    name = (request.form.get("name") or "").strip()
    team_ids = request.form.getlist("team_ids", type=int)
    allowance = request.form.get("allowance", type=int) or 200
    if name:
        conn = db()
        cur = conn.execute("INSERT INTO members(name, allowance) VALUES (?,?)", (name, allowance))
        member_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO member_teams(member_id, team_id, start_date, end_date) VALUES (?,?,NULL,NULL)",
            [(member_id, team_id) for team_id in set(team_ids)],
        )
        conn.commit(); conn.close()
    return redirect(request.referrer or url_for("index"))


@app.route("/member/delete", methods=["POST"])
@admin_required
def delete_member():
    member_id = request.form.get("member_id", type=int)
    conn = db()
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit(); conn.close()
    return redirect(request.referrer or url_for("index"))


def _norm_date(value):
    """Validate/normalize a YYYY-MM-DD string; anything else becomes None."""
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        return None


@app.route("/member/teams/batch", methods=["POST"])
@admin_required
def update_member_teams_batch():
    """Apply a batch of team-membership edits made in the "Manage teams &
    people" panel. Body: JSON {"add": [...], "remove": [...], "update": [...]},
    each item {"member_id", "team_id"} plus "start_date"/"end_date" for add
    and update. Only rows still relevant today or later are ever touched â€”
    past history is never rewritten."""
    data = request.get_json(force=True) or {}
    today = date.today()
    today_iso = today.isoformat()
    yesterday_iso = (today - timedelta(days=1)).isoformat()

    conn = db()
    try:
        for item in data.get("add", []):
            conn.execute(
                "INSERT INTO member_teams(member_id, team_id, start_date, end_date) VALUES (?,?,?,?)",
                (item.get("member_id"), item.get("team_id"),
                 _norm_date(item.get("start_date")), _norm_date(item.get("end_date"))),
            )
        for item in data.get("update", []):
            row = conn.execute(
                "SELECT id FROM member_teams WHERE member_id=? AND team_id=? AND "
                "(end_date IS NULL OR end_date>=?) ORDER BY id DESC LIMIT 1",
                (item.get("member_id"), item.get("team_id"), today_iso),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE member_teams SET start_date=?, end_date=? WHERE id=?",
                    (_norm_date(item.get("start_date")), _norm_date(item.get("end_date")), row["id"]),
                )
        for item in data.get("remove", []):
            row = conn.execute(
                "SELECT id, start_date FROM member_teams WHERE member_id=? AND team_id=? AND "
                "(end_date IS NULL OR end_date>=?) ORDER BY id DESC LIMIT 1",
                (item.get("member_id"), item.get("team_id"), today_iso),
            ).fetchone()
            if not row:
                continue
            if row["start_date"] and row["start_date"] >= today_iso:
                # not started yet â€” cancel outright
                conn.execute("DELETE FROM member_teams WHERE id=?", (row["id"],))
            else:
                # active â€” ends as of today
                conn.execute("UPDATE member_teams SET end_date=? WHERE id=?", (yesterday_iso, row["id"]))
        conn.commit()
    finally:
        conn.close()
    return jsonify(ok=True)


@app.route("/member/team/add", methods=["POST"])
@admin_required
def member_team_add():
    member_id = request.form.get("member_id", type=int)
    team_id = request.form.get("team_id", type=int)
    if member_id and team_id:
        conn = db()
        try:
            conn.execute(
                "INSERT INTO member_teams(member_id, team_id, start_date, end_date) VALUES (?,?,NULL,NULL)",
                (member_id, team_id),
            )
            conn.commit()
        finally:
            conn.close()
    return redirect(request.referrer or url_for("index"))


@app.route("/member/team/remove", methods=["POST"])
@admin_required
def member_team_remove():
    member_id = request.form.get("member_id", type=int)
    team_id = request.form.get("team_id", type=int)
    today_iso = date.today().isoformat()
    yesterday_iso = (date.today() - timedelta(days=1)).isoformat()
    if member_id and team_id:
        conn = db()
        try:
            row = conn.execute(
                "SELECT id, start_date FROM member_teams WHERE member_id=? AND team_id=? AND "
                "(end_date IS NULL OR end_date>=?) ORDER BY id DESC LIMIT 1",
                (member_id, team_id, today_iso),
            ).fetchone()
            if row:
                if row["start_date"] and row["start_date"] >= today_iso:
                    conn.execute("DELETE FROM member_teams WHERE id=?", (row["id"],))
                else:
                    conn.execute("UPDATE member_teams SET end_date=? WHERE id=?", (yesterday_iso, row["id"]))
            conn.commit()
        finally:
            conn.close()
    return redirect(request.referrer or url_for("index"))


@app.route("/member/team/dates", methods=["POST"])
@admin_required
def member_team_dates():
    member_id = request.form.get("member_id", type=int)
    team_id = request.form.get("team_id", type=int)
    start = _norm_date(request.form.get("start_date"))
    end = _norm_date(request.form.get("end_date"))
    today_iso = date.today().isoformat()
    if member_id and team_id:
        conn = db()
        try:
            row = conn.execute(
                "SELECT id FROM member_teams WHERE member_id=? AND team_id=? AND "
                "(end_date IS NULL OR end_date>=?) ORDER BY id DESC LIMIT 1",
                (member_id, team_id, today_iso),
            ).fetchone()
            if row:
                conn.execute("UPDATE member_teams SET start_date=?, end_date=? WHERE id=?",
                             (start, end, row["id"]))
            conn.commit()
        finally:
            conn.close()
    return redirect(request.referrer or url_for("index"))


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=8080, debug=True)

