# Kiosk Health Monitor

This idea —“short-range health tap” is a neat mental model for spotting client machine problems before hardwaare failure at a critical moment in operation. It incorporates an architecture that:

- **Doesn’t poke holes in the kiosk shell**

- **Doesn’t depend on Bluetooth at first**

- Lets you **bolt Bluetooth on later** as just another “transport”

---

## Big Picture

On each **kiosk (Laptop B)** you run a tiny **health agent** that:

1. Collects metrics (CPU, temp, RAM, disk, network, maybe a heartbeat ID).

2. Sends them **outbound only** to a trusted collector:
   
   - **Phase 1:** over your existing LAN (HTTP → Flask on Laptop A).
   
   - **Phase 2:** over Bluetooth when you’re nearby.

Critically:

- The agent **never accepts commands**.

- Chromium kiosk session never knows this exists—it’s just a background service.

---

## Phase 0 – Decide what you want to measure

Keep it boring and structured:

- **Identity**
  
  - `hostname`
  
  - `kiosk_id` (small string you assign, like `kiosk-01`)

- **Health**
  
  - `uptime_seconds`
  
  - `cpu_percent`
  
  - `load_avg_1m` / `5m`
  
  - `memory_used_pct`
  
  - `disk_used_pct` (on `/`)
  
  - `core_temp_c` (if available)

- **Network**
  
  - `rx_bytes` / `tx_bytes` on the Wi-Fi interface

- **Meta**
  
  - `timestamp_utc`
  
  - `agent_version`

JSON example:

```json
{
  "kiosk_id": "kiosk-01",
  "hostname": "vcdb-kiosk-01",
  "timestamp_utc": "2025-11-20T07:15:00Z",
  "uptime_seconds": 123456,
  "cpu_percent": 14.2,
  "load_avg_1m": 0.32,
  "memory_used_pct": 47.8,
  "disk_used_pct": 61.0,
  "core_temp_c": 52.3,
  "wifi_rx_bytes": 12345678,
  "wifi_tx_bytes": 9876543,
  "agent_version": "0.1.0"
}
```

One JSON blob per sample. That’s it.

---

## Phase 1 – LAN-based health agent (no Bluetooth yet)

### 1. Service layout on each kiosk

On **Laptop B** you’ll eventually have:

- A Python script: `health_agent.py`
  
  - Runs every N seconds (e.g. 30 or 60)
  
  - Gathers metrics (via `/proc` or `psutil`)
  
  - Sends a POST request with JSON to Laptop A

- A **systemd service**: `kiosk-health-agent.service`
  
  - Runs under a non-privileged user (e.g. `metrics` or even `kiosk` if you want)
  
  - Starts at boot
  
  - Restarts on failure

Conceptually:

```text
+-----------------------+
| kiosk (Laptop B)      |
|                       |
|  [health_agent.py]    | -> POST /api/health  (JSON)
|    (systemd service)  |
+-----------------------+
              |
              |   existing LAN (through Arris Wi-Fi)
              v
+-----------------------+
| Laptop A (server)     |
|  Apache + Flask       |
|  /api/health endpoint |
+-----------------------+
```

### 2. Server side (Laptop A)

In your existing Flask app on Laptop A:

- Add an endpoint like:
  
  - `POST /api/health` → accepts JSON, validates, stores in DB or a log.

On the Apache side, this is just another route in the same WSGI app you already planned.

This alone gets you:

- Centralized view of kiosk health.

- No Bluetooth yet.

- Everything over the LAN you already built.

**Bonus:** it’s easy to test with curl before you ever touch Bluetooth.

---

## Phase 2 – Add Bluetooth as a second “transport”

Once the LAN version works and you like the data, you can “switch on” Bluetooth as a **second path** without changing what the agent measures.

There are multiple ways to use BT; I’d suggest:

### Option A (simpler conceptually): Bluetooth SPP (serial port profile)

Think of it as “a serial cable over Bluetooth”.

- **Laptop A**:
  
  - Runs a BT SPP server (e.g. Python script using BlueZ bindings).
  
  - Listens for incoming connections.
  
  - When a kiosk connects, it reads JSON lines and pushes them into the same Flask/DB pipeline.

- **Each kiosk**:
  
  - Same `health_agent.py`, but with an extra mode:
    
    - If BT is connected, **send sample over BT** (JSON line over the RFCOMM socket).
    
    - Optionally also keep sending over LAN; or BT can be “diagnostic mode only”.

Data flow:

```text
kiosk health_agent.py
   ├─ send over HTTP to 192.168.1.10 (LAN)
   └─ when told/able, also send JSON over Bluetooth ↦ Laptop A BT daemon
```

This gives you **short-range “tap”** capability without depending on the LAN being perfect.

### Option B: Bluetooth LE “advertisements” (more advanced)

- Each kiosk periodically **broadcasts a small status packet** (e.g. CPU %, health OK/NOT).

- A scanner (Laptop A or even your phone with a small app) listens for those beacons.

Pros:

- Totally one-way, no connections.

- Very low power, “spy from the hallway” style.

Cons:

- Much more fiddly to implement.

- Limited payload (you don’t get full JSON, more like a small custom packet).

I’d park BLE beacons as a **future experiment**, not the first iteration.

---

## Isolation / Safety Rules (so kiosks stay “dumb terminals”)

Some important principles so Bluetooth doesn’t become a back door:

1. **Outbound only logic**
   
   - The kiosk agent never listens on a network port.
   
   - For Bluetooth SPP: kiosk acts as **client** connecting out to server’s BT address.
   
   - No “remote shell” or commands, just `send_status()`.

2. **Separate user**
   
   - Run the agent under a dedicated user (e.g. `metrics`) with:
     
     - No sudo
     
     - No direct access to kiosk app data
   
   - It only needs read access to `/proc` and maybe sensors.

3. **Small, dumb message format**
   
   - Fixed JSON schema (like the one above).
   
   - Validator on the server side so malformed data gets dropped.

4. **You control pairing**
   
   - Only pair kiosks’ Bluetooth with **Laptop A** (or your admin machine).
   
   - Turn off BT discoverability once pairing is done.

5. **Independent of Chromium**
   
   - Agent is a systemd service.
   
   - Chromium kiosk is just a session app.
   
   - If Chromium crashes, the agent keeps running; if the agent dies, kiosk still works.

---

## Phase 3 – Implementation roadmap (rough)

In order I’d tackle it:

1. **Implement & test the metrics collection script** on one kiosk:
   
   - No network yet; just print JSON to stdout or write to `/var/log/kiosk_health.log`.

2. Wrap it in a **systemd service** so it runs at boot.

3. Add **HTTP POST to Laptop A**:
   
   - Add `/api/health` in Flask.
   
   - Have the agent POST every 30–60 seconds.
   
   - Confirm you see data on the server.

4. Roll that out to all kiosks.

5. Only then start playing with **Bluetooth**:
   
   - Get plain BT working between one kiosk and Laptop A (pairing).
   
   - Write a tiny “hello world” SPP pair: send `"hello\n"` over BT, see it arrive.
   
   - Replace `"hello\n"` with your JSON blobs.

At that point, Bluetooth is just a **second link** carrying the same messages the HTTP path already uses. If BT experiments get messy, you still have a solid LAN-based health system.

---

## Implementation Plan:

1. A **v1 JSON “contract”** for the health agent

2. A **small DB table layout** on Laptop A that matches it

You can paste this into your docs and treat it as the spec.

---

## 1. Health Agent JSON Contract (v1)

This is what each kiosk sends once per interval (e.g. every 60s) to your server.

```jsonc
{
  "schema_version": "health.v1",

  "kiosk_id": "kiosk-01",              // your label for this station
  "hostname": "vcdb-kiosk-01",         // OS hostname

  "timestamp_utc": "2025-11-20T07:15:00Z", // ISO-8601, UTC

  "uptime_s": 123456,                  // seconds since boot

  "cpu_percent": 14.2,                 // whole system CPU %
  "load_avg_1m": 0.32,                 // 1-minute load average
  "load_avg_5m": 0.28,                 // 5-minute load average

  "mem_used_pct": 47.8,                // RAM used %

  "disk_root_used_pct": 61.0,          // % used on "/"

  "cpu_temp_c": 52.3,                  // CPU temp in °C (null if unavailable)

  "net_iface": "wlp3s0",               // primary network interface name
  "net_rx_bytes": 12345678,            // bytes received on that interface
  "net_tx_bytes": 9876543,             // bytes sent on that interface

  "agent_version": "0.1.0",            // your agent code version
  "sample_interval_s": 60              // intended interval in seconds
}
```

**Notes / rules:**

- `schema_version` = `"health.v1"`
  
  - Lets you change things later as `health.v2` etc.

- `kiosk_id` = short human-friendly label you assign (e.g. in a config file).

- `hostname` = from the OS (`socket.gethostname()`).

- `timestamp_utc` must be UTC, ISO-8601, with `Z` suffix.

- `cpu_temp_c` can be `null` if the kiosk can’t read temps.

- `net_iface` is whichever interface you care about (on kiosks, the Wi-Fi).

That’s it. No nesting, nice and flat, easy to log and query.

---

## 2. DB Table Layout on Laptop A

Let’s call the table **`kiosk_health_sample`**.

You can implement this as:

- **SQLite** table (simple), or

- SQLAlchemy model matching this schema.

### 2.1 Columns

| Column name          | Type       | Notes                                         |
| -------------------- | ---------- | --------------------------------------------- |
| `id`                 | INTEGER PK | Autoincrement sample ID                       |
| `kiosk_id`           | TEXT       | From JSON                                     |
| `hostname`           | TEXT       | From JSON                                     |
| `ts_utc`             | TEXT       | ISO-8601 timestamp from JSON                  |
| `uptime_s`           | INTEGER    | From JSON                                     |
| `cpu_percent`        | REAL       | From JSON                                     |
| `load_avg_1m`        | REAL       | From JSON                                     |
| `load_avg_5m`        | REAL       | From JSON                                     |
| `mem_used_pct`       | REAL       | From JSON                                     |
| `disk_root_used_pct` | REAL       | From JSON                                     |
| `cpu_temp_c`         | REAL       | From JSON (nullable)                          |
| `net_iface`          | TEXT       | From JSON                                     |
| `net_rx_bytes`       | INTEGER    | From JSON                                     |
| `net_tx_bytes`       | INTEGER    | From JSON                                     |
| `agent_version`      | TEXT       | From JSON                                     |
| `sample_interval_s`  | INTEGER    | From JSON                                     |
| `raw_payload`        | TEXT       | Entire original JSON as text (for future use) |

**Why `raw_payload`?**

- Gives you a safety net: if you add fields later, you still have the full original blob even if you don’t add new columns right away.

### 2.2 Example CREATE TABLE (SQLite)

You don’t **have** to type this now, but this is what it looks like:

```sql
CREATE TABLE kiosk_health_sample (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    kiosk_id            TEXT NOT NULL,
    hostname            TEXT NOT NULL,
    ts_utc              TEXT NOT NULL,

    uptime_s            INTEGER,
    cpu_percent         REAL,
    load_avg_1m         REAL,
    load_avg_5m         REAL,
    mem_used_pct        REAL,
    disk_root_used_pct  REAL,
    cpu_temp_c          REAL,

    net_iface           TEXT,
    net_rx_bytes        INTEGER,
    net_tx_bytes        INTEGER,

    agent_version       TEXT,
    sample_interval_s   INTEGER,

    raw_payload         TEXT
);
```

You can add indexes later if you want (e.g. on `kiosk_id`, `ts_utc`), but not needed for early testing.

---

## 3. Flask Endpoint Contract (server side)

When you get around to wiring this into your Flask app on Laptop A, the contract is:

- **Method:** `POST`

- **Path:** `/api/health`

- **Content-Type:** `application/json`

- **Body:** exactly the JSON structure above.

Server behaviour (what you can implement later):

1. Parse JSON.

2. Validate at least:
   
   - `schema_version == "health.v1"`
   
   - `kiosk_id`, `hostname`, `timestamp_utc` present

3. Insert a row into `kiosk_health_sample` mapping fields 1:1.

4. Store `raw_payload` as the original JSON string.

5. Respond with something simple like:
   
   ```json
   {"ok": true}
   ```

If you stick to this contract, the agent code can be dumb and boring, and your future Bluetooth transport is just a different way of delivering the same JSON.

---


