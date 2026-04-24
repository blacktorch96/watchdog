"""Watchdog client — standalone stdlib-only module.

Copy this file into any project to report status to a Watchdog service.

Usage:
    from watchdog_client import WatchdogClient, DependencyError

    # Explicit:
    client = WatchdogClient("http://watchdog.example.com", server="web01")

    # Via environment variables (WATCHDOG_URL + WATCHDOG_SERVER in .env):
    client = WatchdogClient()

    client.start("backup")
    client.stop("backup", kommentar="12 GB in 4m")

    dt = client.last_success("backup")          # datetime | None
    client.require_success("backup", within_minutes=60)  # raises DependencyError if stale

    with client.run("cleanup"):
        do_cleanup()  # auto start/stop; reports fehler on exception

    # Version check — compare this copy against the server's canonical version:
    info = client.check_version()
    # → {'local': '1.1.0', 'remote': '1.1.0', 'up_to_date': True}
"""

__version__ = "1.2.0"

import contextlib
import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request


def _parse_version(v: str) -> tuple:
    """Parse a semver string into a comparable int tuple."""
    try:
        return tuple(int(x) for x in v.split('.'))
    except Exception:
        return (0,)


class DependencyError(RuntimeError):
    """Raised when a required dependency service has not run within the expected window."""


class WatchdogClient:
    """HTTP client for the Watchdog status service."""

    def __init__(
        self,
        base_url: str | None = None,
        server: str | None = None,
        timeout: int = 10,
    ) -> None:
        """Initialise client.

        Both base_url and server can be omitted when the environment variables
        WATCHDOG_URL and WATCHDOG_SERVER are set (e.g. via a .env file).

        Args:
            base_url: Base URL of the Watchdog service (e.g. 'http://host:5050').
                      Falls back to the WATCHDOG_URL environment variable.
            server:   Server name reported with every status call.
                      Falls back to the WATCHDOG_SERVER environment variable.
            timeout:  HTTP request timeout in seconds.

        Raises:
            ValueError: If base_url or server cannot be resolved from params or env.
        """
        resolved_url = base_url or os.environ.get("WATCHDOG_URL", "")
        resolved_server = server or os.environ.get("WATCHDOG_SERVER", "")
        if not resolved_url:
            raise ValueError(
                "base_url is required. Pass it explicitly or set the WATCHDOG_URL environment variable."
            )
        if not resolved_server:
            raise ValueError(
                "server is required. Pass it explicitly or set the WATCHDOG_SERVER environment variable."
            )
        self._base_url = resolved_url.rstrip("/")
        self._server = resolved_server
        self._timeout = timeout
        self._last_error: str | None = None

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
            dienst:    Service / tool name.
            status:    One of: start, stop, fehler, update.
            gruppe:    Optional group path (e.g. 'Backup/DB').
            kommentar: Optional free-text comment.
            pid:       Optional process ID string.

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
                self._last_error = None
                return resp.status == 200
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            self._last_error = f"HTTP {exc.code} {exc.reason}: {body}"
            return False
        except Exception as exc:
            self._last_error = repr(exc)
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

    def last_success(
        self, dienst: str, server: str | None = None
    ) -> datetime.datetime | None:
        """Return when dienst last completed successfully.

        Args:
            dienst:  Service name to query.
            server:  Override server name (defaults to self._server).

        Returns:
            Parsed datetime of the last stop-status report, or None if
            no successful run is recorded or on any network/parse error.
        """
        srv = server if server is not None else self._server
        params = urllib.parse.urlencode({"server": srv, "dienst": dienst})
        url = f"{self._base_url}/api/tools/last-success?{params}"
        try:
            with urllib.request.urlopen(url, timeout=self._timeout) as resp:
                if resp.status != 200:
                    return None
                body = json.loads(resp.read().decode())
                return datetime.datetime.fromisoformat(body["reported_at"])
        except Exception:
            return None

    def require_success(
        self,
        dienst: str,
        within_minutes: int,
        server: str | None = None,
    ) -> None:
        """Assert that dienst ran successfully within the last within_minutes minutes.

        Use this to declare a dependency before executing a downstream service.

        Args:
            dienst:         Dependency service name to check.
            within_minutes: Maximum age of the last successful run in minutes.
            server:         Server to check (defaults to self._server).

        Raises:
            DependencyError: If no successful run was found within the window.
        """
        srv = server if server is not None else self._server
        dt = self.last_success(dienst, server=srv)
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=within_minutes)
        if dt is None or dt < cutoff:
            if dt is None:
                age_str = "never"
            else:
                age_min = int((datetime.datetime.utcnow() - dt).total_seconds() / 60)
                age_str = f"last success {age_min}m ago"
            raise DependencyError(
                f"Prerequisite not met: '{dienst}' on '{srv}' "
                f"did not succeed within the last {within_minutes}m ({age_str})"
            )

    @property
    def version(self) -> str:
        """Return the version of this client module."""
        return __version__

    @property
    def last_error(self) -> str | None:
        """Return the error detail from the last failed report() call, or None if successful."""
        return self._last_error

    def check_version(self) -> dict:
        """Check whether this client copy is up to date with the server's canonical version.

        Calls GET /api/client/version on the connected server and compares against
        the __version__ embedded in this file.

        Returns:
            Dict with keys:
                'local':      version string of this file
                'remote':     version string reported by the server, or None on error
                'up_to_date': True if local >= remote, False if outdated, None if unknown
        """
        url = f"{self._base_url}/api/client/version"
        try:
            with urllib.request.urlopen(url, timeout=self._timeout) as resp:
                body = json.loads(resp.read().decode())
                remote = body.get("version")
                if not remote:
                    return {"local": __version__, "remote": None, "up_to_date": None}
                up_to_date = _parse_version(__version__) >= _parse_version(remote)
                return {"local": __version__, "remote": remote, "up_to_date": up_to_date}
        except Exception:
            return {"local": __version__, "remote": None, "up_to_date": None}

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
