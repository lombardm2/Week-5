import json
import os
import sys
from pathlib import Path

import duckdb
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def con():
    path = Path(os.environ.get("WAREHOUSE", ROOT / "build/warehouse.duckdb"))
    if not path.exists():
        pytest.exit(f"Warehouse not found at {path}; run `make build` first.", returncode=2)
    c = duckdb.connect(str(path), read_only=True)
    yield c
    c.close()


@pytest.fixture(scope="session")
def manifest():
    return json.loads((ROOT / "data/raw/_manifest.json").read_text())


@pytest.fixture(scope="session")
def contract():
    return yaml.safe_load((ROOT / "contracts/accounts.yml").read_text())


@pytest.fixture(scope="session")
def expected_schemas():
    return yaml.safe_load((ROOT / "tests/expected_schemas.yml").read_text())
