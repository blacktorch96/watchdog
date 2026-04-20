"""Admin blueprint for tool and config management."""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from app.database import get_db, get_config, set_config


admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/tools')
def tools_list():
    """List all tools."""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT id, server, dienst, gruppe, status, last_seen,
               timeout_hours, monthly_day
        FROM tools
        ORDER BY gruppe, server, dienst
    """)
    tools = [dict(row) for row in cursor.fetchall()]
    return render_template('admin.html', tools=tools)


@admin_bp.route('/tools/new', methods=['GET', 'POST'])
def create_tool():
    """Create a new tool manually."""
    if request.method == 'POST':
        data = request.form
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO tools (server, dienst, gruppe, timeout_hours, monthly_day, status)
            VALUES (?, ?, ?, ?, ?, 'unknown')
        """, (
            data.get('server', '').strip(),
            data.get('dienst', '').strip(),
            data.get('gruppe', '').strip() or None,
            int(data.get('timeout_hours', 24)),
            int(data.get('monthly_day')) if data.get('monthly_day') else None,
        ))
        db.commit()
        return redirect(url_for('admin.tools_list'))

    empty = {'id': None, 'server': '', 'dienst': '', 'gruppe': '',
             'timeout_hours': 24, 'monthly_day': None}
    return render_template('admin_tool.html', tool=empty)


@admin_bp.route('/tools/<int:tool_id>')
def edit_tool(tool_id):
    """Edit a specific tool."""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT id, server, dienst, gruppe, timeout_hours, monthly_day
        FROM tools WHERE id = ?
    """, (tool_id,))
    tool = dict(cursor.fetchone() or {})

    if not tool:
        return "Tool not found", 404

    return render_template('admin_tool.html', tool=tool)


@admin_bp.route('/tools/api/update/<int:tool_id>', methods=['POST'])
def update_tool(tool_id):
    """Update tool configuration."""
    data = request.get_json()
    db = get_db()
    cursor = db.cursor()

    cursor.execute("""
        UPDATE tools
        SET gruppe = ?, timeout_hours = ?, monthly_day = ?
        WHERE id = ?
    """, (data.get('gruppe'), data.get('timeout_hours'),
          data.get('monthly_day'), tool_id))

    db.commit()
    return jsonify({"ok": True})


@admin_bp.route('/tools/api/delete/<int:tool_id>', methods=['POST'])
def delete_tool(tool_id):
    """Delete a tool and its history (cascade)."""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM tools WHERE id = ?", (tool_id,))
    db.commit()
    return jsonify({"ok": True})


@admin_bp.route('/tools/<int:tool_id>/history')
def tool_history(tool_id):
    """View history for a specific tool."""
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT server, dienst FROM tools WHERE id = ?", (tool_id,))
    tool = cursor.fetchone()

    if not tool:
        return "Tool not found", 404

    cursor.execute("""
        SELECT id, status, kommentar, pid, reported_at, manually_resolved
        FROM history
        WHERE tool_id = ?
        ORDER BY reported_at DESC
        LIMIT 100
    """, (tool_id,))

    history = [dict(row) for row in cursor.fetchall()]
    return render_template('admin_history.html',
                           tool={"id": tool_id, "name": f"{tool[0]}/{tool[1]}"},
                           history=history)


@admin_bp.route('/tools/<int:tool_id>/history/<int:hist_id>/resolve', methods=['POST'])
def resolve_history(tool_id, hist_id):
    """Mark history entry as manually resolved."""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        UPDATE history SET manually_resolved = 1
        WHERE id = ? AND tool_id = ?
    """, (hist_id, tool_id))
    db.commit()
    return jsonify({"ok": True})


@admin_bp.route('/config', methods=['GET', 'POST'])
def configure():
    """View/edit global configuration."""
    if request.method == 'POST':
        set_config('smtp_host', request.form.get('smtp_host'))
        set_config('smtp_port', request.form.get('smtp_port'))
        set_config('alert_emails', request.form.get('alert_emails'))
        set_config('check_interval_minutes', request.form.get('check_interval_minutes', '1440'))
        set_config('monthly_grace_days', request.form.get('monthly_grace_days', '5'))
        return redirect(url_for('admin.configure'))

    config = {
        'smtp_host': get_config('smtp_host'),
        'smtp_port': get_config('smtp_port', '25'),
        'alert_emails': get_config('alert_emails'),
        'check_interval_minutes': get_config('check_interval_minutes', '1440'),
        'monthly_grace_days': get_config('monthly_grace_days', '5'),
    }
    return render_template('admin_config.html', config=config)


@admin_bp.route('/config/test-email', methods=['POST'])
def test_email():
    """Send test email to configured recipients."""
    import smtplib
    from email.mime.text import MIMEText

    smtp_host = get_config('smtp_host')
    smtp_port = int(get_config('smtp_port', '25'))
    alert_emails = [e.strip() for e in get_config('alert_emails', '').split(';') if e.strip()]

    if not smtp_host or not alert_emails:
        return jsonify({"error": "SMTP not configured"}), 400

    try:
        msg = MIMEText("Watchdog test email")
        msg['Subject'] = "Watchdog - Test Email"
        msg['From'] = "watchdog@localhost"
        msg['To'] = alert_emails[0]

        with smtplib.SMTP(smtp_host, smtp_port, timeout=5) as server:
            server.sendmail("watchdog@localhost", alert_emails, msg.as_string())

        return jsonify({"ok": True, "message": "Test email sent"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
