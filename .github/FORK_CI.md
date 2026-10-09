# CI in a Hermes fork

Source CI runs on standard GitHub-hosted runners by default in forks. The
official repository retains its larger runners. Repository variables can
override labels without changing workflow files:

| Variable | Fork default |
| --- | --- |
| `CI_LINUX_X64_RUNNER` | `ubuntu-latest` |
| `CI_LINUX_ARM64_RUNNER` | `ubuntu-24.04-arm` |
| `CI_WINDOWS_X64_RUNNER` | `windows-latest` |
| `CI_WINDOWS_ARM64_RUNNER` | `windows-11-arm` |

Fork Python lanes use fewer concurrent workers and longer job budgets for
standard runners. Test coverage and failure gates are unchanged.

The install/update matrix samples stable SemVer and historical CalVer tags.
A fork with no stable releases still tests real `HEAD -> NEXT` transitions;
the run summary explicitly marks historical-release coverage unavailable.
Official and stable-release gates require released baselines. A results
reporter survives a failed picker without adding a secondary JSON failure.

The red tracker checks whether issues are enabled before using the issue API.
When disabled, it leaves a notice; the original E2E job conclusions remain
authoritative. Enable repository issues if tracking issues are desired.

## Publisher infrastructure

Forks do not automatically tag canaries or attempt signed desktop releases.
These workflows report **not attempted**, not a successful package build.
To enable them, provision the fork's own `release-signing` environment:

- Secrets: `CLOUDFLARE_R2_ACCOUNT_ID`, `CLOUDFLARE_R2_ACCESS_KEY_ID`,
  `CLOUDFLARE_R2_SECRET_ACCESS_KEY`.
- Variables: `CLOUDFLARE_R2_BUCKET`, `CLOUDFLARE_R2_PUBLIC_URL`.
- Native signing/notarization settings for the selected platforms, as
  documented in `desktop-bundled-release.yml`.

Then set the repository Actions variable `ENABLE_RELEASES` to `true`.
Enabled publishers fail if storage settings are missing. This does not
disable archive verification, source admission, signing, native smoke tests,
or publication gates. Never copy an upstream publisher's credentials into a fork.
