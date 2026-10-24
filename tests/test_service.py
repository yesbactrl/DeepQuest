import plistlib
from pathlib import Path

from deepquest.service import LABEL, build_plist


def test_plist_runs_project_with_uv_and_restarts() -> None:
    plist = build_plist("/opt/homebrew/bin/uv", Path("/repo"), Path("/logs/deepquest.log"))

    assert plist["Label"] == LABEL
    assert plist["ProgramArguments"] == [
        "/usr/bin/caffeinate",
        "-is",
        "/opt/homebrew/bin/uv",
        "run",
        "--directory",
        "/repo",
        "deepquest",
    ]
    # .env читается из рабочей папки.
    assert plist["WorkingDirectory"] == "/repo"
    assert plist["RunAtLoad"] and plist["KeepAlive"]
    assert plist["EnvironmentVariables"]["ACCESS_LOG"] == "false"
    assert "/opt/homebrew/bin" in plist["EnvironmentVariables"]["PATH"]
    assert plist["StandardErrorPath"] == "/logs/deepquest.log"
    # launchd примет только корректный plist.
    assert plistlib.loads(plistlib.dumps(plist)) == plist
