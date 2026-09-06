-- SQL Migration: Add status and error_message to evaluations table
-- Run this on the production database if Python script cannot be used

-- Add status column with default COMPLETED for existing rows
ALTER TABLE evaluations
ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'COMPLETED';

-- Add error_message column (nullable, no default needed)
ALTER TABLE evaluations
ADD COLUMN IF NOT EXISTS error_message TEXT;

-- Backfill: mark evaluations with recommendation=EVALUATION_FAILED as FAILED
UPDATE evaluations
SET status = 'FAILED'
WHERE recommendation = 'EVALUATION_FAILED';

-- Backfill: detect historical failed evaluations created before the fix
-- These have summary='Evaluacion fallida.' but recommendation='LOW_MATCH'
UPDATE evaluations
SET status = 'FAILED',
    recommendation = 'EVALUATION_FAILED'
WHERE summary = 'Evaluacion fallida.'
AND recommendation = 'LOW_MATCH'
AND status = 'COMPLETED';

-- Verify: show counts by recommendation and status
SELECT
    recommendation,
    status,
    COUNT(*)
FROM evaluations
GROUP BY recommendation, status
ORDER BY recommendation, status;
