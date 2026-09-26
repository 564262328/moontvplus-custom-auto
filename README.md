# MoonTVPlus Custom Auto Update V1

This repository contains only the custom UI layer and update automation. It does not vendor the MoonTVPlus source tree.

## GitHub Actions pipeline

Every 6 hours the workflow checks `mtvpls/MoonTVPlus:main`, applies the custom UI patch, builds an amd64 Docker image, starts it for an HTTP smoke test, and only then publishes:

- `ghcr.io/<owner>/moontvplus-custom:stable`
- `ghcr.io/<owner>/moontvplus-custom:<upstream-version>-ui1.7.1`
- `ghcr.io/<owner>/moontvplus-custom:upstream-<commit>-ui1.7.1`

If the patch no longer applies cleanly, or the build/smoke test fails, `stable` is not moved.

## Upstream compatibility strategy

The large visual CSS layer is stored separately in `custom/custom-ui-v1.7.1.css`
and appended after the structural patch applies. VideoCard visual hooks are
added by `scripts/apply-videocard-customization.py` using exact semantic class
matches. This avoids tying those two high-churn files to old line numbers while
still failing safely if upstream changes the expected structure.

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

## Kvrocks key-count note

Kvrocks does not continuously maintain the value returned by plain `DBSIZE`.
The updater therefore runs `DBSIZE SCAN`, waits for
`last_dbsize_scan_timestamp` to advance, and only then records/compares the
exact key count. A plain `DBSIZE` can report `0` even when `SCAN` returns
real MoonTV keys if no DB-size scan has been run yet.

## Resilient NAS image pull

The NAS updater first tries a normal `docker pull`. If GHCR/CDN transport fails
(for example with `unexpected EOF` or `connection reset by peer`), it falls
back to Skopeo with a single parallel copy and retry/resume behavior, importing
the completed image into the local Docker daemon. Compose then recreates only
`moontv-core` with `--pull never`, so a successful local import is not
followed by another network pull.

Default fallback settings are:

- `SKOPEO_IMAGE=quay.io/skopeo/stable:latest`
- `SKOPEO_RETRY_TIMES=10`
- `SKOPEO_RETRY_DELAY=10s`
- `SKOPEO_PARALLEL_COPIES=1`

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

## Rollback behavior

If the new MoonTV image fails the local HTTP health check, rollback now happens in stages:

1. Switch `moontv-core` back to the previous image first, leaving Kvrocks untouched.
2. If the previous image becomes healthy, stop there and pause automatic updates for review.
3. If the previous image is still unhealthy, automatic updates are paused and MoonTV core is stopped for manual review. Production Kvrocks is left untouched by default.
4. Automatic production Kvrocks restore only runs when `KVROCKS_AUTO_RESTORE=1` has been explicitly configured.
5. Even in that opt-in mode, the exact pre-update checkpoint must pass isolated restore validation before production restore is attempted.
6. Regardless of whether application-only rollback or an explicitly enabled full rollback succeeds, automatic updates remain paused after a failed upgrade so the event can be reviewed.

The default is `KVROCKS_AUTO_RESTORE=0`. The guarded production restore helper also refuses to run unless it is given the explicit `--confirm-production-restore` flag.

## Data layout

Production Kvrocks currently reports:

- live DB: `/var/lib/kvrocks/db`
- checkpoint directory: `/var/lib/kvrocks/backup`

The checkpoint is copied to a separate NAS directory so recovery does not depend on the container's internal backup location.

## Upstream

Upstream: https://github.com/mtvpls/MoonTVPlus

Preserve applicable upstream copyright and license notices in redistributed derivative builds.
