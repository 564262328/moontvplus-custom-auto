# MoonTVPlus Custom Auto Update V1

This repository contains only the custom UI layer and update automation. It does not vendor the MoonTVPlus source tree.

## GitHub Actions pipeline

Every 6 hours the workflow checks `mtvpls/MoonTVPlus:main`, applies the custom UI patch, builds an amd64 Docker image, starts it for an HTTP smoke test, and only then publishes:

- `ghcr.io/<owner>/moontvplus-custom:stable`
- `ghcr.io/<owner>/moontvplus-custom:<upstream-version>-ui1.7.1`
- `ghcr.io/<owner>/moontvplus-custom:upstream-<commit>-ui1.7.1`

If the patch no longer applies cleanly, or the build/smoke test fails, `stable` is not moved.

## NAS installation

From the repository's `nas` directory:

```sh
./install-nas.sh YOUR_GITHUB_USERNAME
```

Then verify the installation manually:

```sh
/vol2/1000/Docker/moontvplus-custom/auto-update/update-moontv.sh
/vol2/1000/Docker/moontvplus-custom/auto-update/status.sh
```

After validation, enable the daily scheduled check:

```sh
/vol2/1000/Docker/moontvplus-custom/auto-update/enable-auto-update.sh
```

## Kvrocks pre-update protection

When a new `stable` image is actually different from the currently running image, the NAS updater now performs a Kvrocks checkpoint before changing `moontv-core`:

1. Send `BGSAVE` to the production Kvrocks instance.
2. Wait for `bgsave_in_progress:0` and `last_bgsave_status:ok`.
3. Verify the checkpoint contains `CURRENT`.
4. Export `/var/lib/kvrocks/backup` to a timestamped archive under:
   `/vol2/1000/Docker/moontvplus-custom/auto-update/kvrocks-backups`
5. Save SHA-256 and basic metadata.
6. Keep the newest 7 backups by default.
7. Only after backup success does the script recreate `moontv-core`.

If backup creation fails, the MoonTV update is aborted before the production app is changed.

Manual backup:

```sh
/vol2/1000/Docker/moontvplus-custom/auto-update/backup-kvrocks.sh
```

## Non-destructive restore validation

Before automatic database restore is enabled, validate a backup in an isolated temporary Kvrocks volume/container:

```sh
/vol2/1000/Docker/moontvplus-custom/auto-update/test-kvrocks-backup.sh
```

The test verifies the archive checksum, restores it into a temporary Docker volume, starts a temporary Kvrocks container, checks `PING`, and compares `DBSIZE` with the value recorded at backup time. Production Kvrocks is not modified by this test.

## Current rollback behavior

If the new MoonTV image fails the local HTTP health check:

1. The application image is switched back to the previous image.
2. Automatic updates are paused.
3. The exact pre-update Kvrocks backup path is recorded for recovery.
4. Kvrocks is not automatically overwritten yet.

Automatic Kvrocks restore is intentionally deferred until the isolated restore test has been run successfully on the NAS.

## Data layout

Production Kvrocks currently reports:

- live DB: `/var/lib/kvrocks/db`
- checkpoint directory: `/var/lib/kvrocks/backup`

The checkpoint is copied to a separate NAS directory so recovery does not depend on the container's internal backup location.

## Upstream

Upstream: https://github.com/mtvpls/MoonTVPlus

Preserve applicable upstream copyright and license notices in redistributed derivative builds.
