"""
Team Attendance Planner — Flask backend.

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
    "ofc": {"label": "In office",     "color": "#16A34A", "working": True},
    "wfh": {"label": "Home office",   "color": "#2563EB", "working": True},
    "trp": {"label": "Business trip", "color": "#7C3AED", "working": True},
    "vac": {"label": "Vacation",      "color": "#E08600", "working": False},
    "sck": {"label": "Sick",          "color": "#DC2626", "working": False},
    "flx": {"label": "Flexi day",     "color": "#0D9488", "working": False},
    "fre": {"label": "Free",          "color": "#64748B", "working": False},
}
ORDER = ["ofc", "wfh", "trp", "vac", "sck", "flx", "fre"]
WORKING = {k for k, v in STATUS.items() if v["working"]}

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
        date(year, 1, 1):   "Den obnovy samostatného českého státu",
        es - timedelta(days=2): "Velký pátek",
        es + timedelta(days=1): "Velikonoční pondělí",
        date(year, 5, 1):   "Svátek práce",
        date(year, 5, 8):   "Den vítězství",
        date(year, 7, 5):   "Den slovanských věrozvěstů Cyrila a Metoděje",
        date(year, 7, 6):   "Den upálení mistra Jana Husa",
        date(year, 9, 28):  "Den české státnosti",
        date(year, 10, 28): "Den vzniku samostatného československého státu",
        date(year, 11, 17): "Den boje za svobodu a demokracii",
        date(year, 12, 24): "Štědrý den",
        date(year, 12, 25): "1. svátek vánoční",
        date(year, 12, 26): "2. svátek vánoční",
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
            team_id   INTEGER REFERENCES teams(id) ON DELETE CASCADE,
            allowance INTEGER NOT NULL DEFAULT 200
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

    # Migrate older DBs where members.team_id was NOT NULL, so people can
    # exist without being assigned to a team yet.
    team_col = next((c for c in conn.execute("PRAGMA table_info(members)") if c["name"] == "team_id"), None)
    if team_col and team_col["notnull"]:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(
            """
            CREATE TABLE members_new (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                name      TEXT NOT NULL,
                team_id   INTEGER REFERENCES teams(id) ON DELETE CASCADE,
                allowance INTEGER NOT NULL DEFAULT 200
            );
            INSERT INTO members_new(id, name, team_id, allowance)
                SELECT id, name, team_id, allowance FROM members;
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
            ("Anna Horáková", ops, 200),
            ("Marek Dvořák", ops, 200),
            ("Petra Nová", ops, 200),
            ("Jakub Černý", risk, 200),
            ("Lucia Veselá", risk, 240),
        ]
        ids = {}
        for name, team, allow in people:
            cur.execute("INSERT INTO members(name, team_id, allowance) VALUES (?,?,?)", (name, team, allow))
            ids[name] = cur.lastrowid

        seed = [
            ("Petra Nová", "2026-06-01", "wfh"), ("Petra Nová", "2026-06-08", "wfh"),
            ("Petra Nová", "2026-06-15", "wfh"), ("Petra Nová", "2026-06-22", "wfh"),
            ("Anna Horáková", "2026-06-03", "vac"), ("Marek Dvořák", "2026-06-03", "wfh"),
            ("Petra Nová", "2026-06-03", "wfh"),
            ("Petra Nová", "2026-06-10", "vac"), ("Marek Dvořák", "2026-06-10", "sck"),
            ("Anna Horáková", "2026-06-09", "trp"), ("Anna Horáková", "2026-06-10", "trp"),
            ("Marek Dvořák", "2026-06-16", "vac"), ("Marek Dvořák", "2026-06-17", "vac"),
            ("Marek Dvořák", "2026-06-18", "vac"),
            ("Jakub Černý", "2026-06-17", "vac"), ("Lucia Veselá", "2026-06-17", "sck"),
            ("Jakub Černý", "2026-06-04", "trp"), ("Jakub Černý", "2026-06-05", "trp"),
            ("Lucia Veselá", "2026-06-11", "flx"), ("Petra Nová", "2026-06-25", "fre"),
            ("Anna Horáková", "2026-06-29", "flx"),
            ("Petra Nová", "2026-06-29", "vac"), ("Petra Nová", "2026-06-30", "vac"),
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


def coverage_for_team(team_min, people_statuses, days):
    """people_statuses: list of {iso: stored_status}. Returns iso -> dict."""
    out = {}
    for day in days:
        if day["weekend"] or day["holiday"]:
            out[day["iso"]] = {"state": "off", "working": 0, "min": team_min}
            continue
        working = 0
        for statuses in people_statuses:
            eff = effective_status(statuses.get(day["iso"]), day["weekend"], day["holiday"])
            if eff in WORKING:
                working += 1
        if working < team_min:
            state = "low"
        elif working == team_min:
            state = "tight"
        else:
            state = "ok"
        out[day["iso"]] = {"state": state, "working": working, "min": team_min}
    return out


def build_model(year, month, me_id):
    conn = db()
    teams_rows = conn.execute("SELECT * FROM teams ORDER BY id").fetchall()
    members_rows = conn.execute("SELECT * FROM members ORDER BY id").fetchall()
    att_rows = conn.execute(
        "SELECT member_id, day, status FROM attendance WHERE day LIKE ?",
        (f"{year:04d}-{month:02d}-%",),
    ).fetchall()
    conn.close()

    by_member = {}
    for r in att_rows:
        by_member.setdefault(r["member_id"], {})[r["day"]] = r["status"]

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
        team_members = [m for m in members if m["team_id"] == t["id"]]
        people_statuses = [by_member.get(m["id"], {}) for m in team_members]
        cov = coverage_for_team(t["min_working"], people_statuses, days)

        teams.append({
            "id": t["id"],
            "name": t["name"],
            "min": t["min_working"],
            "count": len(team_members),
            "people": build_people(team_members),
            "coverage": [{"iso": d["iso"], **cov[d["iso"]]} for d in days],
        })

    unassigned_members = [m for m in members if m["team_id"] is None]
    unassigned = build_people(unassigned_members)

    # personal vacation stats for "me"
    me = next((m for m in members if m["id"] == me_id), None)
    used_days = 0
    if me:
        conn = db()
        used_days = conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE member_id=? AND status='vac' AND day LIKE ?",
            (me_id, f"{year:04d}-%"),
        ).fetchone()[0]
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
    """Check whether setting new_status='vac' for member_id would use more
    vacation days than their yearly allowance. Returns {"year", "name",
    "allowed_days", "used_before", "used_after"} describing the conflict, or
    None if OK. Allowance resets every calendar year."""
    if new_status != "vac":
        return None
    member = conn.execute("SELECT name, allowance FROM members WHERE id=?", (member_id,)).fetchone()
    if not member:
        return None
    allowed_days = member["allowance"] / 8

    by_year = {}
    for d in dates:
        by_year.setdefault(d[:4], []).append(d)

    for year, year_dates in by_year.items():
        existing_days = {
            r["day"] for r in conn.execute(
                "SELECT day FROM attendance WHERE member_id=? AND status='vac' AND day LIKE ?",
                (member_id, f"{year}-%"),
            ).fetchall()
        }
        used_after = len(existing_days | set(year_dates))
        if used_after > allowed_days:
            return {
                "year": year,
                "name": member["name"],
                "allowed_days": round(allowed_days, 1),
                "used_before": len(existing_days),
                "used_after": used_after,
            }
    return None


def team_min_blocks(conn, team_id, member_id, dates, new_status):
    """Check whether setting new_status for member_id on the given dates would
    drop the team below its minimum working headcount on any weekday/non-holiday
    date where this member is currently counted as working. Returns
    {"team", "min", "dates"} describing the conflict, or None if OK."""
    if not team_id or new_status is None or new_status in WORKING:
        return None
    team = conn.execute("SELECT name, min_working FROM teams WHERE id=?", (team_id,)).fetchone()
    if not team:
        return None
    candidate_dates = [
        d for d in dates
        if date.fromisoformat(d).weekday() < 5 and d not in cz_holidays(int(d[:4]))
    ]
    if not candidate_dates:
        return None

    day_ph = ",".join("?" * len(candidate_dates))
    own_rows = conn.execute(
        f"SELECT day, status FROM attendance WHERE member_id=? AND day IN ({day_ph})",
        (member_id, *candidate_dates),
    ).fetchall()
    own_stored = {r["day"]: r["status"] for r in own_rows}
    # only dates where this member currently counts as working are actually at risk —
    # switching between two non-working statuses never reduces coverage.
    at_risk_dates = [d for d in candidate_dates if effective_status(own_stored.get(d), False, False) in WORKING]
    if not at_risk_dates:
        return None

    other_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM members WHERE team_id=? AND id!=?", (team_id, member_id)).fetchall()]
    stored = {}
    if other_ids:
        id_ph = ",".join("?" * len(other_ids))
        risk_ph = ",".join("?" * len(at_risk_dates))
        rows = conn.execute(
            f"SELECT member_id, day, status FROM attendance "
            f"WHERE member_id IN ({id_ph}) AND day IN ({risk_ph})",
            (*other_ids, *at_risk_dates),
        ).fetchall()
        for r in rows:
            stored[(r["member_id"], r["day"])] = r["status"]
    blocked = [
        d for d in at_risk_dates
        if sum(1 for mid in other_ids
               if effective_status(stored.get((mid, d)), False, False) in WORKING) < team["min_working"]
    ]
    if not blocked:
        return None
    return {"team": team["name"], "min": team["min_working"], "dates": blocked}


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
            error="Weekends and public holidays don't carry a status — nothing to set on "
                  + ", ".join(non_workdays) + ".",
        ), 409

    conn = db()
    row = conn.execute("SELECT team_id FROM members WHERE id=?", (member_id,)).fetchone()
    team_id = row["team_id"] if row else None

    vac_block = vacation_allowance_block(conn, member_id, dates, status)
    if vac_block:
        conn.close()
        return jsonify(
            ok=False,
            error=(f"{vac_block['name']} only has {vac_block['allowed_days']} vacation days "
                   f"for {vac_block['year']} ({vac_block['used_before']} already used) — "
                   f"this request would use {vac_block['used_after']}."),
        ), 409

    block = team_min_blocks(conn, team_id, member_id, dates, status)
    if block:
        conn.close()
        dates_str = ", ".join(block["dates"])
        return jsonify(
            ok=False,
            error=(f"{block['team']} needs at least {block['min']} people working — "
                   f"this would drop below minimum on {dates_str}."),
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
    team = next((t for t in model["teams"] if t["id"] == team_id), None)

    cells = []
    for d in dates:
        dt = date.fromisoformat(d)
        eff = status or effective_status(None, dt.weekday() >= 5, d in cz_holidays(dt.year))
        cells.append({"date": d, "status": eff})

    return jsonify({
        "ok": True,
        "member_id": member_id,
        "team_id": team_id,
        "cells": cells,
        "coverage": team["coverage"] if team else [],
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
    team_id = request.form.get("team_id", type=int)
    allowance = request.form.get("allowance", type=int) or 200
    if name:
        conn = db()
        conn.execute("INSERT INTO members(name, team_id, allowance) VALUES (?,?,?)",
                     (name, team_id, allowance))
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


@app.route("/member/team", methods=["POST"])
@admin_required
def update_member_team():
    member_id = request.form.get("member_id", type=int)
    team_id = request.form.get("team_id", type=int)
    conn = db()
    conn.execute("UPDATE members SET team_id=? WHERE id=?", (team_id, member_id))
    conn.commit(); conn.close()
    return redirect(request.referrer or url_for("index"))


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=8080, debug=True)
