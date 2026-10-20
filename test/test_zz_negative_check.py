"""Temporary negative check for CI-4 (must never be merged).

If CI is a real gate, this test makes the `python` job (and therefore the
aggregate `ci` check) fail. The commit that adds this file is reverted
immediately after the red run is captured.
"""


def test_intentional_failure():
    assert False, "negative verification: CI must turn red"
