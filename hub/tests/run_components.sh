#!/bin/sh
set -eu

root=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$root"

expected_minor=${1:-}
case "$expected_minor" in
    8.2|8.3|8.4|8.5) ;;
    *) echo "Usage: $0 8.2|8.3|8.4|8.5" >&2; exit 2 ;;
esac

if ! command -v php >/dev/null 2>&1; then
    echo "PHP CLI is required on PATH." >&2
    exit 1
fi

php -r '
    $actual = PHP_MAJOR_VERSION . "." . PHP_MINOR_VERSION;
    if ($actual !== $argv[1]) {
        fwrite(STDERR, "Expected PHP " . $argv[1] . ", found " . PHP_VERSION . PHP_EOL);
        exit(1);
    }
    foreach (["sodium", "curl"] as $extension) {
        if (!extension_loaded($extension)) {
            fwrite(STDERR, "Missing PHP extension: " . $extension . PHP_EOL);
            exit(1);
        }
    }
    echo "PHP " . PHP_VERSION . PHP_EOL;
' "$expected_minor"

export PYTHONDONTWRITEBYTECODE=1
python3 -c 'from importlib.metadata import version; import sys; print("Python", sys.version.split()[0], "cryptography", version("cryptography"), "jsonschema", version("jsonschema"))'
find cms -type f -name '*.php' -exec sh -c '
    for source do
        php -l "$source" || exit 1
    done
' sh {} +
python3 -m unittest discover -s hub/tests -p 'test_*.py' -v
python3 hub/tests/test_php_local_preflight_manual.py
