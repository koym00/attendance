-- Migration: remove allowance column from members table.
-- Run AFTER postgresql_seed_member_allowances.sql.

ALTER TABLE members DROP COLUMN IF EXISTS allowance;
