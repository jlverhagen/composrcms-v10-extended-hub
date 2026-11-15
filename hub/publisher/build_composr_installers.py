#!/usr/bin/env python3
"""Package a reviewed Composr v10 checkout using its stock release inventory."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
import zlib

from build_release_manifest import CALENDAR_VERSION_PATTERN
from catalogue_enforcement import GUARDED_FILES, render_checksums


def php(code, *args, data=None):
    return subprocess.check_output(["php", "-r", code, "--", *args], input=data)


def inventory(source):
    return json.loads(php("""
        $files = unserialize(file_get_contents($argv[1]), ['allowed_classes' => false]);
        if (!is_array($files)) exit(1);
        echo json_encode(array_keys($files), JSON_THROW_ON_ERROR);
    """, str(source / "data/files.bin")))


def quick_installer(files, data_path, stock_installer):
    with tarfile.open(data_path, "w", format=tarfile.USTAR_FORMAT) as archive:
        write_tar(archive, files)
    with tarfile.open(data_path) as archive:
        locations = {item.name: [item.offset_data, item.size] for item in archive}
    directories = sorted({str(parent) for name in files for parent in PurePosixPath(name).parents if str(parent) != "."})
    index = php("echo var_export(json_decode(stream_get_contents(STDIN), true, 512, JSON_THROW_ON_ERROR), true);",
                data=json.dumps([locations, list(locations), directories]).encode())
    checksum = hashlib.md5(files["data/images/advertise_here.png"]).hexdigest()
    prefix = b"<?php\nlist($QUICK_INDEX, $FILE_ARRAY, $DIR_ARRAY) = " + index + b";\n"
    prefix += f"""
$DATADOTCMS_FILE = @fopen(__DIR__ . '/data.cms', 'rb');
if ($DATADOTCMS_FILE === false || fstat($DATADOTCMS_FILE)['size'] !== {data_path.stat().st_size}) {{
    exit('data.cms missing or wrong size');
}}
function file_array_get($path) {{
    global $QUICK_INDEX, $DATADOTCMS_FILE, $FILE_BASE;
    if (isset($FILE_BASE) && str_starts_with($path, $FILE_BASE . '/')) {{
        $path = substr($path, strlen($FILE_BASE) + 1);
    }}
    if (!isset($QUICK_INDEX[$path])) return null;
    [$offset, $size] = $QUICK_INDEX[$path];
    if ($size === 0) return '';
    fseek($DATADOTCMS_FILE, $offset);
    if ($size > 1024 * 1024) return [$size, $DATADOTCMS_FILE, $offset];
    return fread($DATADOTCMS_FILE, $size);
}}
function file_array_exists($path) {{
    global $QUICK_INDEX;
    return isset($QUICK_INDEX[$path]);
}}
function file_array_get_at($i) {{
    global $FILE_ARRAY;
    return [$FILE_ARRAY[$i], file_array_get($FILE_ARRAY[$i])];
}}
function file_array_count() {{
    global $FILE_ARRAY;
    return count($FILE_ARRAY);
}}
if (md5(file_array_get('data/images/advertise_here.png')) !== '{checksum}') {{
    exit('data.cms failed its integrity check');
}}
?>""".encode()
    return prefix + stock_installer


def write_tar(archive, files):
    for name, content in sorted(files.items()):
        entry = tarfile.TarInfo(name)
        entry.size = len(content)
        entry.mode = 0o644
        archive.addfile(entry, io.BytesIO(content))


def write_zip(path, files):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            if isinstance(data, Path):
                with data.open("rb") as source, archive.open(entry, "w") as target:
                    shutil.copyfileobj(source, target)
            else:
                archive.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED)


def build(source, output, version):
    if not re.fullmatch(CALENDAR_VERSION_PATTERN, version):
        raise ValueError("Expected a calendar release such as 2026.11.1-alpha.1")
    if output.exists() or output.is_relative_to(source):
        raise ValueError("Use a new output directory outside the checkout")

    files = {}
    extended_files = [
        "adminzone/pages/modules_custom/admin_extended_addons.php",
        "themes/default/templates_custom/EXTENDED_ADDON_INSTALL_CANCEL.tpl",
        "sources_custom/hooks/systems/page_groupings/extended_addons.php",
    ] + [path.relative_to(source).as_posix() for path in sorted((source / "sources_custom").glob("extended_*.php"))]
    for name in inventory(source) + extended_files:
        path = PurePosixPath(name)
        if not path.parts or path.is_absolute() or ".." in path.parts or "\\" in name or str(path) != name:
            raise ValueError(f"Invalid inventory path: {name}")
        if path.parts[0] in {"aps", "mobiquo", ".git"} or name == "_config.php":
            continue
        member = source / ("data_custom/execute_temp.php.bundle" if name == "data_custom/execute_temp.php" else name)
        if member.resolve() != member or not member.is_file():
            raise ValueError(f"Missing or linked release file: {name}")
        files[name] = member.read_bytes()

    # The stock upgrader copies files listed by installed addon registry hooks.
    core_registry = "sources/hooks/systems/addon_registry/core.php"
    start = b"public function get_file_list()\n    {\n        return array(\n"
    registry = files[core_registry]
    if registry.count(start) != 1:
        raise ValueError("Cannot locate the core addon file inventory")
    owned = b"".join(f"            '{name}',\n".encode("ascii") for name in extended_files
                     if f"'{name}'".encode("ascii") not in registry)
    files[core_registry] = registry.replace(start, start + owned)

    version_path = "sources_custom/extended_version.php"
    declaration = rb"(function extended_distribution_version\(\)\s*\{\s*return ')[^']+(';)"
    files[version_path], count = re.subn(declaration, rb"\g<1>" + version.encode() + rb"\2", files[version_path])
    if count != 1:
        raise ValueError("Cannot stamp the installed Extended release version")

    files["themes/map.ini"] = b"default=default\n"
    files["data_custom/functions.bin"] = b""
    files["data_custom/errorlog.php"] = b"<?php return; ?>\n"
    files.pop("data/files.bin", None)
    checksums = {}
    for name, content in files.items():
        if name == "sources/version.php":
            content = re.sub(rb"\d{10}", b"", content)
        checksums[name] = [str(zlib.crc32(re.sub(rb"[\r\n\t ]", b"", content)))]
    files["data/files.bin"] = php(
        "echo serialize(json_decode(stream_get_contents(STDIN), true, 512, JSON_THROW_ON_ERROR));",
        data=json.dumps(checksums).encode(),
    )

    installer = (source / "install.php").read_bytes()
    readme = (source / "data_custom/builds/readme.txt").read_bytes()
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        temporary = Path(directory)
        result = temporary / "release"
        result.mkdir()
        data_path = temporary / "data.cms"
        quick = quick_installer(files, data_path, installer)
        write_zip(result / f"composr_quick_installer-{version}.zip",
                  {"data.cms": data_path, "install.php": quick, "readme.txt": readme})
        manual = {**files, "install.php": installer}
        write_zip(result / f"composr_manualextraction_installer-{version}.zip", manual)
        with (result / f"composr-{version}.tar.gz").open("wb") as target:
            with gzip.GzipFile(filename="", fileobj=target, mode="wb", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.USTAR_FORMAT) as archive:
                    write_tar(archive, {**manual, "readme.txt": readme,
                                        "install.sql": (source / "install.sql").read_bytes(),
                                        "_config.php.template": (source / "_config.php.template").read_bytes()})
        with tarfile.open(result / f"composr_upgrader-{version}.cms", "w", format=tarfile.USTAR_FORMAT) as archive:
            write_tar(archive, files)
        (result / f"catalogue-enforcement-{version}.sha256").write_text(
            render_checksums({name: hashlib.sha256(files[name]).hexdigest() for name in GUARDED_FILES}),
            encoding="ascii",
        )
        sums = []
        for path in sorted(result.iterdir()):
            with path.open("rb") as stream:
                sums.append(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {path.name}\n")
        (result / "SHA256SUMS").write_text("".join(sums), encoding="ascii")
        result.rename(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    build(args.source_dir.resolve(), args.output_dir.resolve(), args.version)
