"""Keep all test data isolated from the user's real research and from other tests."""
import os
import tempfile

import pytest

# Set data home before any application module is imported by test collection.
os.environ['THERAPY_DATA_HOME'] = tempfile.mkdtemp(prefix='therapy-test-') + '/data'


@pytest.fixture(autouse=True)
def clean_research_state_between_tests():
    """Prevent synthetic completed assessments leaking into later tests.

    In particular, a completed synthetic ranking in test_analysis_state must
    not make the incomplete-rank API test unexpectedly return HTTP 200.
    """
    from finder import state
    state.FILE.unlink(missing_ok=True)
    yield
    state.FILE.unlink(missing_ok=True)
