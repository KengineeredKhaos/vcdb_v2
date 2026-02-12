# VCDB Base Hardware

## (architecture & configuration)

Let’s assume this final architecture:

- **Arris NVG510** = local-only router / Wi-Fi AP
  
  - WAN port not used or has no internet, doesn’t matter
  
  - Does **DHCP** on LAN, gives out `192.168.1.x`

- **Laptop A** = Lubuntu 20.04 server
  
  - Ethernet to Arris LAN
  
  - Runs **Apache2 + Flask (via mod_wsgi)**
  
  - Has a **fixed LAN IP** like `192.168.1.10`

- **Laptop B (x4–5)** = Lubuntu kiosk clients
  
  - Wi-Fi to Arris
  
  - Auto-connect to SSID, get DHCP addresses
  
  - Auto-boot into **Chromium in kiosk mode** pointing at `http://192.168.1.10/`

Below is a **checklist**, not a firehose of config. You can work top-down and we can drill into any step later.

---

## 0. Router (Arris NVG510) – one-time checklist

1. **Plug stuff in**
   
   - Laptop A → **Arris LAN port** (not WAN)
   
   - Laptop B’s → connect over Wi-Fi

2. **Log into the Arris web UI** (from any machine on a LAN port or Wi-Fi):
   
   - In a browser: try `http://192.168.1.254` (common AT&T / NVG default)
   
   - Use the admin/password printed on the router (or whatever you set)

3. **LAN & DHCP**
   
   - Note the **router LAN IP** (probably `192.168.1.254`)
   
   - Confirm **DHCP is ON**, giving addresses like `192.168.1.64–192.168.1.253`
   
   - Optional: create a **DHCP reservation** for Laptop A’s MAC address so it always gets e.g. `192.168.1.10`.  
     If that’s fiddly, we’ll just set a static IP on Laptop A.

4. **Wi-Fi**
   
   - Set SSID to something like `VCDB-LAN`
   
   - Set WPA2 password
   
   - Make sure Wi-Fi is enabled on 2.4GHz (for older hardware reliability)

You’re done with the router: it’s just a plain LAN + Wi-Fi, no internet required.

---

## 1. Laptop A (server) – network checklist

Goal: **fixed IP**, always reachable at e.g. `192.168.1.10`.

### 1.1 Decide IP

Let’s use:

- **Laptop A IP**: `192.168.1.10`

- **Netmask**: `255.255.255.0`

- **Gateway**: `192.168.1.254` (router)

- **DNS**: `192.168.1.254` or `1.1.1.1` (doesn’t matter much on a no-internet LAN)

### 1.2 Set static IP via GUI (NetworkManager)

On Laptop A:

1. Right-click **network icon** in panel → **Edit Connections…**

2. Under **Wired**, select your ethernet connection (e.g. “Wired connection 1”) → **Edit**.

3. **IPv4 Settings** tab:
   
   - Method: **Manual**
   
   - Addresses:
     
     - Address: `192.168.1.10`
     
     - Netmask: `255.255.255.0`
     
     - Gateway: `192.168.1.254`
   
   - DNS: `192.168.1.254` (or `1.1.1.1`)

4. **IPv6** tab: Method **Ignore** (keep life simple)

5. Save, close, then disconnect/reconnect that wired connection.

Sanity check in a terminal:

```bash
ip addr show
ping -c 3 192.168.1.254    # should ping the router
```

---

## 2. Laptop A – Apache + Flask hosting checklist

We’ll use **Apache + mod_wsgi** so Apache manages the app; no extra systemd service needed for Flask.

### 2.1 Install packages

On Laptop A:

```bash
sudo apt update
sudo apt install apache2 libapache2-mod-wsgi-py3 python3-venv
```

### 2.2 Service basics (systemctl commands)

Apache’s systemd unit is already set up when installed.

- Enable at boot:
  
  ```bash
  sudo systemctl enable apache2
  ```

- Start now:
  
  ```bash
  sudo systemctl start apache2
  ```

- Restart after config changes:
  
  ```bash
  sudo systemctl restart apache2
  ```

- Check status:
  
  ```bash
  sudo systemctl status apache2
  ```

- View logs:
  
  ```bash
  sudo journalctl -u apache2
  ```

### 2.3 Confirm it's listening on the LAN

On Laptop A:

```bash
sudo ss -tlnp | grep :80
```

You want to see something like `LISTEN 0.0.0.0:80 ... apache2`.

From **any Laptop B later**, you should be able to open `http://192.168.1.10/` and see the Apache default page.

---

## 3. Laptop A – Flask + mod_wsgi skeleton checklist

(High level; we can fill details when you’re ready.)

1. **Create an app directory**, e.g.:
   
   ```bash
   sudo mkdir -p /var/www/vcdb
   sudo chown "$USER":"$USER" /var/www/vcdb
   cd /var/www/vcdb
   ```

2. **Python venv & Flask**
   
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install flask
   # pip install your-app if it’s in a package
   ```

3. **Minimal app for testing** (e.g. `app.py`):
   
   ```python
   from flask import Flask
   app = Flask(__name__)
   
   @app.route("/")
   def index():
      return "Hello from VCDB server"
   ```

4. **WSGI entry point** `vcdb.wsgi`:
   
   ```python
   import sys
   from pathlib import Path
   
   # Ensure app path & venv site-packages are on sys.path
   base = Path(__file__).resolve().parent
   venv_site = base / "venv" / "lib" / "python3.8" / "site-packages"
   sys.path.insert(0, str(base))
   sys.path.insert(0, str(venv_site))
   
   from app import app as application
   ```
   
   (We can tweak Python version / paths later, this is just schematic.)

5. **Apache site config** `/etc/apache2/sites-available/vcdb.conf`:
   
   ```apache
   <VirtualHost *:80>
      ServerName 192.168.1.10
   
      DocumentRoot /var/www/vcdb
   
      WSGIDaemonProcess vcdb python-home=/var/www/vcdb/venv python-path=/var/www/vcdb
      WSGIProcessGroup vcdb
      WSGIScriptAlias / /var/www/vcdb/vcdb.wsgi
   
      <Directory /var/www/vcdb>
          Require all granted
      </Directory>
   
      ErrorLog ${APACHE_LOG_DIR}/vcdb-error.log
      CustomLog ${APACHE_LOG_DIR}/vcdb-access.log combined
   </VirtualHost>
   ```

6. **Enable site & restart Apache**
   
   ```bash
   sudo a2ensite vcdb.conf
   sudo systemctl reload apache2
   ```

Test from Laptop A: `http://192.168.1.10/`  
Later test from a B unit once its network is set up.

---

## 4. Laptop B – network & browser checklist

Repeat this on each B unit.

### 4.1 Network (Wi-Fi)

1. Click network icon → **Wi-Fi**.

2. Connect to **SSID** (e.g. `VCDB-LAN`) → enter WPA2 password.

3. In **Edit Connections… → Wi-Fi → Edit**:
   
   - **General** tab: check **“Connect automatically”**.
   
   - **IPv4 Settings**: Method **Automatic (DHCP)**.
   
   - **IPv6**: Method **Ignore**.

4. Save, reconnect.

Check:

```bash
ip addr
ping -c 3 192.168.1.10   # ping the server
```

Then open **Firefox/Chromium** manually and browse to:

```text
http://192.168.1.10/
```

Once that works on one B, the same config will work on all 4–5.

---

## 5. Laptop B – kiosk mode checklist (Chromium)

We’ll create:

- A **dedicated kiosk user**

- Autologin to that user

- An **autostart entry** that launches Chromium in kiosk mode to `http://192.168.1.10/`

- Optional: stop screen blanking

### 5.1 Create kiosk user

On each B:

```bash
sudo adduser kiosk
# follow prompts, simple password is fine (device rarely touched)
```

### 5.2 Enable autologin to kiosk (SDDM)

On Lubuntu 20.04 (SDDM):

```bash
sudo mkdir -p /etc/sddm.conf.d
sudo nano /etc/sddm.conf.d/autologin.conf
```

Put:

```ini
[Autologin]
User=kiosk
Session=lxqt.desktop
```

Save, reboot once to verify it auto-logs into `kiosk`.

### 5.3 Install Chromium

```bash
sudo apt install chromium-browser
```

(If Ubuntu whines about Snap—no worries, the command still works, it just installs via Snap under the hood.)

### 5.4 Autostart Chromium in kiosk

Log in as **kiosk** (autologin should handle this now), then:

```bash
mkdir -p ~/.config/autostart
nano ~/.config/autostart/kiosk-chromium.desktop
```

Contents:

```ini
[Desktop Entry]
Type=Application
Name=Kiosk Chromium
Exec=chromium-browser --kiosk --incognito \
  --noerrdialogs --disable-infobars \
  --check-for-update-interval=31536000 \
  http://192.168.1.10/
X-LXQt-Need-Tray=false
```

Save.

Log out/log in (or reboot) and it should:

- auto-login as `kiosk`

- auto-launch Chromium full-screen to your Flask app

### 5.5 Stop screen blanking (optional but nice)

Create a small script:

```bash
mkdir -p ~/bin
nano ~/bin/no-blank.sh
```

Contents:

```bash
#!/bin/sh
# Disable DPMS and screen blanking
xset s off
xset -dpms
xset s noblank
```

Make it executable:

```bash
chmod +x ~/bin/no-blank.sh
```

Create another autostart entry:

```bash
nano ~/.config/autostart/no-blank.desktop
```

Contents:

```ini
[Desktop Entry]
Type=Application
Name=NoBlank
Exec=/home/kiosk/bin/no-blank.sh
X-LXQt-Need-Tray=false
```

Now on startup:

- Screen won’t blank

- Chromium runs full-screen to your app

---

## 6. Quick end-to-end smoke test checklist

1. **Router** powered on, Laptop A on Ethernet, B’s on Wi-Fi.

2. From Laptop A:
   
   ```bash
   ping -c 3 192.168.1.254    # router
   ```

3. From one Laptop B:
   
   ```bash
   ping -c 3 192.168.1.10     # server
   ```

4. Open `http://192.168.1.10/` in browser on B → see Flask app via Apache.

5. Reboot a B unit → confirm:
   
   - It auto-logs into kiosk user
   
   - Chromium auto-starts to `http://192.168.1.10/`
   
   - You can’t easily get to a normal desktop without Ctrl+Alt+Fx or SSH (lockdown-ish).

---

If you’d like, next pass we can **zoom into just one slice** of this (for example: “make me a concrete Apache site config and WSGI file for my current Flask project layout”) so you don’t have to do any guessing or heavy typing.
