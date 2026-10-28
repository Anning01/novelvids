# Database and media storage

[README](../README.en.md) · [中文](storage.md)

Configure storage through environment variables. Use [`.env.example`](../.env.example) as a template for your private `.env` file.

### SQLite and PostgreSQL

Development defaults to SQLite:

```dotenv
DATABASE_URL=sqlite://./data/novelvids.db
```

For PostgreSQL:

```dotenv
DATABASE_URL=postgres://novelvids:your-password@127.0.0.1:5432/novelvids
```

Startup creates missing tables with `safe=True` and runs compatibility initialization. It does not delete existing tables. Back up the database before migrating an existing deployment; changing the URL does not transfer its data.

Project names are unique within a team, or within a creator’s personal scope when no team is assigned. Different scopes can use the same name. Existing global name constraints require an explicitly reviewed migration; see [project name scoping and migration](project-name-scoping.md). The migration defaults to preview and never runs automatically at startup.

### Local media and Alibaba Cloud OSS

Local storage:

```dotenv
MEDIA_PATH=./media
OSS_PROVIDER=local
```

Alibaba Cloud OSS:

```dotenv
OSS_PROVIDER=aliyun
OSS_BUCKET=your-bucket
OSS_ENDPOINT=oss-cn-guangzhou.aliyuncs.com
OSS_INTERNAL_ENDPOINT=oss-cn-guangzhou-internal.aliyuncs.com
OSS_PUBLIC_BASE=https://media.example.com
OSS_ACCESS_KEY_ID=
OSS_ACCESS_KEY_SECRET=
```

- Browsers use signed policies to upload large files directly.
- Server-side processing uses `OSS_INTERNAL_ENDPOINT` for downloads and uploads.
- Models and browser previews receive public or signed URLs; the database retains stable object keys where possible.
- `OSS_PUBLIC_BASE` can point to a CDN or CNAME. If omitted, URLs use the bucket and public endpoint.

Original images are retained alongside thumbnails and previews. To backfill derivatives after upgrading:

```sh
uv run python -m scripts.backfill_media_derivatives
```

The idempotent command creates WebP image derivatives and first-frame posters for historical generated videos. Local derivatives sit beside originals; OSS derivatives use the configured internal endpoint.

### Background video reconciliation

```dotenv
VIDEO_RECONCILE_INTERVAL_SECONDS=30
VIDEO_RECONCILE_BATCH_SIZE=50
```

The backend continues querying queued and running provider tasks after the browser closes, including completion handling, usage recording, last-frame extraction and continuity updates.

## Private enhanced exports

`CHAPTER_EXPORT_PATH` defaults to `./data/chapter-exports`. It must remain outside public `MEDIA_PATH`, with downloads checked against project access. The default Compose data mount already includes it. If customized, persist and back it up separately; do not add a public static-file route.

## Authentication and deployment

The default Compose setup disables login. Public deployments need authentication, team scoping, HTTPS and appropriate proxy settings; see [team deployment](team-auth-deployment.md) (Chinese).

Back up the database and media before updates. Existing project names use team/personal scope; older global uniqueness constraints need an explicitly reviewed migration, not a table reset.
