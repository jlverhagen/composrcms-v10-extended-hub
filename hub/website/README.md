# Hub deployment plan

Run a minimal ComposrCMS v10 installation on the intended subdomain. Use the existing Downloads module for human-facing addon pages. Do not deploy the legacy homesite wholesale. Publish generated static JSON at `/api/v1/addons.json` and immutable packages at `/downloads/`; avoid public writable upload paths for signed metadata. Deployment and domain configuration are not included.
