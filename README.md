# MoonTVPlus Custom Auto Update V1

This repository contains only the custom layer and automation. It does **not**
vendor the MoonTVPlus source tree.

## What it does

1. Every 6 hours, GitHub Actions checks `mtvpls/MoonTVPlus:main`.
2. It identifies the exact upstream commit and `VERSION.txt`.
3. It applies `custom/custom-ui-v1.7.1.patch`.
4. If the patch does not apply cleanly, the workflow **fails safely** and
   does not update `stable`.
5. If the patch applies, it builds an amd64 Docker image using
   `Dockerfile.preview`.
6. It starts that image with temporary SQLite storage and runs an HTTP smoke test.
7. Only after the smoke test passes does it publish:
   - `ghcr.io/<owner>/moontvplus-custom:stable`
   - `ghcr.io/<owner>/moontvplus-custom:<upstream-version>-ui1.7.1`
   - `ghcr.io/<owner>/moontvplus-custom:upstream-<commit>-ui1.7.1`

The stable tag therefore moves only after patch + build + smoke test succeed.

## Why upstream is tracked by commit, not GitHub Release

MoonTVPlus currently updates its `main` branch and GHCR image, while its GitHub
Releases page has no published releases. Tracking the exact `main` commit avoids
missing an upstream update that does not correspond to a Release object.

## GitHub setup

1. Create a new GitHub repository, e.g. `moontvplus-custom-auto`.
2. Put the contents of this folder at the **repository root**.
3. Push to `main`.
4. Open **Actions** and manually run:
   `Build custom MoonTVPlus from upstream`.
5. If package publishing is blocked by repository policy, enable workflow
   read/write permission under repository Actions settings.
6. After the first successful build, open the generated GHCR package.
   - Easiest NAS setup: make the package **Public**.
   - If kept private: log in on the NAS with a GitHub PAT that can read packages.

No MoonTV username/password or video-source configuration is stored in GitHub.

## NAS setup

Extract this repository/package on the NAS, then:

```sh
cd nas
./install-nas.sh YOUR_GITHUB_USERNAME
```

If GHCR is private, first authenticate on the NAS:

```sh
docker login ghcr.io
```

Then make one manual controlled upgrade:

```sh
/vol2/1000/Docker/moontvplus-custom/auto-update/update-moontv.sh
```

Verify:

```sh
/vol2/1000/Docker/moontvplus-custom/auto-update/status.sh
```

After the manual test is good, enable daily automatic pulling at 04:23:

```sh
/vol2/1000/Docker/moontvplus-custom/auto-update/enable-auto-update.sh
```

If `crontab` is not available/persistent on your Feiniu version, create an
equivalent daily task in the NAS task scheduler that executes:

```sh
/vol2/1000/Docker/moontvplus-custom/auto-update/update-moontv.sh
```

## Data behavior

The updater recreates **only** `moontv-core` with `--no-deps`.
It does not recreate `moontv-kvrocks`.

Your existing production Kvrocks volume remains the single source of truth for
normal application data. The updater changes the application image, not the
database.

## Failure behavior

If the new stable image does not return HTTP 200/301/302/307/308 within the
health window:

1. The previous running image has already been tagged locally as a rollback image.
2. The updater switches `moontv-core` back to that rollback tag.
3. A `state/PAUSED` file is created.
4. Future automatic update runs stop until you explicitly resume.

After a newer GitHub build succeeds:

```sh
/vol2/1000/Docker/moontvplus-custom/auto-update/resume-auto-update.sh
```

Manual rollback:

```sh
/vol2/1000/Docker/moontvplus-custom/auto-update/rollback-last.sh
```

## Important limitation

The smoke test proves that the app builds and boots. It cannot prove every
upstream feature behaves correctly. A large upstream refactor can still change
runtime behavior. The patch-apply gate and automatic NAS rollback are designed
to keep such failures away from the production data container as much as
practical.

## Upstream and license

Upstream: https://github.com/mtvpls/MoonTVPlus

MoonTVPlus states its project license as MIT. Keep upstream copyright/license
notices when redistributing a derived image.
