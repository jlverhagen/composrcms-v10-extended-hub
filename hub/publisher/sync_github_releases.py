"""Mirror complete ComposrCMS Extended releases from GitHub."""

import argparse
import fcntl
import hashlib
import html
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


REPOSITORY = "jlverhagen/composrcms-v10-extended"
API = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=30"
DOWNLOAD_ROOT = f"https://github.com/{REPOSITORY}/releases/download"
VERSION = re.compile(r"[1-9][0-9]{3}\.(?:0[1-9]|1[0-2])\.[1-9][0-9]*(?:-(alpha|beta|rc)\.[1-9][0-9]*)?")
DOWNLOAD_HOSTS = {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
MANIFEST = "SHA256SUMS"


class GitHubRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urlsplit(newurl)
        if url.scheme != "https" or url.netloc not in DOWNLOAD_HOSTS:
            raise ValueError("Unexpected GitHub download redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = build_opener(GitHubRedirects())


def read_url(url):
    return OPENER.open(Request(url, headers={"User-Agent": "ComposrCMS-Extended-Mirror"}), timeout=30)


def release_assets(version):
    return {
        f"composr_quick_installer-{version}.zip": "Quick installer ZIP",
        f"composr_manualextraction_installer-{version}.zip": "Manual installer ZIP",
        f"composr-{version}.tar.gz": "Bundled TAR.GZ",
        f"composr_upgrader-{version}.cms": "Full upgrader CMS",
        f"catalogue-enforcement-{version}.sha256": "Catalogue enforcement checksums",
        MANIFEST: "SHA-256 checksums",
    }


def read_manifest(path, names):
    entries = {}
    for line in path.read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  ([A-Za-z0-9_.-]+)", line)
        if match is None or match[2] in entries:
            raise ValueError("Malformed checksum manifest")
        entries[match[2]] = match[1]
    if entries.keys() != names - {MANIFEST}:
        raise ValueError("Checksum manifest does not list exactly the expected files")
    return entries


def matches(path, asset):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != asset["size"]:
        return False
    with path.open("rb") as file:
        return "sha256:" + hashlib.file_digest(file, "sha256").hexdigest() == asset["digest"]


def download(asset, path):
    remaining = asset["size"]
    with read_url(asset["browser_download_url"]) as response, path.open("xb") as file:
        while chunk := response.read(min(remaining + 1, 1024 * 1024)):
            remaining -= len(chunk)
            if remaining < 0:
                raise ValueError(f"Oversized asset: {path.name}")
            file.write(chunk)
    if not matches(path, asset):
        raise ValueError(f"Asset does not match the GitHub digest: {path.name}")


def sync_release(root, release):
    tag = release["tag_name"]
    version = tag.removeprefix("v")
    expected = release_assets(version)
    assets = {asset["name"]: asset for asset in release["assets"] if asset["state"] == "uploaded"}
    if not expected.keys() <= assets.keys():
        print(f"Skipping {tag}: incomplete asset set", flush=True)
        return False
    for name in expected:
        asset = assets[name]
        max_size = 32768 if name == MANIFEST else 512 * 1024 * 1024
        if (asset["browser_download_url"] != f"{DOWNLOAD_ROOT}/{tag}/{name}"
                or type(asset["size"]) is not int or not 0 < asset["size"] <= max_size
                or not re.fullmatch(r"sha256:[a-f0-9]{64}", asset["digest"] or "")):
            raise ValueError(f"Unexpected GitHub asset metadata: {tag}/{name}")
    target = root / "releases" / version
    if target.is_symlink():
        raise ValueError(f"Release directory is a symbolic link: {target}")
    if target.exists():
        if not all(matches(target / name, assets[name]) for name in expected):
            raise ValueError(f"Existing release differs from GitHub: {version}")
        return True

    with tempfile.TemporaryDirectory(prefix="release-", dir=root.parent) as staging:
        stage = Path(staging) / "assets"
        stage.mkdir(mode=0o755)
        download(assets[MANIFEST], stage / MANIFEST)
        for name, digest in read_manifest(stage / MANIFEST, expected.keys()).items():
            if assets[name]["digest"] != "sha256:" + digest:
                raise ValueError(f"Checksum manifest differs from GitHub: {tag}/{name}")
            download(assets[name], stage / name)
        for path in stage.iterdir():
            path.chmod(0o644)
        stage.chmod(0o755)
        stage.rename(target)
    print(f"Mirrored {version}", flush=True)
    return True


def write_index(root, releases):
    sections = []
    for version in releases:
        heading = html.escape(version)
        links = "".join(
            f'<li><a href="releases/{heading}/{name}">{label}</a></li>'
            for name, label in release_assets(version).items()
        )
        sections.append(f"<h2>{heading}</h2><ul>{links}</ul>")
    page = ("<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
            "<title>GitHub releases</title><h1>ComposrCMS Extended releases</h1>"
            '<p><a href="./">Back to the mirror</a></p>' + "\n".join(sections) + "</html>\n")
    with tempfile.TemporaryDirectory(prefix="index-", dir=root.parent) as staging:
        index = Path(staging) / "github-releases.html"
        index.write_text(page, encoding="utf-8")
        index.chmod(0o644)
        index.replace(root / index.name)


def sync(root):
    with (root.parent / f".{root.name}-github-sync.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with read_url(API) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("GitHub release listing is too large")
        releases = json.loads(data)
        if not isinstance(releases, list):
            raise ValueError("Invalid GitHub release listing")
        versions = []
        for release in releases:
            version = release["tag_name"].removeprefix("v")
            if release["draft"] or not VERSION.fullmatch(version) or version in versions:
                continue
            if sync_release(root, release):
                versions.append(version)
        if not versions:
            raise ValueError("No complete GitHub releases found")
        write_index(root, versions)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mirror_root", type=Path)
    args = parser.parse_args()
    sync(args.mirror_root.resolve(strict=True))
