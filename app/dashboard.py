"""Dashboard blueprint."""

import os
import tomllib
from flask import Blueprint, render_template, jsonify, request
from app.database import get_db, get_last_success
from datetime import datetime, timedelta


dashboard_bp = Blueprint('dashboard', __name__, url_prefix='')


def _read_version() -> str:
    """Read project version from pyproject.toml."""
    try:
        toml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'pyproject.toml')
        with open(toml_path, 'rb') as f:
            return tomllib.load(f)['project']['version']
    except Exception:
        return 'dev'


APP_VERSION = _read_version()


def build_group_tree(tools):
    """Build hierarchical group structure from flat tool list.
    
    Args:
        tools: List of tool dicts
        
    Returns:
        Nested dict: {groupA: {groupB: [tools]}}
    """
    tree = {}
    for tool in tools:
        group_path = tool['gruppe'].split('/') if tool['gruppe'] else ['Ungrouped']
        current = tree
        
        for group_part in group_path[:-1]:
            if group_part not in current:
                current[group_part] = {}
            current = current[group_part]
        
        leaf = group_path[-1] if group_path else 'Ungrouped'
        if leaf not in current:
            current[leaf] = []
        current[leaf].append(tool)
    
    return tree


def check_timeout(tool):
    """Check if tool is in timeout.
    
    Args:
        tool: Tool dict from database
        
    Returns:
        Tuple: (is_timeouted, reason_str)
    """
    now = datetime.utcnow()
    last_seen = datetime.fromisoformat(tool['last_seen'])
    timeout_hours = tool['timeout_hours']
    
    # Standard timeout check
    if (now - last_seen) > timedelta(hours=timeout_hours):
        return True, f"No report for {timeout_hours}h"
    
    # Monthly timeout check
    if tool['monthly_day']:
        # Calculate last expected run date
        if now.day >= tool['monthly_day']:
            expected_day = now.replace(day=tool['monthly_day'])
        else:
            # Last month's run date
            prev_month = now.replace(day=1) - timedelta(days=1)
            expected_day = prev_month.replace(day=min(tool['monthly_day'], 28))
        
        grace_days = 5  # Default grace period (can be config later)
        if last_seen < expected_day and \
           (now - expected_day) > timedelta(days=grace_days):
            return True, f"Monthly run (expected {tool['monthly_day']}.)"
    
    return False, ""


@dashboard_bp.route('/')
def index():
    """Main dashboard view."""
    return render_template('dashboard.html', version=APP_VERSION)


@dashboard_bp.route('/api/status')
def get_status():
    """Return current tool status as JSON for polling.
    
    Returns:
        JSON with tool tree, grouped by gruppe
    """
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("""
        SELECT id, server, dienst, gruppe, status, kommentar, 
               last_seen, timeout_hours, monthly_day, alert_sent
        FROM tools
        ORDER BY gruppe, server, dienst
    """)
    
    tools = []
    for row in cursor.fetchall():
        tool = {
            'id': row[0],
            'server': row[1],
            'dienst': row[2],
            'gruppe': row[3] or '',
            'status': row[4],
            'kommentar': row[5],
            'last_seen': row[6],
            'timeout_hours': row[7],
            'monthly_day': row[8],
            'alert_sent': row[9],
        }
        
        # Add timeout check
        is_timeout, reason = check_timeout(tool)
        tool['is_timeout'] = is_timeout
        tool['timeout_reason'] = reason
        
        # Color coding
        if is_timeout:
            tool['color'] = 'red'
        elif tool['status'] == 'fehler':
            tool['color'] = 'orange'
        elif tool['status'] == 'stop':
            tool['color'] = 'gray'
        elif tool['status'] == 'start':
            tool['color'] = 'green'
        else:
            tool['color'] = 'gray'
        
        tools.append(tool)
    
    # Build group tree
    tree = build_group_tree(tools)
    
    return jsonify({
        'tools': tools,
        'tree': tree_to_json(tree),
        'timestamp': datetime.utcnow().isoformat()
    })


@dashboard_bp.route('/api/tools/<int:tool_id>/history')
def tool_history_api(tool_id):
    """Return the last 60 history entries for a tool, oldest first.

    Returns:
        JSON with history list
    """
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT status, kommentar, pid, reported_at
        FROM (
            SELECT status, kommentar, pid, reported_at
            FROM history WHERE tool_id = ?
            ORDER BY reported_at DESC LIMIT 60
        ) ORDER BY reported_at ASC
    """, (tool_id,))
    history = [dict(row) for row in cursor.fetchall()]
    return jsonify({'history': history})


@dashboard_bp.route('/api/tools/last-success')
def last_success_api():
    """Return the most recent successful run for a (server, dienst) pair.

    Query params:
        server: Server name (required)
        dienst: Service name (required)

    Returns:
        200 {'reported_at': str, 'kommentar': str|null}
        400 {'error': 'Missing required parameters'}
        404 {'error': 'No successful run recorded'}
    """
    server = request.args.get('server', '').strip()
    dienst = request.args.get('dienst', '').strip()
    if not server or not dienst:
        return jsonify({"error": "Missing required parameters"}), 400
    result = get_last_success(server, dienst)
    if result is None:
        return jsonify({"error": "No successful run recorded"}), 404
    return jsonify(result), 200


@dashboard_bp.route('/api/tools/<int:tool_id>/timeline')
def tool_timeline_api(tool_id: int):
    """Return a 24h bucketed timeline for a tool.

    Query params:
        slot_minutes: Slot width in minutes (default 10).
        hours:        Window in hours (default 24).

    Returns:
        JSON with slots array; each slot has 'start' (ISO) and
        'status' (ok | error | warn | null).
    """
    slot_minutes = max(1, int(request.args.get('slot_minutes', 10)))
    hours = max(1, int(request.args.get('hours', 24)))
    num_slots = (hours * 60) // slot_minutes

    now = datetime.utcnow()
    since = now - timedelta(hours=hours)

    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        """SELECT status, reported_at FROM history
           WHERE tool_id = ? AND reported_at >= ?
           ORDER BY reported_at ASC""",
        (tool_id, since.strftime('%Y-%m-%d %H:%M:%S')),
    )
    entries = cursor.fetchall()

    priority = {'error': 3, 'ok': 2, 'warn': 1}
    slots = [
        {'start': (since + timedelta(minutes=i * slot_minutes)).isoformat(), 'status': None}
        for i in range(num_slots)
    ]
    for entry in entries:
        dt = datetime.fromisoformat(entry['reported_at'])
        idx = int((dt - since).total_seconds() // (slot_minutes * 60))
        if 0 <= idx < num_slots:
            mapped = ('error' if entry['status'] == 'fehler' else
                      'ok' if entry['status'] in ('stop', 'start') else 'warn')
            current = slots[idx]['status']
            if current is None or priority[mapped] > priority.get(current, 0):
                slots[idx]['status'] = mapped

    return jsonify({'slots': slots, 'slot_minutes': slot_minutes, 'hours': hours})


def tree_to_json(node, level=0):
    """Convert tree structure to JSON-friendly format.
    
    Args:
        node: Dict or list in tree
        level: Current nesting level
        
    Returns:
        List of dicts for JSON
    """
    result = []
    
    if isinstance(node, dict):
        for key, value in sorted(node.items()):
            if isinstance(value, list):
                # This is a tool list
                result.append({
                    'type': 'group',
                    'name': key,
                    'tools': value,
                    'level': level
                })
            else:
                # Recurse into subgroup
                result.append({
                    'type': 'subgroup',
                    'name': key,
                    'items': tree_to_json(value, level + 1)
                })
    elif isinstance(node, list):
        for tool in node:
            result.append({
                'type': 'tool',
                'data': tool
            })
    
    return result
