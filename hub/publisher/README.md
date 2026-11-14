# Publisher prototype

`build_catalogue.py` validates local uncompressed addon TAR packages, checks the package ID against a single `addon.inf` name assignment, computes SHA-256 and emits deterministic unsigned JSON. The TAR scanner requires aligned blocks, an intact two-block end marker and zero-only trailing padding. It checks basic header fields, paths, entry types, duplicates and file/directory conflicts against the PHP preflight rules.

Build from a stable directory containing only the intended packages. Real exports still need comparison against the stock Composr exporter and importer. The publisher preserves the explicit Unix UTC `issued_at` and `expires_at` values, validates freshness against the current clock, and checks the output against the addon catalogue schema. It needs Python and `jsonschema`. Copy `hub/examples/catalogue-source.json` and update both example timestamps for the intended publication window. Set the expiry in the future and within 30 days of issuance. The builder keeps the supplied timestamps so identical inputs produce identical unsigned bytes during that window.

Build and sign locally from the checkpoint root. Set the catalogue key file and key ID separately from the core release key.

```sh
python3 hub/publisher/build_catalogue.py \
    --input "$catalogue_source" --package-root "$package_dir" --output "$catalogue_output"
python3 hub/publisher/sign_manifest.py \
    --manifest "$catalogue_output" --private-key "$CATALOGUE_KEY_FILE" \
    --key-id "$CATALOGUE_KEY_ID" --signature-output "$catalogue_signature"
```

Review package provenance and licensing before publication. For verified catalogues passed to the offline merger, source identity and priority come from the registry. Unspecified registry priority is zero. See [component tests](../tests/README.md).

## Core releases

`build_release_package.py` creates a repeatable TAR.GZ from a staged core tree and writes an inventory and checksum list. `build_release_manifest.py` generates unsigned core metadata using the archive's SHA-256, the Extended version, the upstream release and exact baseline commit, and the intended HTTPS URL. See the [offline release workflow](../../cms/docs/extended/release-process.md#offline-prototype) for commands and key handling.

`check_release_staging.py` reports the staged tree and flags common accidental inclusions. `verify_release.py` checks the signed manifest, archive digest, and packaged files against the inventory using a pinned core public key.
