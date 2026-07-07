# Team Attendance Planner (Flask)

Department coverage planner. At a glance: does every team have enough people
working each day? Each person sets their own daily status. Admin can manage
teams, people, and duty schedules. Includes Czech public holidays.

## Run

1. Open this folder in VS Code: **File → Open Folder…** → select `attendance`.
2. Open a terminal (**Terminal → New Terminal**) and run:

   **Windows (PowerShell)**
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python app.py
   ```

   **macOS / Linux**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python app.py
   ```

3. Open **http://127.0.0.1:8080**

On first run a local SQLite database `attendance.db` is created and seeded with
demo data. Delete that file to start fresh.

## Project layout
```
attendance/
  app.py                 # Flask routes, SQLite, CZ holidays, coverage & duty logic
  templates/
    index.html           # Calendar grid + Manage panel (Jinja2)
    duty.html            # Duty Schedule page
  static/
    style.css
    app.js               # Status picker, bulk selection, manage panel AJAX
  requirements.txt
```

## Features

### Calendar
- Monthly grid — one column per day, one row per person
- **Status picker**: click a cell to set a status; drag across multiple cells for bulk edit
- Statuses: `WRK` (work), `VAC` (vacation), `HVA` (half-day vacation), `FLX` (flexi), `RST` (rest day), `PLE` (paid leave), `FIC` (sick), `UPL` (unpaid leave), `LYR` (last year leave), `BDY` (birthday)
- **Coverage row** per team: green / amber (LOW) / red based on headcount vs. minimum
- Weekends and CZ public holidays are non-interactive

### Allowance tracking
- Each person has a yearly vacation allowance (stored in hours, displayed in days)
- `VAC` = 1 day, `HVA` = 0.5 day; allowance deducted automatically
- Remaining allowance shown in the toolbar; goes red when low

### Multi-team membership
- A person can belong to multiple teams simultaneously
- Memberships are date-ranged (`start_date` / `end_date`) — history is preserved
- The calendar shows only the teams a person was actually in on each day

### Admin panel
- Login with admin credentials (set in `app.py`)
- **Manage teams & people**: add/remove teams, add/remove people, assign to teams, set effective dates
- Override any person's status for any day

### Duty Schedule (`/duty`)
- Per-team monthly duty calendar — shows who is on duty each working day
- Supports **weekly** (5 working days) and **biweekly** (10 working days) cycles
- **Auto-replacement**: if the scheduled person is absent, the system picks the
  fairest available replacement (fewest replacements → fewest scheduled duties → lowest ID)
- **Manual override**: admin can set any person for any day via dropdown
- Replacement stats table for the year
- Multiple schedules per team with history

## Coverage logic
- **Working** statuses: `WRK`, `FLX`
- All other statuses (VAC, HVA, RST, PLE, FIC, UPL, LYR, BDY) = not working
- A weekday with no status set defaults to working
- Coverage row: **green** = above minimum, **LOW** = below minimum

## Czech public holidays
Computed in `cz_holidays(year)` in `app.py`. Movable dates (Velký pátek,
Velikonoční pondělí) use the Computus algorithm — works for any year.
