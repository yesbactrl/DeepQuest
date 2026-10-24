from pathlib import Path

import pytest

from deepquest.__main__ import acquire_instance_lock

URL = "http://127.0.0.1:8484"


def test_second_instance_stops_with_message(tmp_path: Path) -> None:
    first = acquire_instance_lock(tmp_path, URL)

    with pytest.raises(SystemExit) as stopped:
        acquire_instance_lock(tmp_path, URL)

    message = str(stopped.value)
    assert message.startswith("DeepQuest уже запущен (PID ")
    assert "Ctrl+C" in message
    assert "service restart" in message
    first.close()
    # Первый вышел — замок снят, можно запускаться снова.
    acquire_instance_lock(tmp_path, URL).close()
