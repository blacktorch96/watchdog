"""Watchdog client — standalone stdlib-only module.

Copy this file into any project to report status to a Watchdog service.

Usage:
    from watchdog_client import WatchdogClient

    client = WatchdogClient("http://watchdog.example.com", server="web01")
    client.start("backup")
    client.stop("backup", kommentar="12 GB in 4m")

    dt = client.last_success("backup")  # datetime | None

    with client.run("cleanup"):
        do_cleanup()  # auto start/stop; reports fehler on exception
"""

import contextlib
import datetime
import json
import urllib.error
import urllib.parse
import urllib.request


class WatchdogClient:
    """HTTP client for the Watchdog status service."""

    def __init__(self, base_url: str, server: str, timeout: int = 10) -> None:
        """Initialise client.

        Args:
            base_url: Base URL of the Watchdog service (e.g. 'http://host:5050').
            server:   Server name reported with every status call.
            timeout:  HTTP request timeout in seconds.
        """
        self._base_url = base_url.rstrip("/")
        self._server = server
        self._timeout = timeout

    def report(
        self,
        dienst: str,
        status: str,
        gruppe: str | None = None,
        kommentar: str | None = None,
        pid: str | None = None,
    ) -> bool:
        """POST a status report to the Watchdog service.

        Args:
            dienst:   Service / tool name.
            status:   One of: start, stop, fehler, update.
            gruppe:   Optional group path (e.g. 'Backup/DB').
            kommentar: Optional free-text comment.
            pid:      Optional process ID string.

        Returns:
            True on HTTP 200, False on any error (network or non-200 response).
        """
        payload: dict[str, str] = {
            "server": self._server,
            "dienst": dienst,
            "status": status,
        }
        if gruppe is not None:
            payload["gruppe"] = gruppe
        if kommentar is not None:
            payload["kommentar"] = kommentar
        if pid is not None:
            payload["pid"] = pid

        data = urllib.parse.urlencode(payload).encode()
        req = urllib.request.Request(
            f"{self._base_url}/watchdog",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def start(self, dienst: str, **kwargs) -> bool:
        """Report status='start' for dienst."""
        return self.report(dienst, "start", **kwargs)

    def stop(self, dienst: str, **kwargs) -> bool:
        """Report status='stop' for dienst."""
        return self.report(dienst, "stop", **kwargs)

    def error(self, dienst: str, **kwargs) -> bool:
        """Report status='fehler' for dienst."""
        return self.report(dienst, "fehler", **kwargs)

    def update(self, dienst: str, **kwargs) -> bool:
        """Report status='update' for dienst."""
        return self.report(dienst, "update", **kwargs)

    def last_success(self, dienst: str) -> datetime.datetime | None:
        """Return when dienst last completed successfully on this server.

        Queries GET /api/tools/last-success?server=...&dienst=...

        Returns:
            Parsed datetime of the last stop-status report, or None if
            no successful run is recorded or on any network/parse error.
        """
        params = urllib.parse.urlencode({"server": self._server, "dienst": dienst})
        url = f"{self._base_url}/api/tools/last-success?{params}"
        try:
            with urllib.request.urlopen(url, timeout=self._timeout) as resp:
                if resp.status != 200:
                    return None
                body = json.loads(resp.read().decode())
                return datetime.datetime.fromisoformat(body["reported_at"])
        except Exception:
            return None

    @contextlib.contextmanager
    def run(
        self,
        dienst: str,
        gruppe: str | None = None,
        kommentar: str | None = None,
        pid: str | None = None,
    ):
        """Context manager: report start on enter, stop on success, fehler on exception.

        The original exception is always re-raised so callers still see it.

        Usage:
            with client.run("backup"):
                do_backup()
        """
        self.start(dienst, gruppe=gruppe, kommentar=kommentar, pid=pid)
        try:
            yield self
        except Exception as exc:
            self.error(dienst, kommentar=str(exc), pid=pid)
            raise
        else:
            self.stop(dienst, gruppe=gruppe, pid=pid)
