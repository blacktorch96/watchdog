"""API blueprint for tool status reporting."""

from flask import Blueprint, request, jsonify
from app.database import add_or_update_tool, add_history


api_bp = Blueprint('api', __name__)


@api_bp.route('/watchdog', methods=['GET', 'POST'])
def report_status():
    """Report tool status via GET or POST.
    
    Parameters (GET query or POST form/JSON):
        server: Server name (required)
        dienst: Service name (required)
        gruppe: Tool group path (optional)
        status: Status value: start, stop, fehler, update (required)
        kommentar: Optional comment/message
        pid: Optional process ID
        
    Returns:
        JSON response with ok: true
    """
    # Get parameters from query or form data
    data = request.args if request.method == 'GET' else request.get_json(silent=True) or request.form
    
    server = data.get('server', '')
    dienst = data.get('dienst', '')
    gruppe = data.get('gruppe', '')
    status = data.get('status', '')
    kommentar = data.get('kommentar', '')
    pid = data.get('pid', '')
    
    # Validate required fields
    if not all([server, dienst, status]):
        return jsonify({"error": "Missing required fields"}), 400
    
    if status not in ['start', 'stop', 'fehler', 'update']:
        return jsonify({"error": "Invalid status"}), 400
    
    # Add or update tool
    tool_id = add_or_update_tool(server, dienst, gruppe, status, kommentar)
    
    # Add history entry
    add_history(tool_id, server, status, kommentar, pid)
    
    return jsonify({"ok": True}), 200
