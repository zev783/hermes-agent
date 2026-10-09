"""Opt forks into publisher infrastructure without weakening release gates."""
from __future__ import annotations

import os
from pathlib import Path

UPSTREAM = "NousResearch/hermes-agent"
REQUIRED = (
    "CLOUDFLARE_R2_ACCOUNT_ID",
    "CLOUDFLARE_R2_ACCESS_KEY_ID",
    "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
    "CLOUDFLARE_R2_BUCKET",
    "CLOUDFLARE_R2_PUBLIC_URL",
)


def release_enabled(env: dict[str, str]) -> bool:
    enabled = env.get("GITHUB_REPOSITORY") == UPSTREAM or env.get("ENABLE_RELEASES") == "true"
    if enabled:
        missing = [name for name in REQUIRED if not env.get(name, "").strip()]
        if missing:
            raise ValueError("Release infrastructure is not configured: " + ", ".join(missing))
    return enabled


def main() -> None:
    enabled = release_enabled(dict(os.environ))
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"enabled={str(enabled).lower()}\n")
    message = (
        "Release infrastructure is configured; publisher validation remains required."
        if enabled else
        "Release packaging was not attempted: this fork has not opted into publisher infrastructure. "
        "See .github/FORK_CI.md; configure release-signing, then set the repository variable "
        "ENABLE_RELEASES=true. Source CI remains enabled."
    )
    print(message if enabled else f"::notice::{message}")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(message + "\n")


if __name__ == "__main__":
    main()
