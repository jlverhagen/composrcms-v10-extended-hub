# ComposrCMS v10 Extended Hub (Unofficial)

Repository: `jlverhagen/composrcms-v10-extended-hub`.

Deploy a minimal ComposrCMS v10 site for human-readable downloads and documentation. Serve versioned catalogue JSON and addon packages as static files. `publisher/build_catalogue.py` is an offline **unsigned** prototype; it is not a production release pipeline.

The old `composr_homesite` branch may be used for studying addon build/publish behavior, but do not copy the entire website or unreviewed assets.

For component and operator tests, place a checkout of the matching Core revision at `cms/` in this checkout or symlink `cms` to it. The scripts and test fixtures use the `hub/` layout inherited from the integration checkpoint. Keep local checkout links and deployment configuration out of commits.

## Build Composr installer packages

Run the same CLI on the mirror publishing host and in GitHub Actions. It takes a
clean, reviewed Core checkout with the stock v10 file manifest and bundled SQL.
It excludes APS and Mobiquo from the packages even when the checkout retains
those directories. The inventory includes the Extended catalogue module,
helper code and its template.

```sh
python3 hub/publisher/build_composr_installers.py \
  --source-dir /path/to/core --output-dir /path/to/new-release-directory \
  --version 2026.11.1-alpha.1
```

The output contains the stock-style quick ZIP, manual extraction ZIP, bundled
TAR.GZ, full upgrader CMS TAR, catalogue enforcement checksums, and SHA256SUMS.
The version argument labels the artifacts and stamps the installed Extended
version. The stock CMS compatibility and database version remain at 10.0.52.
Use YYYY.MM.N with an optional -alpha.N, -beta.N, or -rc.N suffix. Review the output and
exercise installation and upgrades before publication. On cms.tfo.net, build
outside the document root and publish the verified files to the mirror's release
download directory. Keep the build invocation outside the web process.

The **Composr v10 installer packages** workflow takes a reviewed Core commit.
Configure the Hub secret `COMPOSR_CORE_READ_TOKEN` with Core contents read access
if Core is private. To enable the optional draft release step, configure
`COMPOSR_CORE_RELEASE_TOKEN` with Core contents write access. The workflow always
uploads artifacts to the run. Publishing to a public release or exposing mirror
links is a separate operator action after review.


### Upgrading a site with the catalogue enforcement guard

Keep the site-specific catalogue configuration in the host-managed guard outside
the document root. For a site that still defines it in the catalogue module,
move the setting to the guard before applying the release.

Before upgrading, take a filesystem and database backup and save a copy of the
active enforcement manifest with it. Put the site into maintenance and verify
the full CMS archive against the SHA-256 obtained from your trusted release
source. Stage the verified package in a root-controlled directory. Apply the
CMS via the normal upgrader. Before reopening the site, run this on the guarded
host as root and substitute the site paths and verified package digest.

```sh
python3 hub/publisher/catalogue_enforcement.py \
  --site-root /path/to/document-root \
  --manifest /path/to/private/enforcement.sha256 \
  --package /path/to/verified/composr_upgrader-2026.11.1-alpha.2.cms \
  --sha256 "$VERIFIED_CMS_SHA256"
```

The command checks the package digest and independently derives the guarded file
hashes from the package. It replaces the active manifest atomically after all
seven installed files match. The separately published checksum file can be used
to inspect the expected file hashes. After an interrupted upgrade, complete the
file upgrade and rerun the command, or restore the filesystem, database and
manifest from the same backup. Verify Admin Zone access and the signed catalogue
before reopening the site. Sites without the host-managed guard can use the
normal installer or upgrader on its own.
