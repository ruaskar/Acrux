# Releasing keymd

Releases are **automatic**. The binary at `releases/latest` — what `install.sh` /
`install.ps1` download and what `keymd update` upgrades to — is built and published by
the [`binary`](.github/workflows/binary.yml) workflow whenever the version changes.

## Cut a release

1. Bump the version in **one** place — `keymd.__version__`
   ([src/keymd/__init__.py](src/keymd/__init__.py)). `pyproject.toml` reads it dynamically,
   so this is the only edit.
2. Open a PR with that bump and merge it to `master`.

On the merge, the `binary` workflow:
- reads `keymd.__version__`,
- if a `v<version>` release does **not** already exist, builds the binary for
  linux-x86_64 / macos-aarch64 / windows-x86_64, smoke-tests each, and publishes a
  GitHub Release `v<version>` with the three binaries + `SHA256SUMS`.

A master push that doesn't change the version is a no-op past the cheap `check` job, so
ordinary merges don't trigger builds.

## Fallback

Pushing a `v*` tag manually (`git tag vX.Y.Z <sha> && git push origin vX.Y.Z`) builds and
releases that exact version too — use this if the auto path ever needs to be bypassed.

## After a release

Users on a prior binary upgrade in place with **`keymd update`** (downloads the new asset,
verifies it against the published `SHA256SUMS`, and self-replaces). Fresh installs get the
new version from the one-line installer automatically.

## Notes

- Do **not** publish to PyPI as part of a release (the binary embeds the wheel; no PyPI
  dependency).
- Linux is built on the oldest supported runner glibc (ubuntu-22.04 / glibc 2.35) so the
  binary runs on Debian 12 / RHEL-adjacent systems; don't move it to `ubuntu-latest`.
