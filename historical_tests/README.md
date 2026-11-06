# Historical local-data tests

These two byte-identical test files came from remote main. The gold/silver
assignment tests require historical collection manifests and image files; the
repository-path tests require legacy annotation/assignment inputs. Those fixtures
are intentionally not bundled with this external-dataset candidate. Their first
full-suite execution produced the 18 expected fixture-related failures recorded
in the private integration report. Other assertions in these files also remain
archival; no assertions were rewritten to hide a failure.

The privacy patch restores selected metadata and minimized assignment/annotation
derivatives. Historical collection/image fixtures remain absent; this does not
make these full historical tests supported. Their source/assertions are unchanged.

The supported offline suite is tests/ (the default pytest testpaths). Historical
tests are preserved here for future adapter/fixture work and are not counted as
passing supported tests. Do not restore persistent dataset images to run them.
