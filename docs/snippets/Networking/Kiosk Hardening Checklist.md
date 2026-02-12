# Kiosk Hardening Checklist

## (Lubuntu 20.04 + Chromium)

> **Goal:** Auto-boot into full-screen Chromium hitting `http://192.168.1.10/`, no obvious way out, no VT switching, no screen blanking.  
> Repeat on each **Laptop B**.
> 
> These kiosks "should not be" available/accessible to the public or anyone outside the organization, even auditors as "there's no 'there' there". All the data lives on the server and archives. We just don't want staff finding some crazy-smart hacker method of playing "Candy Crush" in a VT on their workstation through some convoluted, ad-hoc Bluetooth connection to their phone. 
> 
> I know, I know, 'just disable Bluetooth', right? 
> 
> Well, not so fast... Eventually, and because of its limited range, we're hoping to use a Bluetooth connection outside of the application to access/spy on client machines and glean machine health information, (traffic volume, core temp, processor load, baseline stats). I know, it's a pipedream but some of the best ideas start out as a silly little experiment in "Learn to code, Boomer" and turn into a viable, open-source, systems-level software solution for non-profit organization management

---

## 1. Create kiosk user (no admin powers)

```bash
sudo adduser kiosk
# Follow prompts; simple password ok
groups kiosk      # verify: should NOT include 'sudo' or 'adm'
```

Keep your own admin account (e.g. `ken`) in `sudo` for maintenance.

---

## 2. Enable autologin (SDDM → kiosk user)

```bash
sudo mkdir -p /etc/sddm.conf.d
sudo nano /etc/sddm.conf.d/autologin.conf
```

Add:

```ini
[Autologin]
User=kiosk
Session=lxqt.desktop
```

Save, then reboot once to confirm it logs in as `kiosk` automatically.

---

## 3. Wi-Fi to your LAN (VCDB router)

While logged in as `kiosk`:

1. Click network icon → connect to SSID (e.g. `VCDB-LAN`).

2. **Edit Connections… → Wi-Fi → Edit:**
   
   - **General**: “Connect automatically” ✔
   
   - **IPv4**: “Automatic (DHCP)”
   
   - **IPv6**: “Ignore”

Test:

```bash
ping -c 3 192.168.1.10
```

---

## 4. Install Chromium

```bash
sudo apt update
sudo apt install chromium-browser
```

(If it pulls the Snap version, that’s fine.)

---

## 5. Autostart Chromium in kiosk mode

As `kiosk`:

```bash
mkdir -p ~/.config/autostart
nano ~/.config/autostart/kiosk-chromium.desktop
```

Add:

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

Log out / reboot → it should auto-login and immediately launch Chromium fullscreen to your app.

---

## 6. Disable screen blanking

As `kiosk`:

```bash
mkdir -p ~/bin
nano ~/bin/no-blank.sh
```

Add:

```bash
#!/bin/sh
xset s off
xset -dpms
xset s noblank
```

Make executable:

```bash
chmod +x ~/bin/no-blank.sh
```

Autostart it:

```bash
nano ~/.config/autostart/no-blank.desktop
```

Add:

```ini
[Desktop Entry]
Type=Application
Name=NoBlank
Exec=/home/kiosk/bin/no-blank.sh
X-LXQt-Need-Tray=false
```

Now the screen won’t go to sleep on idle.

---

## 7. Block Ctrl+Alt+F1–F7 VT switching

On each kiosk box (any user with sudo):

```bash
sudo mkdir -p /etc/X11/xorg.conf.d
sudo nano /etc/X11/xorg.conf.d/10-kiosk.conf
```

Add:

```ini
Section "ServerFlags"
    Option "DontVTSwitch" "true"
    Option "DontZap" "true"
    Option "DontZoom" "true"
EndSection
```

Save, then:

```bash
sudo reboot
```

After reboot, Ctrl+Alt+F2… won’t pull them out of the kiosk session.

> To undo: `sudo rm /etc/X11/xorg.conf.d/10-kiosk.conf` and reboot.

---

## 8. Optional: Bluetooth policy (for now vs future)

While you’re still building your “future BT health monitor” idea:

- **Now (simple lockdown):**  
  In each kiosk, disable Bluetooth in the panel, or:
  
  ```bash
  sudo systemctl disable --now bluetooth
  ```

- **Later (monitoring project):**  
  Re-enable it and run your own small agent that reports health metrics to Laptop A’s Flask app. That can live under a separate user or service and doesn’t need to touch the kiosk browser session at all.

---

## 9. Quick smoke test after setup

On each **Laptop B**:

1. Power on.

2. Confirm:
   
   - Auto-login as `kiosk`
   
   - Chromium opens fullscreen to your VCDB URL
   
   - Screen does not blank after a while
   
   - Ctrl+Alt+F2 / F3 / F4 **do nothing**

3. Try to “break out” like a bored staffer would. If all they can do is power-cycle the box, you’ve won. 😁

---
