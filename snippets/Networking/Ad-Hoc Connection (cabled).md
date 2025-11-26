Nice, Lubuntu makes this pretty doable. I’ll assume **both laptops are Lubuntu 20.04.1** and call them:

- **Laptop A** = has working Wi-Fi (this will share the internet)

- **Laptop B** = no Wi-Fi driver, needs internet

We’ll do **the simplest setup first (direct cable)**. Once that works, you can add the Arris in the middle if you want longer cables / more ports.

---

## Phase 1 – Direct cable between laptops

### 1. Hook up the hardware

1. Connect an **Ethernet cable** from **Laptop A → Laptop B**.  
   (Any normal Ethernet cable is fine on modern hardware.)

2. Make sure **Laptop A is online via Wi-Fi** (you can browse the web on it).

We’ll now turn Laptop A into a little router using NetworkManager’s **“Shared to other computers”** option.

---

## Phase 2 – Set up sharing on Laptop A (Wi-Fi → Ethernet)

### 2A. Open the Network Connections editor

On **Laptop A**:

1. Look at the **bottom panel** for the **network icon**  
   (might look like a Wi-Fi indicator or two little arrows).

2. **Right-click** that icon and choose **“Edit Connections…”**  
   If you don’t see that, you can also press:
   
   `Alt+F2`
   
   and run:
   
   `nm-connection-editor`

### 2B. Configure the wired connection to share

In the **Network Connections** window:

1. Click the **“Wired”** tab on the left (or find **“Wired connection 1”** in the list).

2. Select your wired connection (often **“Wired connection 1”**) and click **“Edit”**.

In the edit window:

3. Go to the **IPv4 Settings** tab:
   
   - **Method**: choose **“Shared to other computers”** from the dropdown.
   
   - Leave the address fields empty (they’ll be auto-managed).

4. Go to the **IPv6 Settings** tab:
   
   - Set **Method** to **“Ignore”** (just to keep things simple).

5. Click **“Save”** (or **“OK”**).

Now back in the main window, close it.

### 2C. Make sure the wired connection is actually up

Still on **Laptop A**:

1. Again, click the **network icon** in the panel.

2. In the wired section, make sure **“Wired connection 1”** (or whatever it’s called) is **checked/on**.
   
   - If there is a button like **“Connect”**, click it.

After a few seconds, Lubuntu should:

- Give **Laptop A’s Ethernet** an IP like `10.42.0.1`

- Start a little DHCP + DNS server on Ethernet

- Share the Wi-Fi internet out through Ethernet

---

## Phase 3 – Configure Laptop B (the one without Wi-Fi)

On **Laptop B**:

1. Plug in the Ethernet cable (already connected to Laptop A).

2. Right-click the **network icon** → **“Edit Connections…”**.

3. Select the **Wired connection** → **“Edit”**.

4. Go to **IPv4 Settings**:
   
   - Set **Method** = **“Automatic (DHCP)”**.

5. On **IPv6 Settings**, set **Method** = **“Ignore”** (again, to keep it simple).

6. Save and close.

Then:

7. Click the **network icon** again and ensure the wired connection is **enabled/connected**.

After a few seconds, Laptop B should get an address like `10.42.0.XX`.

---

## Phase 4 – Test that it’s actually working

On **Laptop B**, open a terminal (Menu → System Tools → LXQt Terminal or similar) and type these, one at a time:

`ip addr`

Look for your wired interface (`enp…` or `eth0`). You should see something like:

- `inet 10.42.0.2/24` (or another `10.42.0.x` address)

Now test connectivity:

`ping -c 3 10.42.0.1`

- This should **ping Laptop A**. If that works, the cable and addressing are good.

Then test internet:

`ping -c 3 8.8.8.8`

- If this works, you have internet reachability.

Finally, test DNS:

`ping -c 3 google.com`

- If this works, web browsing should work too.

If the first ping (to `10.42.0.1`) fails, the problem is the **link or the “Shared to other computers” config on Laptop A.**  
If the first ping works but `8.8.8.8` fails, the problem is **NAT/ICS on Laptop A.**  
If `8.8.8.8` works but `google.com` fails, it’s **DNS** (still on Laptop A).
