# Team Attendance Planner (Flask)

Department coverage planner. At a glance: does every team have enough people
working each day? Each person sets their own daily status. Includes Czech
public holidays (fixed + movable Easter dates, computed for any year).

## Run it in VS Code

1. Open this folder in VS Code:  **File → Open Folder…**  → select `attendance`.
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

3. Open http://127.0.0.1:8080

On first run a local SQLite database `attendance.db` is created and seeded with
demo teams/people so the coverage colours are visible. Delete that file to start
empty.

## Project layout
```
attendance/
  app.py              # Flask routes, SQLite store, CZ holidays, coverage logic
  templates/
    index.html        # the grid (Jinja)
  static/
    style.css
    app.js            # click-a-cell status picker + live coverage repaint
  requirements.txt
```

## How coverage works
- "Working" = In office, Home office, Business trip.
- Vacation / Sick / Flexi / Free do **not** count as working.
- A normal weekday with nothing set defaults to **In office**.
- Weekends and CZ public holidays carry no minimum requirement.
- The coverage row turns **red (LOW)** when a team has fewer working people
  than its minimum, amber when exactly on the minimum, green when above.

## Czech public holidays
Computed in `cz_holidays(year)` in `app.py`. Movable dates (Velký pátek,
Velikonoční pondělí) use the Computus algorithm, so any year works.

## Swapping SQLite for PostgreSQL
You had pgAdmin/Postgres open. To move off SQLite, replace the `db()` helper and
the few `sqlite3` calls with `psycopg`/SQLAlchemy. The SQL is standard; the only
SQLite-specific bit is the `ON CONFLICT(member_id, day) DO UPDATE` upsert, which
Postgres also supports with the same syntax.
