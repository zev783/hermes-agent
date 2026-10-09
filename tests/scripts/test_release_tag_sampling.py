"""Release sampling follows tag chronology across CalVer and SemVer."""
import os
import subprocess

import pytest

from scripts.releases.pick_tags import pick_tags


def test_sampling_includes_newest_stable_and_excludes_candidate(tmp_path):
    def git(*args, env=None):
        return subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True, text=True)

    git("init", "-b", "main")
    git("config", "user.name", "fixture")
    git("config", "user.email", "fixture@example.invalid")
    for index, tag in enumerate(["v2026.7.20", "v0.27.0", "v0.28.0"]):
        env = {**os.environ, "GIT_AUTHOR_DATE": f"2026-08-{index + 1:02d}T00:00:00Z", "GIT_COMMITTER_DATE": f"2026-08-{index + 1:02d}T00:00:00Z"}
        git("commit", "--allow-empty", "-m", tag, env=env)
        git("tag", tag)
    assert pick_tags(tmp_path, 1, "v0.28.0") == ["v0.27.0"]
    assert pick_tags(tmp_path, 3, "v0.28.0") == ["v2026.7.20", "v0.27.0"]


def test_canary_only_fork_requires_explicit_empty_baseline_policy(tmp_path):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True)

    git("init", "-b", "main")
    git("config", "user.name", "fixture")
    git("config", "user.email", "fixture@example.invalid")
    git("commit", "--allow-empty", "-m", "fork")
    git("tag", "v0.21.4+canary.20261009T134353Z")
    with pytest.raises(ValueError, match="No released baseline"):
        pick_tags(tmp_path, 2)
    assert pick_tags(tmp_path, 2, allow_empty=True) == []
    git("tag", "v0.21.4")
    assert pick_tags(tmp_path, 2, allow_empty=True) == ["v0.21.4"]
    with pytest.raises(ValueError, match="No released baseline"):
        pick_tags(tmp_path, 2, "v0.21.4")
