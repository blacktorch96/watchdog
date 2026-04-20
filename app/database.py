"""Database initialization and CRUD operations."""

import sqlite3
from datetime import datetime
from flask import g, current_app


def get_db():
    """Get database connection from app config path.

    Returns:
        SQLite3 connection object
    """
    db = getattr(g, '_database', None)
    if db is None:
        db_path = current_app.config.get('DATABASE', 'watchdog.db')
        db = g._database = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
    return db


def init_db(app):
    """Initialize database schema.

    Args:
        app: Flask application instance
    """
    db = sqlite3.connect(app.config.get('DATABASE', 'watchdog.db'))
    cursor = db.cursor()
    
    # Create tables if not exist
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS tools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server TEXT NOT NULL,
            dienst TEXT NOT NULL,
            gruppe TEXT,
            status TEXT DEFAULT 'unknown',
            kommentar TEXT,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            timeout_hours INTEGER DEFAULT 24,
            monthly_day INTEGER,
            alert_sent BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(server, dienst)
        );
        
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_id INTEGER NOT NULL,
            server TEXT NOT NULL,
            status TEXT NOT NULL,
            kommentar TEXT,
            pid TEXT,
            manually_resolved BOOLEAN DEFAULT 0,
            reported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(tool_id) REFERENCES tools(id) ON DELETE CASCADE
        );
        
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        
        CREATE INDEX IF NOT EXISTS idx_history_tool ON history(tool_id);
        CREATE INDEX IF NOT EXISTS idx_history_reported ON history(reported_at);
    """)
    
    db.commit()
    db.close()
    
    @app.teardown_appcontext
    def close_connection(exception):
        """Close database connection."""
        db = getattr(g, '_database', None)
        if db is not None:
            db.close()


def add_or_update_tool(server: str, dienst: str, group: str, status: str, 
                       kommentar: str, timeout_hours: int = 24) -> int:
    """Add or update a tool in the database.
    
    Args:
        server: Server name
        dienst: Service name
        group: Tool group path (e.g., 'Gruppe A/Tool B')
        status: Current status (start, stop, fehler, update)
        kommentar: Optional comment/message
        timeout_hours: Timeout in hours (default: 24)
        
    Returns:
        Tool ID
    """
    db = get_db()
    cursor = db.cursor()
    
    now = datetime.utcnow()
    
    cursor.execute(
        "SELECT id FROM tools WHERE server = ? AND dienst = ?",
        (server, dienst)
    )
    row = cursor.fetchone()
    
    if row:
        tool_id = row[0]
        cursor.execute("""
            UPDATE tools 
            SET status = ?, kommentar = ?, last_seen = ?, 
                alert_sent = 0, updated_at = ?
            WHERE id = ?
        """, (status, kommentar, now, now, tool_id))
    else:
        cursor.execute("""
            INSERT INTO tools 
            (server, dienst, gruppe, status, kommentar, timeout_hours, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (server, dienst, group, status, kommentar, timeout_hours, now))
        tool_id = cursor.lastrowid
    
    db.commit()
    return tool_id


def add_history(tool_id: int, server: str, status: str, kommentar: str = "", 
                pid: str = None) -> int:
    """Add history entry for a tool.
    
    Args:
        tool_id: Tool ID
        server: Server name
        status: Status value
        kommentar: Optional comment
        pid: Optional process ID
        
    Returns:
        History entry ID
    """
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("""
        INSERT INTO history (tool_id, server, status, kommentar, pid)
        VALUES (?, ?, ?, ?, ?)
    """, (tool_id, server, status, kommentar, pid))
    
    db.commit()
    return cursor.lastrowid


def get_config(key: str, default: str = "") -> str:
    """Get configuration value.
    
    Args:
        key: Config key
        default: Default value if key not found
        
    Returns:
        Config value
    """
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = cursor.fetchone()
    return row[0] if row else default


def set_config(key: str, value: str):
    """Set configuration value.
    
    Args:
        key: Config key
        value: Config value
    """
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
        (key, value)
    )
    db.commit()
