# Shared signed catalogue fixtures

Both test implementations use these exact UTF-8 bytes and a fixed verification time of Unix timestamp `1800000000`. The source ID is `extended-hub` and the signing key ID is `fixture-catalogue`.

| Manifest | Detached signature | Expected result |
| --- | --- | --- |
| `valid.json` | `valid.sig.json` | Signature and validity window pass. |
| `expired.json` | `expired.sig.json` | Signature passes. The validity window ends exactly at the test clock and is rejected. |
| `tampered.json` | `valid.sig.json` | A changed addon name fails signature verification. |

The public key is a test trust pin. The signing seed was temporary. Keep the checked-in bytes unchanged when running the tests. `source.json` and the USTAR fixture created by the Python test reproduce `valid.json` byte for byte.
