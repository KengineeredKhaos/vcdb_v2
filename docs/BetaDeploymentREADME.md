# VCDB Beta Deployment Packet

This packet is a practical starting point for deploying VCDB v2 on a
Linux host using:

- Apache2
- mod_wsgi in daemon mode
- HTTPS on a closed LAN
- immutable code + venv
- writable state under `/srv/vcdb/var/*`

It is shaped around the deployment canon already established for this
project:

- code at `/srv/vcdb/app`
- virtualenv at `/opt/vcdb/venv`
- writable runtime paths under `/srv/vcdb/var/{db,log,tmp,cache,uploads,backups}`
- Apache/mod_wsgi in daemon mode
- `XDG_CACHE_HOME` and `TMPDIR` pointed at writable runtime paths

## Application Manifest

### Must go to the host

Ship these:

- `app/`
  - all Python packages/modules the app imports
  - all slice code
  - all templates
  - all static assets actually served by the app
  - any JSON/schema/data files the app reads at runtime
- `config.py`
- production `wsgi.py`
- `manage_vcdb.py`
  - not needed by Apache itself
  - but very useful on-host for bootstrap, seed, migrations, smoke checks, and admin CLI work, since it is your Flask CLI wrapper
- dependency definition files
  - whichever you actually use to build the venv on the host: `requirements*.txt`, `pyproject.toml`, lockfile, wheelhouse, etc.
- migration files, **if** you plan to run migrations on the host
  - for example `migrations/` or Alembic assets

### Should live on the host, but outside the app tree

These are **not** part of the code release:

- database file
  - `/srv/vcdb/var/db/...`
- uploads / attachments
  - `/srv/vcdb/var/uploads`
- logs
  - `/srv/vcdb/var/log`
- cache / tmp
  - `/srv/vcdb/var/cache`
  - `/srv/vcdb/var/tmp`
- backups
  - `/srv/vcdb/var/backups`
- env/config secrets
  - `/etc/vcdb/vcdb.env`
- TLS cert/key
  - `/etc/vcdb/tls/...`

That is exactly how your production config is shaped: `VCDB_DB` is a filesystem path, not a repo-local dev DB, and prod validation expects a real secret key from the environment.

### Production bundle baseline:

release/  
  app/  
  config.py  
  manage_vcdb.py  
  wsgi.py  
  requirements-lock.txt   # or equivalent  
  migrations/             # if applicable

### One practical caution

Do **not** strip out:

- templates
- static assets
- governance/policy JSON
- schema files
- any runtime-loaded seed/reference files



**Ship the application source, templates/static, runtime data files, config module, WSGI entrypoint, CLI launcher, and dependency/migration files. Leave behind tests, docs, caches, local DBs, local logs, editor clutter, git metadata, and your local virtualenv.**

## Deployment Packet contents

```text
vcdb_beta_deploy_packet/
├── README.md
├── app/
│   └── wsgi.py
├── config/
│   ├── apache2/
│   │   └── vcdb.conf
│   ├── env/
│   │   └── vcdb.env.example
│   ├── logrotate/
│   │   └── vcdb
│   └── systemd/
│       └── apache2.service.d/
│           └── vcdb.conf
├── scripts/
│   ├── install_host.sh
│   ├── deploy_release.sh
│   ├── rollback_release.sh
│   ├── vcdb-backup
│   ├── vcdb-smoke
│   └── make-selfsigned-cert.sh
└── tls/
    └── README.md
```

### What these files are for

### `config/apache2/vcdb.conf`

Apache virtual host file. This is the primary runtime config. It
redirects HTTP to HTTPS and runs the app via mod_wsgi daemon mode.

### `app/wsgi.py`

Small WSGI bridge into your Flask app factory. This file assumes your
app can be started with:

```python
from app import create_app
application = create_app()
```

If your factory import path differs, adjust only this file.

### `config/env/vcdb.env.example`

Template for environment/config values. Copy this to
`/etc/vcdb/vcdb.env` and fill in the real values.

### `config/systemd/apache2.service.d/vcdb.conf`

Optional Apache systemd drop-in. This is only needed if you want Apache
to inherit an EnvironmentFile. You do **not** need a separate
`vcdb.service` when Apache/mod_wsgi is the runtime.

### `config/logrotate/vcdb`

Log rotation for app-specific Apache/app logs.

### `scripts/install_host.sh`

One-time host preparation script. Installs packages, creates
directories, copies configs, enables modules/site, and restarts Apache.

### `scripts/deploy_release.sh`

Deploys a release tarball into a new release directory and flips the
`current` symlink.

### `scripts/rollback_release.sh`

Points `current` back at a previous release and restarts Apache.

### `scripts/vcdb-backup`

Simple backup script for config, uploads, and SQLite database.

### `scripts/vcdb-smoke`

Basic smoke check after install/update.

### `scripts/make-selfsigned-cert.sh`

Fast local certificate generator for a closed network test environment.
This is expedient, not elegant. For a more durable setup, issue a cert
from your own internal CA and install that CA root on the client
machines.

## Recommended production shape

```text
/etc/vcdb/
    vcdb.env
    apache.env                 # optional if using the systemd drop-in
    tls/
        server.crt
        server.key
        ca.crt                 # optional internal CA root

/srv/vcdb/
    app/
        releases/
            2026-04-15_01/
        current -> /srv/vcdb/app/releases/2026-04-15_01
    var/
        db/
        log/
        tmp/
        cache/
        uploads/
        backups/

/opt/vcdb/
    venv/
```

## Preflight assumptions

1. The host already has a static LAN address or a stable DHCP lease.
2. The router/DNS setup will resolve `vcdb.lan` to that host.
3. Your Flask factory works with production config via environment.
4. Your release artifact already contains the application code.
5. If you use SQLite, the DB will live at
   `/srv/vcdb/var/db/vcdb.sqlite3`.

## First-time host install

1. Copy this packet to the host.

2. Put your release tarball somewhere accessible, for example:
   
   ```bash
   /root/vcdb-release.tar.gz
   ```

3. Review and edit:
   
   - `config/env/vcdb.env.example`
   - `config/apache2/vcdb.conf`
   - `app/wsgi.py`

4. If you do not already have TLS material, generate a quick local cert:
   
   ```bash
   cd /root/vcdb_beta_deploy_packet
   ./scripts/make-selfsigned-cert.sh vcdb.lan
   ```

5. Run the host prep script as root:
   
   ```bash
   cd /root/vcdb_beta_deploy_packet
   sudo ./scripts/install_host.sh
   ```

6. Deploy the application release:
   
   ```bash
   sudo ./scripts/deploy_release.sh /root/vcdb-release.tar.gz 2026-04-15_01
   ```

7. Run smoke checks:
   
   ```bash
   sudo /usr/local/sbin/vcdb-smoke
   ```

## Update procedure

Use releases + symlink flips. Do not edit the live tree in place.

1. Copy new release tarball to the host.

2. Deploy it:
   
   ```bash
   sudo ./scripts/deploy_release.sh /root/vcdb-release.tar.gz 2026-04-20_01
   ```

3. Run smoke checks.

4. If broken, rollback:
   
   ```bash
   sudo ./scripts/rollback_release.sh 2026-04-15_01
   ```

## Rollback procedure

Rollback is simply:

- point `/srv/vcdb/app/current` back at a known-good release
- restart Apache
- run smoke check

## Writable vs read-only rules

### Read-only after deployment

- `/srv/vcdb/app/releases/*`
- `/srv/vcdb/app/current`
- `/opt/vcdb/venv`
- `/etc/apache2/sites-available/vcdb.conf`

### Writable at runtime

- `/srv/vcdb/var/db`
- `/srv/vcdb/var/log`
- `/srv/vcdb/var/tmp`
- `/srv/vcdb/var/cache`
- `/srv/vcdb/var/uploads`
- `/srv/vcdb/var/backups`

## Logging expectations

Primary places to check:

- `/srv/vcdb/var/log/apache-error.log`
- `/srv/vcdb/var/log/apache-access.log`
- `/srv/vcdb/var/log/app.log` if your app writes one
- `journalctl -u apache2`

## Backup expectations

At minimum back up:

- `/srv/vcdb/var/db`
- `/srv/vcdb/var/uploads`
- `/etc/vcdb`

Do not bother backing up:

- `/srv/vcdb/var/tmp`
- `/srv/vcdb/var/cache`

## Immediate smoke-check list after deploy

1. `apachectl configtest`
2. `systemctl status apache2 --no-pager`
3. `journalctl -u apache2 -n 100 --no-pager`
4. `curl -k -I https://vcdb.lan/`
5. Browser test from an operator workstation
6. Login test
7. One read route
8. One write route
9. Confirm DB file timestamps changed if using SQLite
10. Run `vcdb-backup` once and verify output

## Notes you should not overlook

- Under Apache/mod_wsgi, Apache is the service manager. Do not create a
  second long-running app daemon unless you intentionally change the
  architecture.
- Build the venv on the host, or on an identical machine, to avoid
  Python/mod_wsgi mismatch headaches.
- Keep `www-data` away from write access in the code tree.
- On a closed network, HTTPS still matters. Even if traffic never leaves
  the LAN, encrypted operator sessions and passwords are still worth
  protecting.
