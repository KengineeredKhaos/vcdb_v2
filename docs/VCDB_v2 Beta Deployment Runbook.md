# VCDB_v2 Beta Deployment Runbook

For this stack, I would keep the deployment boring and predictable:

Use **Apache as the only long-running service**, run the Flask app in a **dedicated mod_wsgi daemon process group**, keep **code and venv read-only**, keep **only `/srv/vcdb/var/*` writable**, and treat `/etc/vcdb/` as the home for environment/config material. That fits the server shape you’ve already been steering toward, and it lines up with how mod_wsgi is meant to be run under Apache. ([modwsgi.readthedocs.io](https://modwsgi.readthedocs.io/en/latest/configuration-directives/WSGIDaemonProcess.html "WSGIDaemonProcess — mod_wsgi 5.0.2 documentation"))

One caution before you lock this in: **Lubuntu 20.04 is long out of support**, and **Ubuntu 20.04 standard support ended in May 2025**. For a new production box, I would strongly prefer **22.04 LTS or 24.04 LTS**. If you must stay on Lubuntu 20, keep it truly closed-network and treat that as a temporary compromise, not the long-term target. ([lubuntu.me](https://lubuntu.me/lubuntu-20-04-lts-end-of-life-and-current-support-statuses/ "Lubuntu 20.04 LTS End of Life and Current Support Statuses – Lubuntu"))

## The server shape I’d deploy

Use this layout on the host:

```text
/etc/vcdb/
    vcdb.env
    apache.env              # optional, only if using a systemd drop-in
    tls/
        server.crt
        server.key
        ca.crt              # if using your own internal CA

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

Permissions goal:

- `/srv/vcdb/app` and `/opt/vcdb/venv` are **read-only after deployment**

- `/srv/vcdb/var/*` is the **only writable area**

- Apache/mod_wsgi runs as `www-data`

- `www-data` should **not** be able to modify the code tree or Apache-served content root; Ubuntu’s Apache guidance explicitly warns against granting write access there. ([Ubuntu](https://ubuntu.com/server/docs/how-to/web-services/use-apache2-modules/ "How to use Apache2 modules - Ubuntu Server documentation"))

## The config files you actually need

These are the files I would prepare on the flash drive.

### 1) Apache vhost

`/etc/apache2/sites-available/vcdb.conf`

This is the main runtime config.

### 2) WSGI entry script

`/srv/vcdb/app/current/wsgi.py`

This is the small bridge from Apache into `create_app()`.

### 3) App environment/config file

`/etc/vcdb/vcdb.env`

This holds secrets and environment-specific settings.

### 4) Optional systemd drop-in for Apache

`/etc/systemd/system/apache2.service.d/vcdb.conf`

This is optional. With Apache/mod_wsgi, you do **not** need a separate `vcdb.service` for the app. The supervised unit is `apache2.service`. A drop-in only makes sense if you want Apache to inherit an `EnvironmentFile=` from systemd. `EnvironmentFile=` is a standard systemd mechanism, and any time you change a unit or drop-in you need `systemctl daemon-reload`. ([FreeDesktop](https://www.freedesktop.org/software/systemd/man/systemd.exec.html?utm_source=chatgpt.com "systemd.exec"))

### 5) Logrotate file

`/etc/logrotate.d/vcdb`

### 6) Backup script

`/usr/local/sbin/vcdb-backup`

### 7) Smoke-check script

`/usr/local/sbin/vcdb-smoke`

## Apache / mod_wsgi process model

For your environment, I would start with **one mod_wsgi daemon process group** and a **small thread count**, not a second Python daemon and not a complicated multi-service topology. mod_wsgi’s docs are explicit that daemon mode creates distinct processes dedicated to the WSGI app, separate from the regular Apache workers, and that you bind the app to that group with `WSGIProcessGroup`. ([modwsgi.readthedocs.io](https://modwsgi.readthedocs.io/en/latest/configuration-directives/WSGIDaemonProcess.html "WSGIDaemonProcess — mod_wsgi 5.0.2 documentation"))

For a small closed LAN with a handful of operator stations, this is a sane starting point:

- one daemon process group

- `threads=5`

- `python-home=/opt/vcdb/venv`

- `python-path=/srv/vcdb/app/current`

- `user=www-data group=www-data`

Also, do **not** assume a virtualenv copied from some other machine will be safe. mod_wsgi requires that the virtual environment use the **same base Python version** it was compiled for. That is the biggest reason I would build the venv on the host, or on a machine that is truly identical. ([modwsgi.readthedocs.io](https://modwsgi.readthedocs.io/en/latest/configuration-directives/WSGIDaemonProcess.html "WSGIDaemonProcess — mod_wsgi 5.0.2 documentation"))

## HTTPS on a closed network

For a stand-alone router / closed LAN, the cleanest answer is usually **your own internal CA** with that CA root installed on the client machines. Apache’s SSL docs note that self-signed certs require extra care, and that running your own CA can make sense inside an intranet where you control the clients. ([Apache HTTP Server](https://httpd.apache.org/docs/current/ssl/ssl_intro.html "SSL/TLS Strong Encryption: An Introduction - Apache HTTP Server Version 2.4"))

Could you use Let’s Encrypt? Maybe, but I would not design around it here. As of January 2026, Let’s Encrypt does offer short-lived IP address certificates, but they are only valid for about **160 hours / just over six days**, and ACME validation still has network requirements. Their integration guide says `http-01` requires inbound port 80 and validation comes from changing IP ranges; that is a poor fit for a private standalone router unless you intentionally engineer public validation into the setup. ([Let's Encrypt](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability "6-day and IP Address Certificates are Generally Available -  Let's Encrypt"))

So my recommendation is:

- use a hostname like `vcdb.lan`

- create an internal CA once

- issue a server cert for `vcdb.lan`

- install the CA root cert on each operator workstation/browser

## Example files

### Apache vhost

`/etc/apache2/sites-available/vcdb.conf`

```apache
<VirtualHost *:80>
    ServerName vcdb.lan
    Redirect permanent / https://vcdb.lan/
</VirtualHost>

<VirtualHost *:443>
    ServerName vcdb.lan

    SSLEngine on
    SSLCertificateFile /etc/vcdb/tls/server.crt
    SSLCertificateKeyFile /etc/vcdb/tls/server.key

    ErrorLog  /srv/vcdb/var/log/apache-error.log
    CustomLog /srv/vcdb/var/log/apache-access.log combined

    WSGIDaemonProcess vcdb \
        user=www-data \
        group=www-data \
        home=/srv/vcdb/app/current \
        python-home=/opt/vcdb/venv \
        python-path=/srv/vcdb/app/current \
        threads=5 \
        lang=en_US.UTF-8 \
        locale=en_US.UTF-8 \
        display-name=%{GROUP}

    WSGIProcessGroup vcdb
    WSGIScriptAlias / /srv/vcdb/app/current/wsgi.py

    <Directory /srv/vcdb/app/current>
        Require all granted
    </Directory>

    # Optional, only if your app has a single stable static root:
    # Alias /static/ /srv/vcdb/app/current/app/static/
    # <Directory /srv/vcdb/app/current/app/static>
    #     Require all granted
    # </Directory>
</VirtualHost>
```

That `lang/locale` bit is worth keeping; mod_wsgi notes many Linux Apache starts come up in the `C` locale unless you set it. ([modwsgi.readthedocs.io](https://modwsgi.readthedocs.io/en/latest/configuration-directives/WSGIDaemonProcess.html "WSGIDaemonProcess — mod_wsgi 5.0.2 documentation"))

### WSGI entry point

`/srv/vcdb/app/current/wsgi.py`

```python
import os
import sys

APP_ROOT = "/srv/vcdb/app/current"
sys.path.insert(0, APP_ROOT)

# Set safe defaults for runtime paths.
os.environ.setdefault("VCDB_ENV_FILE", "/etc/vcdb/vcdb.env")
os.environ.setdefault("XDG_CACHE_HOME", "/srv/vcdb/var/cache")
os.environ.setdefault("TMPDIR", "/srv/vcdb/var/tmp")

from app import create_app

application = create_app()
```

You may need to rename `VCDB_ENV_FILE` to whatever your factory already expects.

### App env file

`/etc/vcdb/vcdb.env`

```dotenv
APP_ENV=production
SECRET_KEY=replace_me
DATABASE_URL=sqlite:////srv/vcdb/var/db/vcdb.sqlite3
UPLOAD_ROOT=/srv/vcdb/var/uploads
LOG_DIR=/srv/vcdb/var/log
CACHE_DIR=/srv/vcdb/var/cache
TMP_DIR=/srv/vcdb/var/tmp
```

### Optional systemd drop-in

`/etc/systemd/system/apache2.service.d/vcdb.conf`

```ini
[Service]
EnvironmentFile=-/etc/vcdb/apache.env
```

And then:

```dotenv
# /etc/vcdb/apache.env
VCDB_ENV_FILE=/etc/vcdb/vcdb.env
XDG_CACHE_HOME=/srv/vcdb/var/cache
TMPDIR=/srv/vcdb/var/tmp
```

I would treat this as optional. It is useful only if you want Apache’s inherited environment centralized outside the WSGI script.

### Logrotate

`/etc/logrotate.d/vcdb`

```conf
/srv/vcdb/var/log/*.log {
    daily
    rotate 14
    missingok
    notifempty
    compress
    delaycompress
    create 0640 root www-data
    sharedscripts
    postrotate
        /usr/sbin/apachectl graceful > /dev/null 2>&1 || true
    endscript
}
```

Using `apachectl graceful` here is appropriate; Apache documents that graceful restart reopens logs without aborting active connections, though old log files may not close immediately. ([Apache HTTP Server](https://httpd.apache.org/docs/current/programs/apachectl.html "apachectl - Apache HTTP Server Control Interface - Apache HTTP Server Version 2.4"))

### Backup script

`/usr/local/sbin/vcdb-backup`

```bash
#!/bin/sh
set -eu

STAMP="$(date +%F-%H%M%S)"
DEST="/srv/vcdb/var/backups/$STAMP"

mkdir -p "$DEST"

# App config
tar -C / -czf "$DEST/etc-vcdb.tgz" etc/vcdb

# Uploads
tar -C /srv/vcdb/var -czf "$DEST/uploads.tgz" uploads

# SQLite example; adapt if you move to a server DB later.
sqlite3 /srv/vcdb/var/db/vcdb.sqlite3 \
  ".backup '$DEST/vcdb.sqlite3'"

# Keep 14 days
find /srv/vcdb/var/backups -mindepth 1 -maxdepth 1 -type d -mtime +14 \
  -exec rm -rf {} +
```

### Smoke-check script

`/usr/local/sbin/vcdb-smoke`

```bash
#!/bin/sh
set -eu

apachectl configtest
systemctl is-active --quiet apache2

test -d /srv/vcdb/var/db
test -d /srv/vcdb/var/log
test -d /srv/vcdb/var/uploads

curl -k -I https://vcdb.lan/ >/dev/null
echo "VCDB smoke check passed."
```

## Flash-drive deployment kit

I would prepare the USB like this:

```text
vcdb-deploy/
    release/
        vcdb-2026-04-15_01.tar.gz
    wheels/
        *.whl
    requirements-lock.txt
    config/
        vcdb.conf
        vcdb.env.example
        apache2-vcdb-override.conf
        logrotate-vcdb
    certs/
        server.crt
        server.key
        ca.crt
    scripts/
        install-host.sh
        vcdb-backup
        vcdb-smoke
```

The important bit is this: copy the **source release** and a **wheelhouse**, but build the virtualenv on the host. That avoids the Python/mod_wsgi version mismatch trap. ([modwsgi.readthedocs.io](https://modwsgi.readthedocs.io/en/latest/configuration-directives/WSGIDaemonProcess.html "WSGIDaemonProcess — mod_wsgi 5.0.2 documentation"))

## Host install procedure

1. Install host packages.

Ubuntu’s current Apache docs show `libapache2-mod-wsgi-py3` for Python WSGI support, and `mod_ssl` is enabled with `a2enmod ssl`. The default self-generated cert from `ssl-cert` is fine for testing, not for your real deployment. ([Ubuntu](https://ubuntu.com/server/docs/how-to/web-services/use-apache2-modules/ "How to use Apache2 modules - Ubuntu Server documentation"))

Example:

```bash
sudo apt update
sudo apt install apache2 libapache2-mod-wsgi-py3 python3-venv python3-pip acl openssl
sudo a2enmod ssl headers wsgi
```

2. Create directories.

```bash
sudo mkdir -p /etc/vcdb/tls
sudo mkdir -p /srv/vcdb/app/releases
sudo mkdir -p /srv/vcdb/var/{db,log,tmp,cache,uploads,backups}
sudo mkdir -p /opt/vcdb
```

3. Set ownership and writable boundaries.

```bash
sudo chown -R root:root /srv/vcdb/app /opt/vcdb /etc/vcdb
sudo chmod -R 755 /srv/vcdb/app /opt/vcdb
sudo chown -R root:www-data /srv/vcdb/var
sudo chmod -R 2770 /srv/vcdb/var
sudo setfacl -R -m u:www-data:rwx /srv/vcdb/var
sudo setfacl -R -m d:u:www-data:rwx /srv/vcdb/var
```

4. Copy release tarball, unpack it into a release directory, and point `current` at it.

```bash
sudo tar -xzf /media/$USER/USB/vcdb-deploy/release/vcdb-2026-04-15_01.tar.gz \
  -C /srv/vcdb/app/releases
sudo ln -sfn /srv/vcdb/app/releases/vcdb-2026-04-15_01 /srv/vcdb/app/current
```

5. Build the venv on the host.

```bash
sudo python3 -m venv /opt/vcdb/venv
sudo /opt/vcdb/venv/bin/pip install --upgrade pip
sudo /opt/vcdb/venv/bin/pip install --no-index \
  --find-links=/media/$USER/USB/vcdb-deploy/wheels \
  -r /media/$USER/USB/vcdb-deploy/requirements-lock.txt
```

6. Copy config files into place.

7. Enable the site and disable the defaults you do not need.

```bash
sudo cp /media/$USER/USB/vcdb-deploy/config/vcdb.conf \
  /etc/apache2/sites-available/vcdb.conf
sudo a2dissite 000-default.conf default-ssl.conf || true
sudo a2ensite vcdb.conf
```

8. If using the Apache systemd drop-in:

```bash
sudo mkdir -p /etc/systemd/system/apache2.service.d
sudo cp /media/$USER/USB/vcdb-deploy/config/apache2-vcdb-override.conf \
  /etc/systemd/system/apache2.service.d/vcdb.conf
sudo systemctl daemon-reload
```

9. Syntax-check Apache config and start.

Apache documents `apachectl configtest` for syntax checking, and `apachectl restart` / `graceful` both run config checks before restarting. ([Apache HTTP Server](https://httpd.apache.org/docs/2.4/configuring.html "Configuration Files - Apache HTTP Server Version 2.4"))

```bash
sudo apachectl configtest
sudo systemctl enable apache2
sudo systemctl restart apache2
```

## Logging location and rotation

I would keep all app-specific logs under:

```text
/srv/vcdb/var/log/
```

Specifically:

- `/srv/vcdb/var/log/apache-access.log`

- `/srv/vcdb/var/log/apache-error.log`

- `/srv/vcdb/var/log/app.log` if your app writes its own file log

Use logrotate for those files. Use `journalctl -u apache2` for boot/startup failures, syntax errors, and mod_wsgi import crashes that happen before your app logger is fully alive.

## Backup expectations

At minimum, back up:

- `/srv/vcdb/var/db/`

- `/srv/vcdb/var/uploads/`

- `/etc/vcdb/`

- the deployed release tarball or Git revision reference

Do **not** waste backup space on:

- `/srv/vcdb/var/tmp`

- `/srv/vcdb/var/cache`

- rotated logs beyond your retention policy

For a small closed-network server, I’d do:

- nightly local backup to `/srv/vcdb/var/backups`

- weekly copy of that backup to a second offline USB drive

- one manual pre-update backup before every deployment

## Restart / update procedure

For updates, do not edit the live tree in place.

Use this pattern instead:

1. copy new release tarball to host

2. unpack to a **new** release directory

3. build/update venv if dependencies changed

4. run smoke import test

5. switch `current` symlink

6. `apachectl configtest`

7. `systemctl restart apache2`

8. run smoke script

9. if bad, point `current` back to previous release and restart Apache

That gives you a crude but effective rollback.

## Bootstrap and smoke checks after deploy

After the first deploy, I would verify these in order:

1. `apachectl configtest`

2. `systemctl status apache2 --no-pager`

3. `journalctl -u apache2 -n 100 --no-pager`

4. `curl -k -I https://vcdb.lan/`

5. open the site from an operator workstation

6. log in

7. perform one write action that touches the DB

8. confirm a log entry appears

9. run one backup and verify the files were created

That proves:

- Apache can load the site

- mod_wsgi can import the app

- TLS is working

- writable paths are correct

- the DB path is usable

- backups are not merely theoretical

The one structural point I’d hold firm on is this:

**Do not create a separate long-running `vcdb.service` for the Flask app when you are already using Apache/mod_wsgi.** Let Apache own the runtime; let your custom files be the **vhost**, **WSGI entry**, **env file**, **logrotate**, **backup**, and optional **apache2 systemd drop-in**. That is the simplest shape with the fewest moving parts. ([modwsgi.readthedocs.io](https://modwsgi.readthedocs.io/en/latest/configuration-directives/WSGIDaemonProcess.html "WSGIDaemonProcess — mod_wsgi 5.0.2 documentation"))

I can turn this into a copy-paste deployment packet next: `vcdb.conf`, `wsgi.py`, `apache2` drop-in, `logrotate`, `backup`, and `smoke` files with your actual app paths and setting names filled in.
