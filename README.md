# ComposrCMS v10 Extended Hub (Unofficial)

Repository: `jlverhagen/composrcms-v10-extended-hub`.

Deploy a minimal ComposrCMS v10 site for human-readable downloads and documentation. Serve versioned catalogue JSON and addon packages as static files. `publisher/build_catalogue.py` is an offline **unsigned** prototype; it is not a production release pipeline.

The old `composr_homesite` branch may be used for studying addon build/publish behavior, but do not copy the entire website or unreviewed assets.

For component and operator tests, place a checkout of the matching Core revision at `cms/` in this checkout or symlink `cms` to it. The scripts and test fixtures use the `hub/` layout inherited from the integration checkpoint. Keep local checkout links and deployment configuration out of commits.
