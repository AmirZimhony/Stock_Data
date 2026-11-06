import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _reset_scrape_state(monkeypatch):
    """Keep legacy Finviz tests off the real 2s gap and clear breaker state between tests."""
    monkeypatch.setenv("SCRAPE_REQUEST_INTERVAL_SECONDS", "0")
    import legacy_finviz as sf

    sf.reset_scrape_state()
    yield
    sf.reset_scrape_state()
