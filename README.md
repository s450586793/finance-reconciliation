# Finance Reconciliation

Finance Reconciliation is a public-source Django application for importing invoices and payment records, reconciling transactions, and deploying prebuilt images to DSM.

- Repository: `https://github.com/s450586793/finance-reconciliation`
- DSM deployment: [docs/deployment-dsm.md](docs/deployment-dsm.md)
- Release and upgrade operations: [docs/system-update-runbook.md](docs/system-update-runbook.md)

## Release Images

- Web image: `ghcr.io/s450586793/finance-reconciliation-web`
- Updater image: `ghcr.io/s450586793/finance-reconciliation-updater`
- Canonical release tags use `vX.Y.Z` only.
- Every release tag publishes immutable `web:vX.Y.Z` and `updater:vX.Y.Z`.
- A tag cannot publish until tests, reachable-history scanning, both local image builds, and both image scans pass.
- After both immutable images are published successfully, the workflow promotes only `ghcr.io/s450586793/finance-reconciliation-web:stable`.
- The updater never receives `stable`, `latest`, or any other mutable tag. DSM operators must pin `FINREC_UPDATER_IMAGE_TAG=vX.Y.Z` for updater upgrades.

## Public Source Rules

- Never commit or publish `.env`, production data, attachments, backups, Token values, Cookie values, private keys, account passwords, or DSM credentials.
- Local snapshot creation consumes only an external mode-`0600` anchor file through `FINREC_PUBLIC_SENSITIVE_ANCHORS_FILE` and creates a single parentless `main` commit from the manifest allowlist.
- GitHub Actions receives the base64-encoded anchor inventory only from the repository secret `FINREC_PUBLIC_SCAN_ANCHORS_B64`; an empty or invalid secret fails closed before release.
- Release automation uses the standard GitHub `GITHUB_TOKEN` package permissions only.
- Production runtime values stay on the deployment host and are injected during deployment, not stored in this repository or image metadata.

## DSM Deployment

- DSM deployments pull prebuilt images only; they do not rebuild the project on the NAS.
- Web promotion is handled through the `stable` tag after a full immutable release succeeds.
- Updater rollout is manual and version-pinned through immutable tags so that Web and updater lifecycles stay explicit.
