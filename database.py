import sqlite3
from datetime import datetime, timedelta
import os

DB_PATH = os.getenv("DB_PATH", "tasks.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            reg_code TEXT UNIQUE,
            line_user_id TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            assigned_to INTEGER NOT NULL,
            interval_hours REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            confirm_token TEXT UNIQUE NOT NULL,
            reminder_count INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME,
            next_remind_at DATETIME NOT NULL,
            FOREIGN KEY (assigned_to) REFERENCES staff(id)
        );
    """)
    conn.commit()
    conn.close()


def get_all_staff():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM staff ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_staff_by_id(staff_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM staff WHERE id = ?", (staff_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_staff(name, reg_code):
    conn = get_conn()
    conn.execute("INSERT INTO staff (name, reg_code) VALUES (?, ?)", (name, reg_code))
    conn.commit()
    conn.close()


def update_staff_line_id(staff_id, line_user_id):
    conn = get_conn()
    conn.execute("UPDATE staff SET line_user_id = ? WHERE id = ?", (line_user_id, staff_id))
    conn.commit()
    conn.close()


def get_all_tasks():
    conn = get_conn()
    rows = conn.execute("""
        SELECT t.*, s.name AS staff_name
        FROM tasks t
        LEFT JOIN staff s ON t.assigned_to = s.id
        ORDER BY t.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_task_by_token(token):
    conn = get_conn()
    row = conn.execute("""
        SELECT t.*, s.name AS staff_name
        FROM tasks t
        LEFT JOIN staff s ON t.assigned_to = s.id
        WHERE t.confirm_token = ?
    """, (token,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_task(title, description, assigned_to, interval_hours, token):
    conn = get_conn()
    next_remind = datetime.now() + timedelta(hours=interval_hours)
    cur = conn.execute("""
        INSERT INTO tasks (title, description, assigned_to, interval_hours, confirm_token, next_remind_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (title, description, assigned_to, interval_hours, token, next_remind.isoformat()))
    task_id = cur.lastrowid
    conn.commit()
    conn.close()
    return task_id


def mark_done(task_id):
    conn = get_conn()
    conn.execute(
        "UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ?",
        (datetime.now().isoformat(), task_id)
    )
    conn.commit()
    conn.close()


def get_due_tasks():
    conn = get_conn()
    now = datetime.now().isoformat()
    rows = conn.execute("""
        SELECT * FROM tasks
        WHERE status = 'pending' AND next_remind_at <= ?
    """, (now,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_next_remind(task_id, next_remind_dt):
    conn = get_conn()
    conn.execute(
        "UPDATE tasks SET next_remind_at = ? WHERE id = ?",
        (next_remind_dt.isoformat(), task_id)
    )
    conn.commit()
    conn.close()


def increment_reminder_count(task_id):
    conn = get_conn()
    conn.execute(
        "UPDATE tasks SET reminder_count = reminder_count + 1 WHERE id = ?",
        (task_id,)
    )
    conn.commit()
    conn.close()


def cancel_task(task_id):
    conn = get_conn()
    conn.execute(
        "UPDATE tasks SET status = 'cancelled' WHERE id = ?",
        (task_id,)
    )
    conn.commit()
    conn.close()
