#!/bin/sh
set -eu

root=$(CDPATH='' cd -- "$(dirname -- "$0")/../.." && pwd)
if [ "$#" -eq 0 ]; then
    set -- 8.2 8.3 8.4 8.5
fi
for minor do
    case "$minor" in
        8.2|8.3|8.4|8.5) ;;
        *) echo "Unsupported PHP version: $minor" >&2; exit 2 ;;
    esac
done

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required for the matrix. To use a local PHP CLI, run hub/tests/run_components.sh." >&2
    exit 1
fi

result=0
for minor do
    image="composr-extended-component-tests:php-$minor"
    echo "PHP $minor component tests"
    if ! docker build --pull --build-arg "PHP_MINOR=$minor" \
        --tag "$image" --file "$root/hub/tests/php-components.Dockerfile" "$root/hub/tests"; then
        result=1
        continue
    fi
    if ! docker run --rm --network none --user "$(id -u):$(id -g)" \
        --mount "type=bind,source=$root,target=/checkpoint,readonly" \
        --workdir /checkpoint "$image" sh hub/tests/run_components.sh "$minor"; then
        result=1
    fi
done
exit "$result"
