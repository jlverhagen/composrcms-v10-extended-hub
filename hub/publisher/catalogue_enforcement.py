#!/usr/bin/env python3
"""Activate catalogue enforcement checksums after a verified stock CMS upgrade."""

import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat
import tarfile
import tempfile


GUARDED_FILES = (
    "adminzone/pages/modules_custom/admin_extended_addons.php",
    "sources_custom/extended_addon_catalogue.php",
    "sources_custom/extended_catalogue_high_water.php",
    "sources_custom/extended_manifest_verify.php",
    "sources_custom/extended_registry_trust.php",
    "sources_custom/extended_addon_browser.php",
    "sources_custom/extended_registry_admin_review.php",
)


def render_checksums(digests):
    return "".join(f"{digests[name]}  {name}\n" for name in GUARDED_FILES)


def release_checksums(package, expected_sha256):
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("Provide the verified release's lowercase SHA-256")
    with package.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected_sha256:
            raise ValueError("Upgrade package SHA-256 does not match the verified release")
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode="r:") as archive:
            digests = {}
            for member in archive:
                if member.name not in GUARDED_FILES:
                    continue
                if not member.isfile() or member.name in digests:
                    raise ValueError(f"Invalid guarded package member: {member.name}")
                with archive.extractfile(member) as content:
                    digests[member.name] = hashlib.file_digest(content, "sha256").hexdigest()
    if set(digests) != set(GUARDED_FILES):
        raise ValueError("The upgrade package is missing guarded files")
    return digests


def activate(site, manifest, digests):
    if manifest.resolve() != manifest or manifest.is_relative_to(site):
        raise ValueError("Use an unlinked enforcement manifest outside the site")
    for parent in manifest.parents:
        info = parent.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError(f"Enforcement directory must be root-owned and protected: {parent}")
    lock_path = manifest.with_name(manifest.name + ".lock")
    with os.fdopen(os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), "rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        info = manifest.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("The existing manifest must be a protected root-owned regular file")
        existing = manifest.read_text(encoding="ascii").splitlines()
        entries = [re.fullmatch(r"[0-9a-f]{64} [ *](.+)", line) for line in existing]
        if (len(entries) != len(GUARDED_FILES) or any(entry is None for entry in entries)
                or {entry[1] for entry in entries} != set(GUARDED_FILES)):
            raise ValueError("Existing enforcement manifest has a different protected file set")

        mismatches = []
        for name, expected in digests.items():
            path = site / name
            if path.resolve() != path or not path.is_file():
                mismatches.append(name)
                continue
            with path.open("rb") as content:
                if hashlib.file_digest(content, "sha256").hexdigest() != expected:
                    mismatches.append(name)
        if mismatches:
            raise ValueError("Installed guarded files differ from the verified release: " + ", ".join(mismatches))

        handle, temporary_name = tempfile.mkstemp(prefix=".enforcement-", dir=manifest.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="ascii") as target:
                target.write(render_checksums(digests))
                target.flush()
                os.fchown(target.fileno(), info.st_uid, info.st_gid)
                os.fchmod(target.fileno(), stat.S_IMODE(info.st_mode))
                for attribute in os.listxattr(manifest):
                    os.setxattr(temporary, attribute, os.getxattr(manifest, attribute))
                os.fsync(target.fileno())
            temporary.replace(manifest)
            directory = os.open(manifest.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--sha256", required=True, help="Package digest from a trusted release source")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run as root on the guarded host")
    try:
        activate(args.site_root.resolve(strict=True), args.manifest.absolute(),
                 release_checksums(args.package, args.sha256))
    except (OSError, ValueError, tarfile.TarError) as error:
        parser.exit(1, f"Catalogue enforcement activation failed: {error}\n")
    print("Activated verified catalogue enforcement checksums.")


if __name__ == "__main__":
    main()
