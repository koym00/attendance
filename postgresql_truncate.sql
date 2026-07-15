-- Deletes all data from all tables and resets sequences (IDs start from 1 again).
-- Run this in pgAdmin when you want a clean slate.
TRUNCATE TABLE
    duty_replacements,
    duty_slots,
    duty_schedules,
    attendance,
    member_allowances,
    member_teams,
    members,
    teams
RESTART IDENTITY CASCADE;
