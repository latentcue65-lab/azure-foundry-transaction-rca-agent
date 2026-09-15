import os
import shutil
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def ensure_azure_cli_on_path() -> None:
    """Make the MSI-installed Azure CLI visible to DefaultAzureCredential on Windows.

    A newly installed CLI can be absent from the inherited PATH of an already-open
    editor or terminal. This is intentionally a Windows-only fallback; other
    platforms use their normal PATH resolution.
    """
    if shutil.which("az") or os.name != "nt":
        return
    azure_cli = Path(r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin")
    if (azure_cli / "az.cmd").is_file():
        os.environ["PATH"] = str(azure_cli) + os.pathsep + os.environ.get("PATH", "")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    mode: Literal["foundry", "replay"] = Field("foundry", validation_alias="RCA_MODE")
    data_dir: Path = Field(Path("data"), validation_alias="RCA_DATA_DIR")
    output_dir: Path = Field(Path("outputs"), validation_alias="RCA_OUTPUT_DIR")
    mock_api_url: str = Field("http://127.0.0.1:8091/events", validation_alias="RCA_MOCK_API_URL")
    http_timeout: float = Field(5, gt=0, le=30, validation_alias="RCA_HTTP_TIMEOUT")
    max_turns: int = Field(12, ge=1, le=30, validation_alias="RCA_MAX_TURNS")
    max_tool_calls: int = Field(18, ge=1, le=60, validation_alias="RCA_MAX_TOOL_CALLS")
    deadline_seconds: float = Field(120, gt=0, le=600, validation_alias="RCA_DEADLINE_SECONDS")
    page_size: int = Field(100, ge=1, le=200, validation_alias="RCA_PAGE_SIZE")
    max_events: int = Field(1000, ge=1, le=2000, validation_alias="RCA_MAX_EVENTS")
    project_endpoint: str = Field("", validation_alias="FOUNDRY_PROJECT_ENDPOINT")
    model_name: str = Field("", validation_alias="FOUNDRY_MODEL_NAME")
    agent_name: str = Field("sphere-transaction-rca", validation_alias="FOUNDRY_AGENT_NAME")
    agent_version: str = Field("", validation_alias="FOUNDRY_AGENT_VERSION")

    @field_validator("mock_api_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("Use a configured http(s) mock endpoint without embedded credentials")
        return value

    @property
    def db_path(self) -> Path:
        return self.data_dir / "transactions.db"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "logs" / "checkout.jsonl"

    def require_foundry(self) -> None:
        if not self.project_endpoint or not self.model_name:
            raise ValueError(
                "Set FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL_NAME in .env, then run rca register"
            )
        parsed = urlparse(self.project_endpoint)
        if parsed.scheme != "https" or "/api/projects/" not in parsed.path:
            raise ValueError(
                "FOUNDRY_PROJECT_ENDPOINT must be the HTTPS project endpoint copied from Foundry"
            )
