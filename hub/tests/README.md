# Component tests

From the checkpoint root, run all four PHP minor versions on a Docker host.

```sh
sh hub/tests/run_php_matrix.sh
```

To run just PHP 8.4, use `sh hub/tests/run_php_matrix.sh 8.4`. The image build needs access to the PHP image registry and Debian package repositories. The tests run with networking disabled and mount the checkpoint read-only. The matrix continues after a failed version and returns failure if any requested version fails. Minor-version tags track new patch releases. Record the exact runtime versions printed by the runner when comparing results.

With a local PHP CLI on PATH, use `sh hub/tests/run_components.sh 8.4`, substituting the installed minor version. The runner checks the PHP version and the cURL and Sodium extensions, prints Python, cryptography and jsonschema versions, lints the scaffold's PHP files, runs unittest discovery, and runs the standalone preflight checks. It needs Python 3.11 or later and the Python `cryptography` and `jsonschema` packages. The standalone script is invoked separately from unittest discovery.

The Python publisher, signing, and core release suites can run independently of PHP. The core release suite uses Python 3.11 or later.

```sh
python3 -m unittest discover -s hub/tests -p test_publisher.py
python3 -m unittest discover -s hub/tests -p test_catalogue_fixtures.py
python3 -m unittest discover -s hub/tests -p test_signing.py
python3 -m unittest discover -s hub/tests -p test_core_release.py
python3 -m unittest discover -s hub/tests -p test_release_checks.py
```

These checks cover the scaffold components. Use the [disposable Composr smoke tests](../../cms/docs/extended/disposable-smoke-tests.md) to verify CMS behavior.

The fixed [catalogue fixtures](fixtures/catalogues/README.md) are shared by Python and PHP. The PHP case runs automatically when the suite finds a PHP CLI.
