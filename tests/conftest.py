"""pytest setup: the shared test baseline lives in ``isolation``.

``isolation`` redirects saved settings and starts every test from the Simple
design, under unittest (the CI and release runner) and pytest alike, so this
file only makes sure it is imported.
"""

import isolation  # noqa: F401
