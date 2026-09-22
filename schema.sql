CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0),
    study_date TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_records_study_date
ON records (study_date DESC);

CREATE INDEX IF NOT EXISTS idx_records_subject
ON records (subject);

CREATE INDEX IF NOT EXISTS idx_records_completed
ON records (completed);

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    daily_goal_minutes INTEGER NOT NULL DEFAULT 60
        CHECK (daily_goal_minutes BETWEEN 1 AND 1440),
    weekly_goal_minutes INTEGER NOT NULL DEFAULT 300
        CHECK (weekly_goal_minutes BETWEEN 1 AND 10080),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO settings
    (id, daily_goal_minutes, weekly_goal_minutes)
VALUES
    (1, 60, 300);
