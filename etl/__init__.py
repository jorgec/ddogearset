"""The dev-only ETL that builds `catalog.db` from a DDOBuilderV2 checkout.

**This package never ships.** It is not embedded in the Wails binary, it is not
extracted at runtime, and the end user never invokes it — see
docs/0.5.0/00_ETL_START_HERE.md constraints 1 and 3. It runs from the build
scripts (or by hand, `python -m etl`) on a developer machine, and its only
output is a `catalog.db` file the app then reads.

Entry point: `python -m etl --help` (see `cli.py`).
"""

# Stamped into catalog_meta.etl_version. Bump when the ETL's *output* changes
# shape in a way worth telling apart at inspection time — not on every code
# edit. Distinct from catalog_meta.schema_version (the DDL's version, in
# load.py) and from catalog_version (a per-published-build counter).
ETL_VERSION = "0.5.0"

# Stamped into catalog_meta.min_app_version: the OLDEST app release that can
# read a catalog this ETL produces. 0.5.0 is the first release that reads
# catalog.db at all, so nothing earlier can ever open one.
#
# Bump this only when a catalog change genuinely requires a newer app — NOT
# with every app release. Setting it to "whatever version is being built right
# now" would make every catalog refuse every older app for no reason, which is
# the opposite of what the field is for (schema doc §5.1.2).
MIN_APP_VERSION = "0.5.0"
