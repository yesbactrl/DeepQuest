"""Служба macOS: `uv run deepquest service install|uninstall|restart|status|logs`.

DeepQuest ставится агентом launchd в ~/Library/LaunchAgents: стартует при входе в систему,
поднимается заново после падения и работает без открытого терминала. После обновления
кода достаточно `service restart`.
"""

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from deepquest.config import PROJECT_ROOT

LABEL = "com.deepquest.app"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_PATH = Path.home() / "Library" / "Logs" / "DeepQuest" / "deepquest.log"
# Под launchd PATH минимальный, а агенту нужен `claude`, а uv — свой каталог инструментов.
SERVICE_PATH = ["/opt/homebrew/bin", str(Path.home() / ".local" / "bin"), "/usr/bin", "/bin"]
# Не чаще одного перезапуска за столько секунд: если старт падает сразу (занят замок,
# сломан .env), launchd не будет крутить его вхолостую.
THROTTLE_S = 30
# Пока DeepQuest работает, Mac на зарядке не засыпает (-s), а от простоя не засыпает и от
# батареи (-i): иначе бот молчит, а утренние задания приходят с опозданием.
CAFFEINATE = ["/usr/bin/caffeinate", "-is"]

USAGE = """Использование: uv run deepquest service <команда>

  install    установить и запустить службу (автозапуск при входе в систему)
  uninstall  остановить и убрать службу
  restart    перезапустить — например, после обновления кода
  status     работает ли служба
  logs       последние строки журнала"""


def build_plist(uv: str, project_root: Path, log_path: Path) -> dict[str, Any]:
    return {
        "Label": LABEL,
        "ProgramArguments": [*CAFFEINATE, uv, "run", "--directory", str(project_root), "deepquest"],
        # Из рабочей папки читается .env.
        "WorkingDirectory": str(project_root),
        "EnvironmentVariables": {
            "PATH": ":".join(SERVICE_PATH),
            "ACCESS_LOG": "false",
            "PYTHONUNBUFFERED": "1",
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": THROTTLE_S,
        "ProcessType": "Interactive",
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
    }


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=check)


def _loaded() -> bool:
    return _launchctl("print", f"{_domain()}/{LABEL}", check=False).returncode == 0


def install() -> int:
    uv = shutil.which("uv")
    if uv is None:
        print("Не нашёл uv в PATH: установи его или запусти команду из терминала, где он есть.")
        return 1
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _loaded():
        _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)
    PLIST_PATH.write_bytes(plistlib.dumps(build_plist(uv, PROJECT_ROOT, LOG_PATH)))
    result = _launchctl("bootstrap", _domain(), str(PLIST_PATH), check=False)
    if result.returncode != 0:
        print(f"launchctl не принял службу: {result.stderr.strip()}")
        return 1
    print(f"Служба установлена и запущена: {LABEL}")
    print(f"Журнал: {LOG_PATH}")
    print("Если DeepQuest уже открыт в терминале — останови его там: служба подхватит сама.")
    return 0


def uninstall() -> int:
    if _loaded():
        _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)
    PLIST_PATH.unlink(missing_ok=True)
    print("Служба остановлена и убрана. Запускать снова — uv run deepquest в терминале.")
    return 0


def restart() -> int:
    if not _loaded():
        print("Служба не установлена: uv run deepquest service install")
        return 1
    _launchctl("kickstart", "-k", f"{_domain()}/{LABEL}")
    print("Служба перезапущена.")
    return 0


def status() -> int:
    result = _launchctl("print", f"{_domain()}/{LABEL}", check=False)
    if result.returncode != 0:
        print("Служба не установлена.")
        return 1
    wanted = ("state =", "pid =", "last exit code =", "runs =")
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith(wanted):
            print(line)
    print(f"Журнал: {LOG_PATH}")
    return 0


def logs(lines: int = 40) -> int:
    if not LOG_PATH.exists():
        print("Журнала пока нет.")
        return 1
    with LOG_PATH.open(errors="replace") as log:
        print("".join(log.readlines()[-lines:]), end="")
    return 0


COMMANDS = {
    "install": install,
    "uninstall": uninstall,
    "restart": restart,
    "status": status,
    "logs": logs,
}


def main(args: list[str]) -> int:
    if sys.platform != "darwin":
        print("Служба есть только для macOS (launchd).")
        return 1
    command = COMMANDS.get(args[0]) if args else None
    if command is None:
        print(USAGE)
        return 2
    return command()
