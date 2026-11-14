ARG PHP_MINOR=8.4
FROM php:${PHP_MINOR}-cli
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-cryptography python3-jsonschema \
    && rm -rf /var/lib/apt/lists/*
