# Team Attendance Planner (Flask)

Department coverage planner. At a glance: does every team have enough people
working each day? Each person sets their own daily status. Admin can manage
teams, people, and duty schedules. Includes Czech public holidays.

## Run locally (PyCharm / VS Code)

1. Create a virtual environment and install dependencies:

   **Windows (PowerShell)**
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

   **macOS / Linux**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Start the development server:
   ```
   python run.py
   ```

3. Open **http://127.0.0.1:5000**

On first run a local SQLite database is created at `main/data/attendance.db`.
Delete that file to start fresh.

## Project layout
```
attendance/
  run.py                   # Local development entry point
  requirements.txt
  postgresql_schema.sql    # PostgreSQL schema for CodeNow deployment
  main/
    routes.py              # Blueprint: routes, DB logic, CZ holidays, coverage & duty
    templates/
      index.html           # Calendar grid + Manage panel (Jinja2)
      duty.html            # Duty Schedule page
      allowances.html      # Vacation Allowances page
    static/
      app.js               # Status picker, bulk selection, manage panel AJAX
      styles/
        style.css
```

## Production deployment

The app runs as a Flask Blueprint (`bp_main`) that can be registered by any WSGI host
with a custom `url_prefix`.

**Database:** The app automatically switches to PostgreSQL when the `DOCHAZKA_1_HOST`
environment variable is set. Without it, the app uses local SQLite.

Required environment variables for PostgreSQL:
```
DOCHAZKA_1_HOST
DOCHAZKA_1_PORT
DOCHAZKA_1_USERNAME
DOCHAZKA_1_PASSWORD
DOCHAZKA_1_DATABASE_NAME
```

Before first deploy, run `postgresql_schema.sql` on the database to create all tables.

## Features

### Calendar
- Monthly grid — one column per day, one row per person
- **Status picker**: click a cell to set a status; drag across multiple cells for bulk edit
- Statuses: `WRK` (work), `VAC` (vacation), `HVA` (half-day vacation), `FLX` (flexi), `RST` (restart day), `PLE` (paid leave), `FIC` (fictional), `UPL` (unpaid leave), `LYR` (last year leave), `BDY` (birthday)
- **Coverage row** per team: green / amber / red based on headcount vs. minimum
- Weekends and CZ public holidays are non-interactive

### Allowance tracking
- Each person has a yearly vacation allowance (stored in hours, displayed in days)
- `VAC` = 1 day, `HVA` = 0.5 day; allowance deducted automatically
- Year-specific allowances set via Vacation Allowances page; falls back to member default (200 h)
- Remaining allowance shown in the toolbar

### Multi-team membership
- A person can belong to multiple teams simultaneously
- Memberships are date-ranged (`start_date` / `end_date`) — history is preserved
- The calendar shows only the teams a person was actually in on each day

### Admin panel
- Login with admin credentials (configured in `routes.py`)
- **Manage teams & people**: add/remove teams, add/remove people, assign to teams, set effective dates
- Admin can override any person's status for any day
- Vacation Allowances: set yearly allowance per person

### Duty Schedule (`/duty`)
- Per-team monthly duty calendar — shows who is on duty each working day
- Supports weekly (5 working days) and biweekly (10 working days) cycles
- **Auto-replacement**: if the scheduled person is absent, the system picks the
  fairest available replacement (fewest replacements → fewest scheduled duties → lowest ID)
- **Manual override**: admin can set any person for any day via dropdown
- Replacement stats table for the year
- Multiple schedules per team with history

## Coverage logic
- **Working** statuses: `WRK`
- All other statuses = not working; a weekday with no status defaults to working
- Coverage row: **green** = above minimum, **amber** = at minimum, **red (LOW)** = below minimum

## Czech public holidays
Computed dynamically in `cz_holidays(year)` using the Computus algorithm.
Works correctly for any future year automatically.

## New year checklist
- **Vacation allowances**: set year-specific allowances per member via Vacation Allowances page (optional — falls back to member default)
- **Duty schedule**: ensure active schedule has `end_date = NULL` or create a new schedule for the new year
