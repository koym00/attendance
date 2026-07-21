-- One-time migration: sync members.allowance to match the current year's
-- effective value from member_allowances.
-- Run once against the production PostgreSQL database.

-- Step 1: Update members.allowance for members who already have a 2026 entry
UPDATE members
SET allowance = (
    SELECT allowance FROM member_allowances
    WHERE member_id = members.id AND year = 2026
)
WHERE EXISTS (
    SELECT 1 FROM member_allowances
    WHERE member_id = members.id AND year = 2026
);

-- Step 2: Seed member_allowances for members who have no entry at all
INSERT INTO member_allowances (member_id, year, allowance)
SELECT id, 2026, allowance
FROM members
WHERE id NOT IN (SELECT DISTINCT member_id FROM member_allowances);
