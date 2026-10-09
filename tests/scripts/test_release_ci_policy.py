"""Forks must opt into publishing; admitted releases still fail closed."""
import pytest

from scripts.releases.ci_policy import REQUIRED, UPSTREAM, release_enabled


def test_unprovisioned_fork_does_not_attempt_publishing():
    assert not release_enabled({"GITHUB_REPOSITORY": "fixture/hermes-agent"})


@pytest.mark.parametrize("repository,opt_in", [(UPSTREAM, ""), ("fixture/hermes-agent", "true")])
def test_enabled_publisher_requires_every_storage_setting(repository, opt_in):
    env = {"GITHUB_REPOSITORY": repository, "ENABLE_RELEASES": opt_in, **dict.fromkeys(REQUIRED, "configured")}
    assert release_enabled(env)
    for setting in REQUIRED:
        with pytest.raises(ValueError, match=setting):
            release_enabled({**env, setting: ""})
