PRAGMA foreign_keys = ON;

-- Project metadata is the root record for all phases and tasks.
CREATE TABLE IF NOT EXISTS project (
    project_id INTEGER PRIMARY KEY,
    project_name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    root_path TEXT,
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
