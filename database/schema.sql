PRAGMA foreign_keys = ON;

-- Project metadata is the root record for all phases and tasks.
CREATE TABLE IF NOT EXISTS project (
    project_id INTEGER PRIMARY KEY,
    project_name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    toolchain TEXT NOT NULL DEFAULT '',
    workspace_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS phases (
    phase_id INTEGER PRIMARY KEY,
    parent_project_id INTEGER NOT NULL,
    phase_name TEXT NOT NULL,
    phase_summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new'
        CHECK (status IN ('new', 'in_progress', 'complete', 'fail')),
    deliverables TEXT NOT NULL,
    architecture_contract TEXT NOT NULL,
    acceptance_checklist TEXT NOT NULL,
    fail_reason TEXT,
    completion_summary TEXT,
    phase_order INTEGER NOT NULL,
    FOREIGN KEY (parent_project_id) REFERENCES project(project_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    UNIQUE (parent_project_id, phase_order),
    UNIQUE (parent_project_id, phase_name)
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id INTEGER PRIMARY KEY,
    parent_phase_id INTEGER NOT NULL,
    task_name TEXT NOT NULL,
    task_status TEXT NOT NULL DEFAULT 'new'
        CHECK (task_status IN ('new', 'in_progress', 'complete', 'fail')),
    task_instructions TEXT NOT NULL,
    task_start_date TEXT,
    task_end_date TEXT,
    fail_reason TEXT,
    completion_summary TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    task_order INTEGER NOT NULL,
    test_results TEXT,
    FOREIGN KEY (parent_phase_id) REFERENCES phases(phase_id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    UNIQUE (parent_phase_id, task_order)
);

CREATE INDEX IF NOT EXISTS idx_phases_project_status_order
    ON phases(parent_project_id, status, phase_order);

CREATE INDEX IF NOT EXISTS idx_tasks_phase_status_order
    ON tasks(parent_phase_id, task_status, task_order);

CREATE INDEX IF NOT EXISTS idx_tasks_status_order
    ON tasks(task_status, task_order);

-- Singleton coordination record for the unattended worker.  A stop request is
-- deliberately durable so it remains visible across the gap between a task
-- completing and the next task being claimed.
CREATE TABLE IF NOT EXISTS worker_state (
    worker_id INTEGER PRIMARY KEY CHECK (worker_id = 1),
    stop_requested INTEGER NOT NULL DEFAULT 0 CHECK (stop_requested IN (0, 1)),
    active_task_id INTEGER,
    run_status TEXT NOT NULL DEFAULT 'idle'
        CHECK (run_status IN ('idle', 'running', 'interrupted')),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (active_task_id) REFERENCES tasks(task_id)
        ON UPDATE CASCADE ON DELETE SET NULL
);

INSERT OR IGNORE INTO worker_state (worker_id) VALUES (1);
