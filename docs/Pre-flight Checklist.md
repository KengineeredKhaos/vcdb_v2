# Pre-flight Checklist

When you’re on the host, have these ready:

- the release bundle or full project tree

- the tailored deployment packet

- sudo access

- your intended hostname, like `vcdb.lan`

- the TLS cert/key you plan to use, or we can generate a temporary self-signed pair

- a note of where you want the DB and uploads to live

Once you’re there, we can go in a clean order:

1. inspect the host

2. install packages

3. lay out directories

4. copy the app

5. build the venv

6. wire Apache/mod_wsgi

7. set env/config

8. enable HTTPS

9. run bootstrap and smoke checks

When you come back on the server, send me:

- `pwd`

- `python3 --version`

- `apache2 -v`

- `lsb_release -a`

- and `ls` of the folder where you placed the app files

Then we’ll walk it through step by step.
