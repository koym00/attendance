-- One-time migration: seed member_allowances for the current year
-- for members who have no entry in member_allowances at all.
-- Uses the fallback value from members.allowance.
-- Run once against the production PostgreSQL database.

INSERT INTO member_allowances (member_id, year, allowance)
SELECT id, EXTRACT(YEAR FROM NOW())::INTEGER, allowance
FROM members
WHERE id NOT IN (SELECT DISTINCT member_id FROM member_allowances);
