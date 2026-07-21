import os
import json
from os import getenv
import secrets
from datetime import date, timedelta
from calendar import monthrange
from functools import wraps

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, session, abort, flash, get_flashed_messages, send_from_directory

bp_main = Blueprint('main', __name__, template_folder='templates', static_folder='static')

STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')

@bp_main.route('/style.css')
def serve_css():
    return send_from_directory(os.path.join(STATIC_DIR, 'styles'), 'style.css', mimetype='text/css')

@bp_main.route('/app.js')
def serve_js():
    return send_from_directory(STATIC_DIR, 'app.js', mimetype='application/javascript')

import sys as _sys
_default_data = "/tmp/attendance_data" if _sys.platform != "win32" else os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
BASE_DIR = getenv("DATA_DIR", _default_data)
os.makedirs(BASE_DIR, exist_ok=True)
DB_PATH = os.path.join(BASE_DIR, "attendance.db")

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "1234"

_CREDS_FILE = os.path.join(BASE_DIR, "admin_creds.json")


def _get_creds():
    if os.path.exists(_CREDS_FILE):
        try:
            with open(_CREDS_FILE) as f:
                d = json.load(f)
                return d.get("username", ADMIN_USERNAME), d.get("password", ADMIN_PASSWORD)
        except Exception:
            pass
    return ADMIN_USERNAME, ADMIN_PASSWORD

# ── database backend ──────────────────────────────────────────────────────────
_USE_PG = bool(getenv("DOCHAZKA_1_HOST"))
_Q = "%s" if _USE_PG else "?"


def _sql(query):
    return query.replace("?", "%s") if _USE_PG else query


def _execute_id(conn, sql, params=()):
    if _USE_PG:
        return conn.execute(sql + " RETURNING id", params).fetchone()["id"]
    return conn.execute(sql, params).lastrowid


def _count(row):
    if isinstance(row, dict):
        return list(row.values())[0]
    return row[0]


if _USE_PG:
    import psycopg2
    import psycopg2.extras

    class _Conn:
        def __init__(self, conn):
            self._conn = conn
            self._cur = conn.cursor()

        def execute(self, sql, params=()):
            self._cur.execute(sql.replace("?", "%s"), params)
            return self._cur

        def executemany(self, sql, params_list):
            self._cur.executemany(sql.replace("?", "%s"), params_list)
            return self._cur

        def cursor(self):
            return self._conn.cursor()

        def commit(self):
            self._conn.commit()

        def close(self):
            self._conn.close()

    def db():
        conn = psycopg2.connect(
            host=getenv("DOCHAZKA_1_HOST"),
            port=getenv("DOCHAZKA_1_PORT", "5432"),
            dbname=getenv("DOCHAZKA_1_DATABASE_NAME"),
            user=getenv("DOCHAZKA_1_USERNAME"),
            password=getenv("DOCHAZKA_1_PASSWORD"),
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        return _Conn(conn)
else:
    import sqlite3

    def db():
        conn = sqlite3.connect(DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


STATUS = {
    "wrk": {"label": "Work",              "color": "#16A34A", "working": True},
    "vac": {"label": "Vacation",          "color": "#E08600", "working": False},
    "hva": {"label": "Half-day vacation", "color": "#E08600", "working": False},
    "flx": {"label": "Flexi Day",         "color": "#0D9488", "working": False},
    "rst": {"label": "Restart Day",       "color": "#7C3AED", "working": False},
    "ple": {"label": "Paid Leave",        "color": "#2563EB", "working": False},
    "fic": {"label": "Fictional",         "color": "#DB2777", "working": False},
    "upl": {"label": "Unpaid Leave",      "color": "#64748B", "working": False},
    "lyr": {"label": "Last Year",         "color": "#0891B2", "working": False, "no_allowance": True},
    "bdy": {"label": "Birthday",          "color": "#D97706", "working": False, "no_allowance": True},
    "chr": {"label": "Charity",           "color": "#E11D48", "working": False, "no_allowance": True},
}
ORDER = ["wrk", "vac", "hva", "flx", "rst", "ple", "fic", "upl", "lyr", "bdy", "chr"]
WORKING = {k for k, v in STATUS.items() if v["working"]}

VAC_WEIGHT = {"vac": 1.0, "hva": 0.5, "flx": 1.0, "rst": 1.0, "ple": 1.0, "fic": 1.0}

MONTHS = ["", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]
WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def easter_sunday(year: int) -> date:
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
    if year in _holiday_cache:
        return _holiday_cache[year]
    es = easter_sunday(year)
    items = {
        date(year, 1, 1):   "Den obnovy samostatneho ceskeho statu",
        es - timedelta(days=2): "Velky patek",
        es + timedelta(days=1): "Velikonocni pondeli",
        date(year, 5, 1):   "Svatek prace",
        date(year, 5, 8):   "Den vitezstvi",
        date(year, 7, 5):   "Den slovanskych verozvest Cyrila a Metodeje",
        date(year, 7, 6):   "Den upaleni mistra Jana Husa",
        date(year, 9, 28):  "Den ceske statnosti",
        date(year, 10, 28): "Den vzniku samostatneho ceskoslovenskeho statu",
        date(year, 11, 17): "Den boje za svobodu a demokracii",
        date(year, 12, 24): "Stedry den",
        date(year, 12, 25): "1. svatek vanocni",
        date(year, 12, 26): "2. svatek vanocni",
    }
    result = {d.isoformat(): name for d, name in items.items()}
    _holiday_cache[year] = result
    return result


def init_db():
    conn = db()

    if not _USE_PG:
        conn.execute("PRAGMA foreign_keys = OFF")
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
                allowance INTEGER NOT NULL DEFAULT 200,
                fraction  REAL NOT NULL DEFAULT 1.0
            );
            CREATE TABLE IF NOT EXISTS member_teams (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id   INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                team_id     INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                start_date  TEXT,
                end_date    TEXT
            );
            CREATE TABLE IF NOT EXISTS attendance (
                member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                day       TEXT NOT NULL,
                status    TEXT NOT NULL,
                PRIMARY KEY (member_id, day)
            );
            CREATE TABLE IF NOT EXISTS duty_schedules (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id     INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                name        TEXT NOT NULL DEFAULT 'Rotation',
                start_date  TEXT NOT NULL,
                end_date    TEXT,
                period_days INTEGER NOT NULL DEFAULT 7,
                active      INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS duty_slots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                schedule_id INTEGER NOT NULL REFERENCES duty_schedules(id) ON DELETE CASCADE,
                day_offset  INTEGER NOT NULL,
                member_id   INTEGER REFERENCES members(id) ON DELETE SET NULL,
                UNIQUE(schedule_id, day_offset)
            );
            CREATE TABLE IF NOT EXISTS duty_replacements (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id     INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                replacer_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                replaced_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
                date        TEXT NOT NULL,
                year        INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS member_allowances (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id   INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                year        INTEGER NOT NULL,
                allowance   INTEGER NOT NULL,
                UNIQUE(member_id, year)
            );
            CREATE TABLE IF NOT EXISTS duty_members (
                team_id   INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                PRIMARY KEY (team_id, member_id)
            );
            """
        )
        conn.commit()

        mem_cols = {c["name"] for c in conn.execute("PRAGMA table_info(members)")}
        if "fraction" not in mem_cols:
            conn.execute("ALTER TABLE members ADD COLUMN fraction REAL NOT NULL DEFAULT 1.0")
            conn.commit()

        ds_cols = {c["name"] for c in conn.execute("PRAGMA table_info(duty_schedules)")}
        if "end_date" not in ds_cols:
            conn.execute("ALTER TABLE duty_schedules ADD COLUMN end_date TEXT")
            conn.commit()

        dr_cols = {c["name"] for c in conn.execute("PRAGMA table_info(duty_replacements)")}
        if "manual" not in dr_cols:
            conn.execute("ALTER TABLE duty_replacements ADD COLUMN manual INTEGER DEFAULT 0")
            conn.commit()

        idx_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='uq_duty_rep_team_date'"
        ).fetchone()
        if not idx_exists:
            conn.execute("""
                DELETE FROM duty_replacements WHERE id NOT IN (
                    SELECT MIN(id) FROM duty_replacements GROUP BY team_id, date
                )
            """)
            conn.execute(
                "CREATE UNIQUE INDEX uq_duty_rep_team_date ON duty_replacements(team_id, date)"
            )
            conn.commit()

        team_col = next((c for c in conn.execute("PRAGMA table_info(members)") if c["name"] == "team_id"), None)
        if team_col:
            rows = conn.execute("SELECT id, team_id FROM members WHERE team_id IS NOT NULL").fetchall()
            if rows:
                conn.executemany(
                    "INSERT INTO member_teams(member_id, team_id, start_date, end_date) VALUES (?,?,NULL,NULL)",
                    [(r["id"], r["team_id"]) for r in rows],
                )
            try:
                conn.execute("ALTER TABLE members DROP COLUMN team_id")
            except Exception:
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

        m_cols = {c["name"] for c in conn.execute("PRAGMA table_info(members)")}
        if "cza" not in m_cols:
            conn.execute("ALTER TABLE members ADD COLUMN cza TEXT")
            conn.commit()

        conn.execute("PRAGMA foreign_keys = ON")

    old_to_new = {"ofc": "wrk", "wfh": "wrk", "trp": "wrk", "sck": "upl", "fre": "upl"}
    for old, new in old_to_new.items():
        conn.execute(_sql("UPDATE attendance SET status=? WHERE status=?"), (new, old))
    conn.commit()

    conn.close()


def effective_status(stored, weekend, holiday):
    if stored:
        return stored
    if weekend or holiday:
        return None
    return "wrk"


def get_allowance(conn, member_id, year) -> int:
    row = conn.execute(
        _sql("SELECT allowance FROM member_allowances WHERE member_id=? AND year=?"),
        (member_id, year),
    ).fetchone()
    if row:
        return row["allowance"]
    prev = conn.execute(
        _sql("SELECT allowance FROM member_allowances WHERE member_id=? AND year<? ORDER BY year DESC LIMIT 1"),
        (member_id, year),
    ).fetchone()
    if prev:
        return prev["allowance"]
    row = conn.execute(_sql("SELECT allowance FROM members WHERE id=?"), (member_id,)).fetchone()
    return row["allowance"] if row else 200


def vacation_days_used(conn, member_id, year, exclude_dates=None):
    exclude_dates = exclude_dates or set()
    placeholders = ",".join(f"'{k}'" for k in VAC_WEIGHT)
    rows = conn.execute(
        f"SELECT day, status FROM attendance WHERE member_id=? AND status IN ({placeholders}) AND day LIKE ?",
        (member_id, f"{year}-%"),
    ).fetchall()
    frow = conn.execute(_sql("SELECT fraction FROM members WHERE id=?"), (member_id,)).fetchone()
    fraction = (frow["fraction"] if frow and frow["fraction"] is not None else 1.0)
    return sum(VAC_WEIGHT[r["status"]] * fraction for r in rows if r["day"] not in exclude_dates)


def birthday_block(conn, member_id, dates, new_status):
    if new_status != "bdy":
        return None
    for d in dates:
        year = d[:4]
        already = _count(conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE member_id=? AND status='bdy' AND day LIKE ? AND day NOT IN (%s)"
            % ",".join("?" * len(dates)),
            (member_id, f"{year}-%", *dates),
        ).fetchone())
        if already >= 1:
            return {"year": year}
    return None


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
        return {
            team_id for (mid, team_id, start, end) in memberships
            if mid == member_id
            and (not start or start <= day_iso)
            and (not end or end >= day_iso)
        }

    days = month_days(year, month)
    members = [dict(r) for r in members_rows]
    if me_id and not any(m["id"] == me_id for m in members) and members:
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
        day_member_ids = {
            day["iso"]: {m["id"] for m in members if t["id"] in teams_on(m["id"], day["iso"])}
            for day in days
        }
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

    members_in_team_roster = {p["id"] for t_data in teams for p in t_data["people"]}
    unassigned_ids = {m["id"] for m in members if m["id"] not in members_in_team_roster}
    unassigned = build_people([m for m in members if m["id"] in unassigned_ids])

    today_iso = date.today().isoformat()
    team_name_by_id = {t["id"]: t["name"] for t in teams_rows}

    member_all_team_ids = {}
    for mid, team_id, start, end in memberships:
        if end and end < today_iso:
            continue
        member_all_team_ids.setdefault(mid, set()).add(team_id)

    current_team_members = {t["id"]: [] for t in teams_rows}
    current_unassigned_members = []
    member_pending_teams = {}
    for m in members:
        all_tids = member_all_team_ids.get(m["id"], set())
        if not all_tids:
            current_unassigned_members.append(m)
        else:
            for tid in sorted(all_tids):
                if tid in current_team_members:
                    current_team_members[tid].append(m)

    member_membership_dates = {}
    for mid, team_id, start, end in memberships:
        if not (end and end < today_iso):
            existing = member_membership_dates.get(mid, {}).get(team_id)
            if not existing or (start or "") > (existing["start_date"] or ""):
                member_membership_dates.setdefault(mid, {})[team_id] = {
                    "start_date": start, "end_date": end
                }
            if not (end and end < today_iso):
                if start and start >= today_iso:
                    member_pending_teams.setdefault(mid, []).append({
                        "team_id": team_id,
                        "team_name": team_name_by_id.get(team_id, "?"),
                        "start_date": start,
                    })
                if end and end >= today_iso:
                    member_pending_teams.setdefault(mid, []).append({
                        "team_id": team_id,
                        "team_name": team_name_by_id.get(team_id, "?"),
                        "end_date": end,
                    })

    conn_all = db()
    member_allowances_year = {
        m["id"]: get_allowance(conn_all, m["id"], year) for m in members
    }
    conn_all.close()

    me = next((m for m in members if m["id"] == me_id), None)
    used_days = 0
    if me:
        conn = db()
        used_days = round(vacation_days_used(conn, me_id, year), 1)
        me_allowance = member_allowances_year[me_id]
        conn.close()
    my_stats = None
    if me:
        rem_h = me_allowance - used_days * 8
        my_stats = {
            "allowance": me_allowance,
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
        "member_membership_dates": member_membership_dates,
        "member_allowances_year": member_allowances_year,
    }


def _get_kerberos_me(conn):
    """Try Kerberos identification. Returns member id (int), None (no match), or False (local dev)."""
    try:
        from idm.idm_auth import idm_get_ticket_kerberos
    except ImportError:
        return False
    try:
        ticket = idm_get_ticket_kerberos()
        if ticket:
            row = conn.execute(_sql("SELECT id FROM members WHERE cza=?"), (ticket,)).fetchone()
            if row:
                return row["id"]
    except Exception:
        pass
    return None


@bp_main.route("/")
def index():
    today = date.today()
    year = request.args.get("year", default=today.year, type=int)
    month = request.args.get("month", default=today.month, type=int)

    while month < 1:
        month += 12; year -= 1
    while month > 12:
        month -= 12; year += 1

    conn = db()
    kerb = _get_kerberos_me(conn)
    conn.close()

    kerberos_active = kerb is not False
    if kerberos_active:
        me_id = kerb or 0
        kerberos_identified = kerb is not None
    else:
        me_id = request.args.get("me", default=0, type=int)
        kerberos_identified = False

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
        kerberos_active=kerberos_active,
        kerberos_identified=kerberos_identified,
    )



@bp_main.route("/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json(force=True) or {}
    username = data.get("username", "")
    password = data.get("password", "")
    stored_user, stored_pass = _get_creds()
    if username == stored_user and password == stored_pass:
        session["is_admin"] = True
        return jsonify(ok=True)
    return jsonify(ok=False, error="Invalid username or password"), 401


@bp_main.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("is_admin", None)
    return jsonify(ok=True)


@bp_main.route("/admin/credentials", methods=["POST"])
def update_admin_credentials():
    data = request.get_json(force=True) or {}
    current_password = (data.get("current_password") or "").strip()
    new_username = (data.get("new_username") or "").strip()
    new_password = (data.get("new_password") or "").strip()
    if not current_password or not new_username or not new_password:
        return jsonify(ok=False, error="All fields are required"), 400
    _, stored_pass = _get_creds()
    if current_password != stored_pass:
        return jsonify(ok=False, error="Incorrect current password"), 401
    try:
        with open(_CREDS_FILE, "w") as f:
            json.dump({"username": new_username, "password": new_password}, f)
    except Exception:
        return jsonify(ok=False, error="Failed to save credentials"), 500
    return jsonify(ok=True)


def vacation_allowance_block(conn, member_id, dates, new_status):
    if new_status not in VAC_WEIGHT:
        return None
    member = conn.execute("SELECT name FROM members WHERE id=?", (member_id,)).fetchone()
    if not member:
        return None

    by_year = {}
    for d in dates:
        by_year.setdefault(d[:4], []).append(d)

    for year, year_dates in by_year.items():
        allowed_days = get_allowance(conn, member_id, int(year)) / 8
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


@bp_main.route("/api/status", methods=["POST"])
def set_status():
    data = request.get_json(force=True)
    member_id = int(data["member_id"])
    dates = data.get("dates") or [data["date"]]
    status = data.get("status") or None
    if status not in STATUS:
        status = None

    if not session.get("is_admin"):
        conn_auth = db()
        kerb = _get_kerberos_me(conn_auth)
        conn_auth.close()
        if kerb is False:
            me_id = data.get("me_id")
            if me_id is None or int(me_id) != member_id:
                abort(403)
        elif kerb != member_id:
            abort(403)

    non_workdays = [
        d for d in dates
        if date.fromisoformat(d).weekday() >= 5 or d in cz_holidays(int(d[:4]))
    ]
    if non_workdays:
        return jsonify(
            ok=False,
            error="Weekends and public holidays don't carry a status - nothing to set on "
                  + ", ".join(non_workdays) + ".",
        ), 409

    conn = db()
    vac_block = vacation_allowance_block(conn, member_id, dates, status)
    if vac_block:
        conn.close()
        return jsonify(
            ok=False,
            error=(f"{vac_block['name']} only has {vac_block['allowed_days']} vacation days "
                   f"for {vac_block['year']} ({vac_block['used_before']} already used) - "
                   f"this request would use {vac_block['used_after']}."),
        ), 409

    bday_block = birthday_block(conn, member_id, dates, status)
    if bday_block:
        conn.close()
        return jsonify(
            ok=False,
            error=f"Birthday day already used in {bday_block['year']} - only one per year is allowed.",
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

    new_eff = effective_status(status, False, False)
    conn2 = db()
    try:
        for d in dates:
            dt = date.fromisoformat(d)
            team_ids = [r["team_id"] for r in conn2.execute(
                "SELECT team_id FROM member_teams WHERE member_id=? "
                "AND (start_date IS NULL OR start_date<=?) AND (end_date IS NULL OR end_date>=?)",
                (member_id, d, d),
            ).fetchall()]
            for tid in team_ids:
                if new_eff not in WORKING:
                    conn2.execute(
                        "DELETE FROM duty_replacements "
                        "WHERE team_id=? AND date=? AND replacer_id=? AND manual=0",
                        (tid, d, member_id),
                    )
                else:
                    sched = conn2.execute(
                        "SELECT * FROM duty_schedules WHERE team_id=? AND active=1 "
                        "AND start_date<=? AND (end_date IS NULL OR end_date>=?) "
                        "ORDER BY start_date DESC LIMIT 1",
                        (tid, d, d),
                    ).fetchone()
                    if not sched:
                        continue
                    start_d = date.fromisoformat(sched["start_date"])
                    wd_count = 0
                    cur = start_d
                    while cur < dt:
                        if cur.weekday() < 5:  # count all weekdays including holidays
                            wd_count += 1
                        cur += timedelta(days=1)
                    day_in_cycle = wd_count % sched["period_days"]
                    slot = conn2.execute(
                        "SELECT member_id FROM duty_slots WHERE schedule_id=? AND day_offset=?",
                        (sched["id"], day_in_cycle),
                    ).fetchone()
                    if slot and slot["member_id"] == member_id:
                        conn2.execute(
                            "DELETE FROM duty_replacements WHERE team_id=? AND date=? AND manual=0",
                            (tid, d),
                        )
        conn2.commit()
    finally:
        conn2.close()

    year, month = int(dates[0][:4]), int(dates[0][5:7])
    model = build_model(year, month, member_id)
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


@bp_main.route("/team", methods=["POST"])
@admin_required
def create_team():
    name = (request.form.get("name") or "").strip()
    min_w = request.form.get("min", type=int) or 0
    if name:
        conn = db()
        conn.execute("INSERT INTO teams(name, min_working) VALUES (?,?)", (name, min_w))
        conn.commit(); conn.close()
    return redirect(request.referrer or url_for("main.index"))


@bp_main.route("/member/allowance", methods=["POST"])
@admin_required
def update_member_allowance():
    member_id = request.form.get("member_id", type=int)
    year = request.form.get("year", type=int)
    allowance = request.form.get("allowance", type=int)
    if not member_id or not year or allowance is None:
        return redirect(request.referrer or url_for("main.index"))
    conn = db()
    conn.execute(
        "INSERT INTO member_allowances(member_id, year, allowance) VALUES (?,?,?) "
        "ON CONFLICT(member_id, year) DO UPDATE SET allowance=excluded.allowance",
        (member_id, year, allowance),
    )
    conn.commit(); conn.close()
    return redirect(request.referrer or url_for("main.index"))


@bp_main.route("/team/min", methods=["POST"])
@admin_required
def update_min():
    team_id = request.form.get("team_id", type=int)
    min_w = request.form.get("min", type=int) or 0
    conn = db()
    conn.execute("UPDATE teams SET min_working=? WHERE id=?", (min_w, team_id))
    conn.commit(); conn.close()
    return redirect(request.referrer or url_for("main.index"))


@bp_main.route("/team/delete", methods=["POST"])
@admin_required
def delete_team():
    team_id = request.form.get("team_id", type=int)
    conn = db()
    conn.execute("DELETE FROM teams WHERE id=?", (team_id,))
    conn.commit(); conn.close()
    return redirect(request.referrer or url_for("main.index"))


@bp_main.route("/member", methods=["POST"])
@admin_required
def add_member():
    name = (request.form.get("name") or "").strip()
    cza = (request.form.get("cza") or "").strip() or None
    team_ids = request.form.getlist("team_ids", type=int)
    allowance = request.form.get("allowance", type=int) or 200
    if request.form.get("allowance_unit") == "days":
        allowance = allowance * 8
    fraction = max(0.0, min(1.0, (request.form.get("fraction", type=float) or 100) / 100))
    if name:
        conn = db()
        existing = conn.execute("SELECT id FROM members WHERE name=?", (name,)).fetchone()
        if existing:
            conn.close()
            flash(f"A person named '{name}' already exists.")
        else:
            member_id = _execute_id(conn, _sql("INSERT INTO members(name, allowance, cza, fraction) VALUES (?,?,?,?)"), (name, allowance, cza, fraction))
            today_iso = date.today().isoformat()
            conn.executemany(
                "INSERT INTO member_teams(member_id, team_id, start_date, end_date) VALUES (?,?,?,NULL)",
                [(member_id, team_id, today_iso) for team_id in set(team_ids)],
            )
            conn.commit()
            conn.close()
    return redirect(request.referrer or url_for("main.index"))


@bp_main.route("/member/rename", methods=["POST"])
@admin_required
def rename_member():
    member_id = request.form.get("member_id", type=int)
    name = (request.form.get("name") or "").strip()
    if member_id and name:
        conn = db()
        conn.execute(_sql("UPDATE members SET name=? WHERE id=?"), (name, member_id))
        conn.commit()
        conn.close()
    return redirect(request.referrer or url_for("main.index"))


@bp_main.route("/member/fraction", methods=["POST"])
@admin_required
def update_member_fraction():
    member_id = request.form.get("member_id", type=int)
    fraction_pct = request.form.get("fraction", type=float)
    if member_id and fraction_pct is not None:
        fraction = max(0.0, min(1.0, fraction_pct / 100))
        conn = db()
        conn.execute(_sql("UPDATE members SET fraction=? WHERE id=?"), (fraction, member_id))
        conn.commit()
        conn.close()
    return redirect(request.referrer or url_for("main.index"))


@bp_main.route("/member/cza", methods=["POST"])
@admin_required
def update_member_cza():
    member_id = request.form.get("member_id", type=int)
    cza = (request.form.get("cza") or "").strip() or None
    if member_id:
        conn = db()
        conn.execute(_sql("UPDATE members SET cza=? WHERE id=?"), (cza, member_id))
        conn.commit()
        conn.close()
    return redirect(request.referrer or url_for("main.index"))


@bp_main.route("/member/delete", methods=["POST"])
@admin_required
def delete_member():
    member_id = request.form.get("member_id", type=int)
    conn = db()
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit(); conn.close()
    return redirect(request.referrer or url_for("main.index"))


def _norm_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        return None


@bp_main.route("/member/teams/batch", methods=["POST"])
@admin_required
def update_member_teams_batch():
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
                conn.execute("DELETE FROM member_teams WHERE id=?", (row["id"],))
            else:
                conn.execute("UPDATE member_teams SET end_date=? WHERE id=?", (yesterday_iso, row["id"]))
        conn.commit()
    finally:
        conn.close()
    return jsonify(ok=True)


@bp_main.route("/member/team/add", methods=["POST"])
@admin_required
def member_team_add():
    member_id = request.form.get("member_id", type=int)
    team_id = request.form.get("team_id", type=int)
    if member_id and team_id:
        today = date.today().isoformat()
        conn = db()
        try:
            conn.execute(
                "INSERT INTO member_teams(member_id, team_id, start_date, end_date) VALUES (?,?,?,NULL)",
                (member_id, team_id, today),
            )
            conn.commit()
        finally:
            conn.close()
    return redirect(request.referrer or url_for("main.index"))


@bp_main.route("/member/team/remove", methods=["POST"])
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
    return redirect(request.referrer or url_for("main.index"))


@bp_main.route("/member/team/dates", methods=["POST"])
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
    return redirect(request.referrer or url_for("main.index"))


def get_monthly_duty(conn, team_id, year, month, duty_ineligible_ids=None):
    all_schedules = [dict(r) for r in conn.execute(
        "SELECT * FROM duty_schedules WHERE team_id=? ORDER BY start_date",
        (team_id,),
    ).fetchall()]
    if not all_schedules:
        return []

    all_schedule_ids = [s["id"] for s in all_schedules]
    id_ph = ",".join("?" * len(all_schedule_ids))
    all_slots = {}
    for r in conn.execute(
        f"SELECT schedule_id, day_offset, member_id FROM duty_slots WHERE schedule_id IN ({id_ph})",
        all_schedule_ids,
    ).fetchall():
        all_slots.setdefault(r["schedule_id"], {})[r["day_offset"]] = r["member_id"]

    def schedule_for(day_iso):
        for s in reversed(all_schedules):
            if s["start_date"] <= day_iso:
                if not s["end_date"] or s["end_date"] >= day_iso:
                    return s
        return None

    count = monthrange(year, month)[1]
    holidays = cz_holidays(year)
    month_prefix = f"{year:04d}-{month:02d}-"

    att_rows = conn.execute(
        "SELECT member_id, day, status FROM attendance WHERE day LIKE ?",
        (month_prefix + "%",),
    ).fetchall()
    att_map = {(r["member_id"], r["day"]): r["status"] for r in att_rows}

    rep_rows = conn.execute(
        "SELECT date, replacer_id, replaced_id, manual FROM duty_replacements "
        "WHERE team_id=? AND date LIKE ?",
        (team_id, month_prefix + "%"),
    ).fetchall()
    existing_rep = {r["date"]: (r["replacer_id"], r["replaced_id"], bool(r["manual"])) for r in rep_rows}

    cnt_rows = conn.execute(
        "SELECT replacer_id, COUNT(*) AS cnt FROM duty_replacements "
        "WHERE team_id=? AND year=? GROUP BY replacer_id",
        (team_id, year),
    ).fetchall()
    rep_counts = {r["replacer_id"]: r["cnt"] for r in cnt_rows}

    last_day = f"{year:04d}-{month:02d}-{count:02d}"
    first_day = month_prefix + "01"
    mt_rows = conn.execute(
        "SELECT m.id, mt.start_date, mt.end_date FROM members m "
        "JOIN member_teams mt ON mt.member_id=m.id "
        "WHERE mt.team_id=? "
        "AND (mt.end_date IS NULL OR mt.end_date>=?) "
        "AND (mt.start_date IS NULL OR mt.start_date<=?)",
        (team_id, first_day, last_day),
    ).fetchall()
    _memberships = [(r["id"], r["start_date"], r["end_date"]) for r in mt_rows]

    def members_active_on(day_iso: str) -> list:
        return [
            mid for mid, s, e in _memberships
            if (s is None or s <= day_iso) and (e is None or e >= day_iso)
        ]

    today = date.today()

    year_start = date(year, 1, 1)
    scan_end = min(today, date(year, 12, 31))
    sched_duty_counts: dict = {}
    _sched_wd: dict = {}
    scan_d = year_start
    while scan_d <= scan_end:
        if scan_d.weekday() < 5:  # all weekdays, holidays just get skipped
            iso_s = scan_d.isoformat()
            s = schedule_for(iso_s)
            if s:
                sid = s["id"]
                if sid not in _sched_wd:
                    s_start = date.fromisoformat(s["start_date"])
                    offset = 0
                    if s_start < year_start:
                        cur2 = s_start
                        while cur2 < year_start:
                            if cur2.weekday() < 5:  # count all weekdays
                                offset += 1
                            cur2 += timedelta(days=1)
                    _sched_wd[sid] = offset
                dic = _sched_wd[sid]
                if iso_s not in cz_holidays(scan_d.year):  # only count duty on non-holidays
                    slot_m = all_slots.get(sid, {}).get(dic % s["period_days"])
                    if slot_m:
                        sched_duty_counts[slot_m] = sched_duty_counts.get(slot_m, 0) + 1
                _sched_wd[sid] = dic + 1  # always advance position
        scan_d += timedelta(days=1)

    result = []

    for day_num in range(1, count + 1):
        d = date(year, month, day_num)
        iso = d.isoformat()
        wd = WD[d.weekday()]

        if d.weekday() >= 5 or iso in holidays:
            continue

        sched = schedule_for(iso)
        if not sched:
            result.append({"date": iso, "wd": wd, "scheduled_id": None, "effective_id": None,
                           "is_replacement": False, "no_coverage": True, "pre_schedule": True})
            continue

        start_date = date.fromisoformat(sched["start_date"])
        wd_count = 0
        cur = start_date
        while cur < d:
            if cur.weekday() < 5:  # count all weekdays including holidays
                wd_count += 1
            cur += timedelta(days=1)
        day_in_cycle = wd_count % sched["period_days"]
        slot_member = all_slots.get(sched["id"], {}).get(day_in_cycle)

        if not slot_member:
            result.append({"date": iso, "wd": wd, "scheduled_id": None, "effective_id": None,
                           "is_replacement": False, "no_coverage": True})
            continue

        scheduled_id = slot_member
        stored = att_map.get((scheduled_id, iso))
        eff = effective_status(stored, False, iso in holidays)

        if iso in existing_rep and existing_rep[iso][2]:
            rep_id, _, _ = existing_rep[iso]
            result.append({"date": iso, "wd": wd, "scheduled_id": scheduled_id, "effective_id": rep_id,
                           "is_replacement": True, "is_manual": True, "no_coverage": False})
            continue

        if eff in WORKING:
            result.append({"date": iso, "wd": wd, "scheduled_id": scheduled_id, "effective_id": scheduled_id,
                           "is_replacement": False, "is_manual": False, "no_coverage": False})
            continue

        if iso in existing_rep:
            rep_id, _, _ = existing_rep[iso]
            result.append({"date": iso, "wd": wd, "scheduled_id": scheduled_id, "effective_id": rep_id,
                           "is_replacement": True, "is_manual": False, "no_coverage": False})
            continue

        candidates = []
        for mid in members_active_on(iso):
            if mid == scheduled_id:
                continue
            if duty_ineligible_ids and mid in duty_ineligible_ids:
                continue
            eff_m = effective_status(att_map.get((mid, iso)), False, iso in holidays)
            if eff_m in WORKING:
                candidates.append((rep_counts.get(mid, 0), mid))

        if not candidates:
            result.append({"date": iso, "wd": wd, "scheduled_id": scheduled_id, "effective_id": None,
                           "is_replacement": False, "is_manual": False, "no_coverage": True})
            continue

        candidates.sort(key=lambda x: (x[0], sched_duty_counts.get(x[1], 0), x[1]))
        replacer_id = candidates[0][1]

        if d <= today:
            conn.execute(
                "INSERT INTO duty_replacements(team_id,replacer_id,replaced_id,date,year,manual) "
                "VALUES (?,?,?,?,?,0) ON CONFLICT(team_id,date) DO NOTHING",
                (team_id, replacer_id, scheduled_id, iso, year),
            )
            conn.commit()
            existing_rep[iso] = (replacer_id, scheduled_id, False)
            rep_counts[replacer_id] = rep_counts.get(replacer_id, 0) + 1

        result.append({"date": iso, "wd": wd, "scheduled_id": scheduled_id, "effective_id": replacer_id,
                       "is_replacement": True, "is_manual": False, "no_coverage": False})

    return result


@bp_main.route("/allowances")
@admin_required
def allowances_page():
    year = request.args.get("year", default=date.today().year, type=int)
    conn = db()
    members = [dict(r) for r in conn.execute("SELECT * FROM members ORDER BY name").fetchall()]
    effective_allowances = {m["id"]: get_allowance(conn, m["id"], year) for m in members}
    used_days = {
        m["id"]: round(vacation_days_used(conn, m["id"], year), 1)
        for m in members
    }
    conn.close()
    return render_template(
        "allowances.html",
        year=year,
        members=members,
        effective_allowances=effective_allowances,
        used_days=used_days,
    )


@bp_main.route("/duty")
def duty_page():
    today = date.today()
    year = request.args.get("year", default=today.year, type=int)
    month = request.args.get("month", default=today.month, type=int)
    while month < 1:
        month += 12; year -= 1
    while month > 12:
        month -= 12; year += 1

    conn = db()
    teams = [dict(r) for r in conn.execute("SELECT * FROM teams ORDER BY name").fetchall()]
    members = [dict(r) for r in conn.execute("SELECT * FROM members ORDER BY name").fetchall()]
    member_names = {m["id"]: m["name"] for m in members}

    team_id = request.args.get("team", type=int)
    if not team_id and teams:
        sched = conn.execute("SELECT team_id FROM duty_schedules WHERE active=1 LIMIT 1").fetchone()
        team_id = sched["team_id"] if sched else teams[0]["id"]
    team = next((t for t in teams if t["id"] == team_id), teams[0] if teams else None)

    schedule = None
    slots = {}
    past_schedules = []
    upcoming_schedules = []
    if team_id:
        today_iso = date.today().isoformat()
        s = conn.execute(
            "SELECT * FROM duty_schedules WHERE team_id=? AND active=1 "
            "AND start_date <= ? AND (end_date IS NULL OR end_date >= ?) "
            "ORDER BY start_date DESC LIMIT 1",
            (team_id, today_iso, today_iso),
        ).fetchone()
        def _slot_start_wd(start_date_str):
            d = date.fromisoformat(start_date_str)
            while d.weekday() >= 5:
                d += timedelta(days=1)
            return d.weekday()

        if s:
            schedule = dict(s)
            schedule["start_wd"] = _slot_start_wd(schedule["start_date"])
            for sl in conn.execute("SELECT * FROM duty_slots WHERE schedule_id=? ORDER BY day_offset", (s["id"],)):
                slots[sl["day_offset"]] = dict(sl)
        for us in conn.execute(
            "SELECT * FROM duty_schedules WHERE team_id=? AND active=1 AND start_date > ? ORDER BY start_date",
            (team_id, today_iso),
        ).fetchall():
            us_dict = dict(us)
            us_dict["start_wd"] = _slot_start_wd(us_dict["start_date"])
            us_dict["slots"] = {
                sl["day_offset"]: dict(sl)
                for sl in conn.execute("SELECT * FROM duty_slots WHERE schedule_id=? ORDER BY day_offset", (us_dict["id"],))
            }
            upcoming_schedules.append(us_dict)
        past_schedules = [dict(r) for r in conn.execute(
            "SELECT * FROM duty_schedules WHERE team_id=? AND (active=0 OR (end_date IS NOT NULL AND end_date < ?)) "
            "ORDER BY start_date DESC",
            (team_id, today_iso),
        ).fetchall()]

    duty_ineligible_ids: set = set()
    current_duty_members: list = []
    if team_id:
        inelig_rows = conn.execute(
            _sql("SELECT member_id FROM duty_members WHERE team_id=?"), (team_id,)
        ).fetchall()
        duty_ineligible_ids = {r["member_id"] for r in inelig_rows}
        today_iso2 = today.isoformat()
        current_duty_members = [dict(r) for r in conn.execute(
            _sql("SELECT DISTINCT m.id, m.name FROM members m "
                 "JOIN member_teams mt ON mt.member_id=m.id "
                 "WHERE mt.team_id=? "
                 "AND (mt.end_date IS NULL OR mt.end_date>=?) "
                 "AND (mt.start_date IS NULL OR mt.start_date<=?) ORDER BY m.name"),
            (team_id, today_iso2, today_iso2),
        ).fetchall()]

    monthly_duty = get_monthly_duty(conn, team_id, year, month, duty_ineligible_ids) if team_id else []

    if schedule and team_id:
        sched_start = date.fromisoformat(schedule["start_date"])
        m_iter = date(sched_start.year, sched_start.month, 1)
        this_month_start = date(today.year, today.month, 1)
        while m_iter < this_month_start:
            if not (m_iter.year == year and m_iter.month == month):
                get_monthly_duty(conn, team_id, m_iter.year, m_iter.month, duty_ineligible_ids)
            m_iter = date(m_iter.year + (m_iter.month // 12),
                          (m_iter.month % 12) + 1, 1)

    team_members = []
    if team_id:
        _last = f"{year:04d}-{month:02d}-{monthrange(year, month)[1]:02d}"
        _first = f"{year:04d}-{month:02d}-01"
        team_members = [dict(r) for r in conn.execute(
            "SELECT DISTINCT m.id, m.name FROM members m "
            "JOIN member_teams mt ON mt.member_id=m.id "
            "WHERE mt.team_id=? "
            "AND (mt.end_date IS NULL OR mt.end_date>=?) "
            "AND (mt.start_date IS NULL OR mt.start_date<=?) ORDER BY m.name",
            (team_id, _first, _last),
        ).fetchall()]

    stats = []
    if team_id:
        cnt_map = {r["replacer_id"]: r["cnt"] for r in conn.execute(
            "SELECT replacer_id, COUNT(*) AS cnt FROM duty_replacements "
            "WHERE team_id=? AND year=? GROUP BY replacer_id",
            (team_id, year),
        ).fetchall()}
        for m in [dict(r) for r in conn.execute(
            "SELECT DISTINCT m.id, m.name FROM members m "
            "JOIN member_teams mt ON mt.member_id=m.id "
            "WHERE mt.team_id=? AND (mt.end_date IS NULL OR mt.end_date>=?) ORDER BY m.name",
            (team_id, today.isoformat()),
        ).fetchall()]:
            stats.append({"id": m["id"], "name": m["name"], "replacements": cnt_map.get(m["id"], 0)})

    conn.close()

    prev_m = (month - 1, year) if month > 1 else (12, year - 1)
    next_m = (month + 1, year) if month < 12 else (1, year + 1)
    is_admin = bool(session.get("is_admin"))

    _month_days = monthrange(year, month)[1]
    _month_start_wd = date(year, month, 1).weekday()
    _month_hols = cz_holidays(year)
    _duty_by_date = {e["date"]: e for e in monthly_duty}
    _all_days = [
        {
            "num": d,
            "iso": f"{year:04d}-{month:02d}-{d:02d}",
            "weekend": date(year, month, d).weekday() >= 5,
            "holiday": f"{year:04d}-{month:02d}-{d:02d}" in _month_hols,
        }
        for d in range(1, _month_days + 1)
    ]

    return render_template(
        "duty.html",
        teams=teams, team=team, team_id=team_id,
        year=year, month=month, month_name=MONTHS[month],
        schedule=schedule, slots=slots,
        upcoming_schedules=upcoming_schedules, past_schedules=past_schedules,
        monthly_duty=monthly_duty,
        member_names=member_names, team_members=team_members,
        stats=stats, today=today.isoformat(),
        prev={"y": prev_m[1], "m": prev_m[0]},
        next={"y": next_m[1], "m": next_m[0]},
        is_admin=is_admin,
        WD=WD,
        all_days=_all_days,
        month_start_wd=_month_start_wd,
        duty_by_date=_duty_by_date,
        duty_ineligible_ids=duty_ineligible_ids,
        current_duty_members=current_duty_members,
    )


@bp_main.route("/duty/schedule", methods=["POST"])
@admin_required
def duty_create_schedule():
    team_id = request.form.get("team_id", type=int)
    name = (request.form.get("name") or "Rotation").strip()
    start_date_raw = request.form.get("start_date", "").strip()
    end_date_raw = (request.form.get("end_date") or "").strip()
    period_days = request.form.get("period_days", type=int) or 5
    if not team_id:
        return redirect(request.referrer or url_for("main.duty_page"))
    start_date = start_date_raw if start_date_raw else date.today().isoformat()
    try:
        end_date = date.fromisoformat(end_date_raw).isoformat() if end_date_raw else None
    except ValueError:
        end_date = None
    is_active = 1 if (not end_date or end_date >= date.today().isoformat()) else 0
    conn = db()
    try:
        prev_end = (date.fromisoformat(start_date) - timedelta(days=1)).isoformat()
        conn.execute(
            "UPDATE duty_schedules SET end_date=? WHERE team_id=? AND active=1 AND end_date IS NULL",
            (prev_end, team_id),
        )
        conn.execute(
            "UPDATE duty_schedules SET active=0 WHERE team_id=? AND active=1 AND end_date >= ?",
            (team_id, start_date),
        )
        conn.execute(
            "INSERT INTO duty_schedules(team_id,name,start_date,end_date,period_days,active) VALUES (?,?,?,?,?,?)",
            (team_id, name, start_date, end_date, period_days, is_active),
        )
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for("main.duty_page", team=team_id))


@bp_main.route("/duty/slot", methods=["POST"])
@admin_required
def duty_set_slot():
    schedule_id = request.form.get("schedule_id", type=int)
    day_offset = request.form.get("day_offset", type=int)
    member_id = request.form.get("member_id", type=int)
    team_id = request.form.get("team_id", type=int)
    if schedule_id is None or day_offset is None:
        return redirect(request.referrer or url_for("main.duty_page"))
    conn = db()
    try:
        if member_id:
            conn.execute(
                "INSERT INTO duty_slots(schedule_id,day_offset,member_id) VALUES (?,?,?) "
                "ON CONFLICT(schedule_id,day_offset) DO UPDATE SET member_id=excluded.member_id",
                (schedule_id, day_offset, member_id),
            )
        else:
            conn.execute("DELETE FROM duty_slots WHERE schedule_id=? AND day_offset=?",
                         (schedule_id, day_offset))
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for("main.duty_page", team=team_id))


@bp_main.route("/duty/schedule/end-date", methods=["POST"])
@admin_required
def duty_update_end_date():
    schedule_id = request.form.get("schedule_id", type=int)
    team_id = request.form.get("team_id", type=int)
    end_date_raw = (request.form.get("end_date") or "").strip()
    try:
        end_date = date.fromisoformat(end_date_raw).isoformat() if end_date_raw else None
    except ValueError:
        end_date = None
    conn = db()
    try:
        sched = conn.execute(
            "SELECT team_id, start_date FROM duty_schedules WHERE id=?", (schedule_id,)
        ).fetchone()
        if sched:
            team_id = team_id or sched["team_id"]
            conn.execute("UPDATE duty_schedules SET end_date=? WHERE id=?", (end_date, schedule_id))
            if end_date:
                next_sched = conn.execute(
                    "SELECT start_date FROM duty_schedules WHERE team_id=? AND start_date > ? "
                    "ORDER BY start_date LIMIT 1",
                    (team_id, end_date),
                ).fetchone()
                if next_sched:
                    upper = (date.fromisoformat(next_sched["start_date"]) - timedelta(days=1)).isoformat()
                    conn.execute(
                        "DELETE FROM duty_replacements WHERE team_id=? AND date > ? AND date <= ? AND date >= ?",
                        (team_id, end_date, upper, sched["start_date"]),
                    )
                else:
                    conn.execute(
                        "DELETE FROM duty_replacements WHERE team_id=? AND date > ? AND date >= ?",
                        (team_id, end_date, sched["start_date"]),
                    )
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for("main.duty_page", team=team_id))


@bp_main.route("/duty/schedule/delete", methods=["POST"])
@admin_required
def duty_delete_schedule():
    schedule_id = request.form.get("schedule_id", type=int)
    conn = db()
    try:
        row = conn.execute(
            "SELECT team_id, start_date, end_date FROM duty_schedules WHERE id=?",
            (schedule_id,),
        ).fetchone()
        if row:
            team_id = row["team_id"]
            period_end = row["end_date"] or date.today().isoformat()
            conn.execute(
                "DELETE FROM duty_replacements WHERE team_id=? AND date >= ? AND date <= ?",
                (team_id, row["start_date"], period_end),
            )
            conn.execute("DELETE FROM duty_schedules WHERE id=?", (schedule_id,))
            remaining = _count(conn.execute(
                "SELECT COUNT(*) FROM duty_schedules WHERE team_id=?", (team_id,)
            ).fetchone())
            if remaining == 0:
                conn.execute(
                    "DELETE FROM duty_replacements WHERE team_id=?", (team_id,)
                )
            conn.commit()
        else:
            team_id = None
    finally:
        conn.close()
    return redirect(url_for("main.duty_page", team=team_id) if team_id else url_for("main.duty_page"))


@bp_main.route("/duty/replacement/set", methods=["POST"])
@admin_required
def duty_set_replacement():
    team_id = request.form.get("team_id", type=int)
    date_str = request.form.get("date")
    replacer_id = request.form.get("replacer_id", type=int)
    replaced_id = request.form.get("replaced_id", type=int)
    year = request.form.get("year", type=int)
    month = request.form.get("month", type=int)

    if not team_id or not date_str:
        return redirect(url_for("main.duty_page"))

    conn = db()
    try:
        conn.execute(
            "DELETE FROM duty_replacements WHERE team_id=? AND date=?",
            (team_id, date_str),
        )
        if replacer_id:
            year_val = int(date_str[:4])
            conn.execute(
                "INSERT INTO duty_replacements(team_id, replacer_id, replaced_id, date, year, manual) "
                "VALUES (?,?,?,?,?,1)",
                (team_id, replacer_id, replaced_id or replacer_id, date_str, year_val),
            )
        conn.commit()
    finally:
        conn.close()
    return redirect(url_for("main.duty_page", team=team_id, year=year, month=month))


@bp_main.route("/duty/member", methods=["POST"])
@admin_required
def duty_toggle_member():
    team_id = request.form.get("team_id", type=int)
    member_id = request.form.get("member_id", type=int)
    eligible = request.form.get("eligible", type=int, default=1)
    year = request.form.get("year", type=int)
    month = request.form.get("month", type=int)
    if team_id and member_id is not None:
        conn = db()
        if eligible:
            conn.execute(
                _sql("DELETE FROM duty_members WHERE team_id=? AND member_id=?"),
                (team_id, member_id),
            )
        else:
            conn.execute(
                _sql("INSERT INTO duty_members(team_id, member_id) VALUES (?,?) "
                     "ON CONFLICT(team_id, member_id) DO NOTHING"),
                (team_id, member_id),
            )
            conn.execute(
                _sql("DELETE FROM duty_replacements "
                     "WHERE team_id=? AND replacer_id=? AND date>? AND manual=0"),
                (team_id, member_id, date.today().isoformat()),
            )
        conn.commit()
        conn.close()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(ok=True)
    return redirect(url_for("main.duty_page", team=team_id, year=year, month=month))


init_db()
