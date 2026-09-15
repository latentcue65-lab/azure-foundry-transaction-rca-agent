import os

from rca_agent.config import ensure_azure_cli_on_path


def test_azure_cli_path_helper_is_safe_when_cli_is_available(monkeypatch):
    original_path = os.environ.get("PATH", "")
    monkeypatch.setattr("rca_agent.config.shutil.which", lambda command: "az" if command == "az" else None)
    ensure_azure_cli_on_path()
    assert os.environ.get("PATH", "") == original_path


def test_azure_cli_path_helper_is_safe_off_windows(monkeypatch):
    original_path = os.environ.get("PATH", "")
    monkeypatch.setattr("rca_agent.config.shutil.which", lambda command: None)
    monkeypatch.setattr("rca_agent.config.os.name", "posix")
    ensure_azure_cli_on_path()
    assert os.environ.get("PATH", "") == original_path
