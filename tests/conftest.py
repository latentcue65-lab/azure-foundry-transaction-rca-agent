import pytest

from rca_agent.config import Settings
from rca_agent.mock_api import running_mock
from rca_agent.seed import seed


@pytest.fixture
def settings(tmp_path):
    config = Settings(
        _env_file=None, mode="replay", data_dir=tmp_path / "data", output_dir=tmp_path / "outputs"
    )
    seed(config)
    with running_mock(config.data_dir) as url:
        yield config.model_copy(update={"mock_api_url": url})
