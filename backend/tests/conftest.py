import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.mkdtemp(prefix="anvaya-test-")
os.environ["ANVAYA_DATA_DIR"] = _tmp
os.environ["FREEMODEL_API_KEY"] = ""          # unit tests never touch the network or the real key
os.environ["ANVAYA_CORS_ORIGINS"] = "http://localhost:5173"

import pytest  # noqa: E402

from anvaya.config import settings  # noqa: E402
from anvaya.db import reset_store_for_tests  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    settings.freemodel_api_key = ""
    settings.data_dir = tmp_path
    reset_store_for_tests(str(tmp_path / "t.sqlite3"))
    yield


def make_agents(n=60, seed=1):
    from anvaya.agents.generator import interpret_offline, sample
    spec = interpret_offline("People react to a new transit fare policy")
    return spec, sample(spec, n, seed)
