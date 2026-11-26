# Maintained publication scope

Approved by the project owner on 2026-11-20; see core audit issue #36.

The retained `composr_homesite_support_credits` registry and its MantisBT tracker dependencies are outside maintained addon publication. `build_addon_tars.php` omits this ID during automatic enumeration and rejects any explicit request containing it before loading source modules or creating partial outputs. Other addon selection remains unchanged.

Source retention is not a compatibility claim. GitHub source archives can still contain the tracker tree; this change does not remove existing installations, database records or previously published artifacts. Validate final release/catalogue inventories separately before publication. The mirror will not use tracker/support-credits; eventual source removal is a separate cleanup task.

Run `PHP_BINARY=/path/to/php python3 hub/tests/test_addon_maintenance_policy.py` to check selection. The four tests use inert registry/archive adapters to prove exclusion and normal selection; they do not validate real TAR payloads or catalogue synchronization. They passed using PHP 8.2.35, 8.3.36, 8.4.27 and 8.5.12 on techie75. The builder also passed lint on each.


## Spreadsheet support, 2026-11-26

The owner excluded `excel_support` from Extended releases until it is rewritten and reviewed (core issue #72). The offline addon builder skips it during enumeration and rejects explicit or mixed requests. Installer construction and verification reject its known core payload paths; staged source-release preflight and packaging also reject those paths. The source repository and GitHub-generated source snapshots retain upstream reference code. Existing installations, data and historical releases are not deleted. Catalogue creation accepts arbitrary locally provided third-party packages, so the publisher must also check that an Extended catalogue does not list the excluded addon before signing or publishing. This is a publication policy, not a restriction on other addon sources.

The policy tests cover automatic and explicit selection, mixed requests, and unrelated addon selection. A reviewed local run also built the 20 remaining historical candidate addon TARs without the spreadsheet payload. Final signed catalogue, published artifacts and web lifecycle acceptance require separate verification.
