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
  --version 10.0.52-ext.1-alpha.1
```

The output contains the stock-style quick ZIP, manual extraction ZIP, bundled
TAR.GZ, full upgrader CMS TAR, and SHA256SUMS. The version argument labels the
artifacts. It does not change Composr's database version. Review the output and
exercise installation and upgrades before publication. On cms.tfo.net, build
outside the document root and publish the verified files to the mirror's release
download directory. Keep the build invocation outside the web process.

The **Composr v10 installer packages** workflow takes a reviewed Core commit.
Configure the Hub secret `COMPOSR_CORE_READ_TOKEN` with Core contents read access
if Core is private. To enable the optional draft release step, configure
`COMPOSR_CORE_RELEASE_TOKEN` with Core contents write access. The workflow always
uploads artifacts to the run. Publishing to a public release or exposing mirror
links is a separate operator action after review.
