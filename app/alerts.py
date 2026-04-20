"""Alert checking and email sending."""

import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from app.database import get_db, get_config
import logging

logger = logging.getLogger(__name__)


def check_tool_timeout(tool):
    """Check if a tool is in timeout.
    
    Args:
        tool: Tool dict from database
        
    Returns:
        Tuple: (is_timeout: bool, reason: str)
    """
    now = datetime.utcnow()
    last_seen = datetime.fromisoformat(tool['last_seen'])
    timeout_hours = tool['timeout_hours']
    
    # Standard timeout
    if (now - last_seen) > timedelta(hours=timeout_hours):
        return True, f"No report for {timeout_hours}h"
    
    # Monthly timeout
    if tool['monthly_day']:
        monthly_grace = int(get_config('monthly_grace_days', '5'))
        
        if now.day >= tool['monthly_day']:
            expected = now.replace(day=tool['monthly_day'], hour=0, minute=0, second=0)
        else:
            prev_month = now.replace(day=1) - timedelta(days=1)
            target_day = min(tool['monthly_day'], 28)
            expected = prev_month.replace(day=target_day, hour=0, minute=0, second=0)
        
        if last_seen < expected and (now - expected) > timedelta(days=monthly_grace):
            return True, f"Monthly run expected on day {tool['monthly_day']}"
    
    return False, ""


def send_alert_email(tool, reason):
    """Send alert email for a tool timeout.
    
    Args:
        tool: Tool dict
        reason: Timeout reason
        
    Returns:
        bool: True if sent successfully
    """
    smtp_host = get_config('smtp_host')
    smtp_port = int(get_config('smtp_port', '25'))
    alert_emails = get_config('alert_emails', '').split(';')
    
    if not smtp_host or not alert_emails:
        logger.warning("SMTP not configured, skipping email alert")
        return False
    
    to_emails = [e.strip() for e in alert_emails if e.strip()]
    if not to_emails:
        return False
    
    try:
        msg = MIMEText(f"""
Watchdog Alert

Tool: {tool['server']} / {tool['dienst']}
Group: {tool['gruppe'] or 'N/A'}
Status: {tool['status']}
Reason: {reason}
Last Seen: {tool['last_seen']}

Please investigate immediately.
        """)
        
        msg['Subject'] = f"[Watchdog] ALERT: {tool['server']}/{tool['dienst']}"
        msg['From'] = "watchdog@localhost"
        msg['To'] = ', '.join(to_emails)
        
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.sendmail("watchdog@localhost", to_emails, msg.as_string())
        
        logger.info(f"Alert email sent for {tool['server']}/{tool['dienst']}")
        return True
    except Exception as e:
        logger.error(f"Failed to send alert email: {e}")
        return False


def check_all_timeouts():
    """Check all tools for timeouts and send alerts if needed.
    
    Called daily by scheduler.
    """
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("""
        SELECT id, server, dienst, gruppe, status, last_seen, 
               timeout_hours, monthly_day, alert_sent
        FROM tools
    """)
    
    alert_count = 0
    
    for row in cursor.fetchall():
        tool = dict(row)
        is_timeout, reason = check_tool_timeout(tool)
        
        if is_timeout and not tool['alert_sent']:
            # Send alert and mark
            if send_alert_email(tool, reason):
                cursor.execute(
                    "UPDATE tools SET alert_sent = 1 WHERE id = ?",
                    (tool['id'],)
                )
                alert_count += 1
        elif not is_timeout and tool['alert_sent']:
            # Tool recovered, reset alert flag
            cursor.execute(
                "UPDATE tools SET alert_sent = 0 WHERE id = ?",
                (tool['id'],)
            )
    
    db.commit()
    logger.info(f"Timeout check completed: {alert_count} alerts sent")


def cleanup_old_history():
    """Delete history entries older than 180 days.
    
    Called daily by scheduler.
    """
    db = get_db()
    cursor = db.cursor()
    
    cutoff = datetime.utcnow() - timedelta(days=180)
    cutoff_str = cutoff.isoformat()
    
    cursor.execute(
        "DELETE FROM history WHERE reported_at < ?",
        (cutoff_str,)
    )
    
    deleted = cursor.rowcount
    db.commit()
    
    logger.info(f"History cleanup: deleted {deleted} old entries")
