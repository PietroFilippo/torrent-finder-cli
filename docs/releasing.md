# Releasing Torrent Finder CLI

Package versions come from Git tags through setuptools-scm. Do not edit
`torrent_finder/_version.py`; it is generated during builds and ignored by Git.

1. Review the commits since the latest release and select an unused version.
   Update README usage guidance and add `docs/releases/vX.Y.Z.md` with changes,
   limitations, and upgrade instructions.
2. Run `python -m unittest discover -s tests -v` and `git diff --check`.
   Commit the release documentation with the implementation it describes.
3. Create an annotated `vX.Y.Z` tag on the release commit. If building locally,
   `python -m build` should produce an sdist and wheel with exactly that version.
4. Push the branch and tag. `.github/workflows/release.yml` runs tests and builds
   distributions, publishes the tagged version to PyPI through Trusted
   Publishing, and builds the three standalone GitHub Release assets.
5. Check the workflow's build, PyPI, and all binary jobs. Set the GitHub Release
   title and body from the committed release notes. Verify the PyPI version and
   all three downloadable assets before announcing completion.

The `workflow_dispatch` action publishes to **TestPyPI**, not production PyPI.
Production releases are triggered by a pushed `v*` tag. PyPI versions are
immutable: after publication, code fixes need a new version. Do not move an
already-published release tag.
