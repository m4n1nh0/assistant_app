-- App execution history used by the launcher/user listing.
-- MySQL 8.x

CREATE TABLE IF NOT EXISTS shortcut_launch_logs (
  id VARCHAR(64) PRIMARY KEY,
  tutor_id VARCHAR(64) NOT NULL,
  shortcut_id VARCHAR(64) NULL,
  shortcut_name VARCHAR(180) NOT NULL,
  target_type VARCHAR(16) NOT NULL,
  target VARCHAR(1024) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'executed',
  source VARCHAR(80) NOT NULL DEFAULT 'interface',
  platform VARCHAR(80) NULL,
  request JSON NULL,
  result JSON NULL,
  error TEXT NULL,
  launched_at DATETIME NOT NULL,
  INDEX ix_shortcut_launch_logs_tutor_id (tutor_id),
  INDEX ix_shortcut_launch_logs_shortcut_id (shortcut_id),
  INDEX ix_shortcut_launch_logs_status (status),
  INDEX ix_shortcut_launch_logs_launched_at (launched_at)
);

-- Detailed history for a user's app executions on one day.
-- Replace :tutor_id, :day_start and :day_end in the API/report layer.
SELECT
  l.tutor_id,
  l.shortcut_name AS application_name,
  l.target_type,
  l.target,
  l.status,
  l.platform,
  l.source,
  l.request,
  l.result,
  l.error,
  l.launched_at,
  s.aliases,
  s.description,
  s.use_count,
  s.last_used_at
FROM shortcut_launch_logs l
LEFT JOIN shortcuts s ON s.id = l.shortcut_id
WHERE l.tutor_id = :tutor_id
  AND l.launched_at >= :day_start
  AND l.launched_at < :day_end
ORDER BY l.launched_at DESC;

-- Daily rollup by user and application.
SELECT
  l.tutor_id,
  DATE(l.launched_at) AS launch_day,
  l.shortcut_name AS application_name,
  l.target,
  COUNT(*) AS total_attempts,
  SUM(CASE WHEN l.status = 'executed' THEN 1 ELSE 0 END) AS successful_runs,
  SUM(CASE WHEN l.status = 'failed' THEN 1 ELSE 0 END) AS failed_runs,
  MAX(l.launched_at) AS last_run_at
FROM shortcut_launch_logs l
GROUP BY
  l.tutor_id,
  DATE(l.launched_at),
  l.shortcut_name,
  l.target
ORDER BY last_run_at DESC;
