# ADB Automation — WhatsApp Sender

A Python-based automation server that sends WhatsApp messages (text, images, video, voice) via real Android devices over ADB and Appium. Exposes a REST API and a CLI, backed by a MariaDB/MySQL job queue.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Installation — Windows](#installation--windows)
4. [Installation — macOS](#installation--macos)
5. [Configuration](#configuration)
6. [Starting Services](#starting-services)
7. [CLI Reference](#cli-reference)
8. [API Reference](#api-reference)
9. [Device Setup (Android)](#device-setup-android)

---

## Architecture Overview

```
Your Code / App
       │
       │ HTTP REST
       ▼
  Flask API Server  ──► Job Queue (MariaDB)
                               │
                         Queue Workers
                               │
                        Appium Server (port 4723)
                               │
                         Android Device (ADB / Wi-Fi)
                               │
                          WhatsApp App
```

- **Flask API** — accepts send jobs and returns a `job_id`
- **Queue workers** — pick up pending jobs and drive the Android device
- **Appium** — UI automation framework; communicates with the device via UIAutomator2
- **MariaDB** — persists devices, jobs, and device leases

---

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.10+ | Runtime |
| Java JDK | 21 | Required by Android SDK tools |
| Node.js | 18 LTS+ | Required by Appium server |
| Android cmdline-tools | Latest | `adb`, `sdkmanager` |
| Appium | 2.x | UI automation server |
| UIAutomator2 driver | Latest | Appium driver for Android |
| FFmpeg | 4.0+ | Voice/audio format conversion |
| MariaDB or MySQL | 10.5+ / 8.0+ | Job queue and device registry |

---

## Installation — Windows

> Run all commands in **Git Bash as Administrator** unless stated otherwise.

### 1 — Automated installer

The repo includes a script that handles steps 2–7 automatically:

```bash
bash install_dependencies.sh
```

Then continue from [step 8 — Python dependencies](#8--python-dependencies-both-platforms).

---

### Manual steps (if the script fails)

### 2 — Java JDK 21

```powershell
winget install --id Microsoft.OpenJDK.21 --exact --silent --accept-package-agreements
```

After install, set the environment variable (replace the path if yours differs):

```powershell
setx JAVA_HOME "C:\Program Files\Microsoft\jdk-21.0.x-hotspot" /M
```

### 3 — Node.js LTS

```powershell
winget install --id OpenJS.NodeJS.LTS --exact --silent --accept-package-agreements
```

Restart Git Bash, then verify:

```bash
node --version   # v20.x.x
npm --version    # 10.x.x
```

### 4 — Android Command-Line Tools

1. Download the Windows zip from:
   `https://developer.android.com/studio#command-line-tools-only`

2. Create the SDK directory and extract:

```bash
mkdir -p "$USERPROFILE/Android/Sdk/cmdline-tools"
unzip commandlinetools-win-*.zip -d "$USERPROFILE/Android/Sdk/cmdline-tools"
mv "$USERPROFILE/Android/Sdk/cmdline-tools/cmdline-tools" \
   "$USERPROFILE/Android/Sdk/cmdline-tools/latest"
```

3. Set environment variables (in PowerShell as Admin):

```powershell
setx ANDROID_HOME "$env:USERPROFILE\Android\Sdk" /M
setx PATH "$env:PATH;$env:USERPROFILE\Android\Sdk\cmdline-tools\latest\bin;$env:USERPROFILE\Android\Sdk\platform-tools" /M
```

4. Install platform-tools (adb) via sdkmanager:

```bash
sdkmanager --sdk_root="$USERPROFILE/Android/Sdk" "platform-tools"
```

Accept all licenses when prompted:

```bash
yes | sdkmanager --licenses
```

Verify:

```bash
adb version
```

### 5 — Appium Server

```bash
npm install -g appium
appium --version   # 2.x.x
```

### 6 — UIAutomator2 Driver

```bash
appium driver install uiautomator2
appium driver list --installed
```

### 7 — FFmpeg

```powershell
winget install --id Gyan.FFmpeg --exact --silent --accept-package-agreements
```

Restart Git Bash, then verify:

```bash
ffmpeg -version
```

### 8 — MariaDB (Windows)

```powershell
winget install --id MariaDB.Server --exact --silent --accept-package-agreements
```

Start the service:

```powershell
net start MariaDB
```

Set a root password if prompted during install, and note it for the `.env` file.

---

## Installation — macOS

### 1 — Homebrew

If not already installed:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 2 — Java JDK 21

```bash
brew install --cask temurin@21
```

Add to your shell profile (`~/.zshrc` or `~/.bash_profile`):

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
```

### 3 — Node.js LTS

```bash
brew install node@20
echo 'export PATH="/opt/homebrew/opt/node@20/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### 4 — Android Command-Line Tools

```bash
brew install --cask android-commandlinetools
```

Add to `~/.zshrc`:

```bash
export ANDROID_HOME="$HOME/Library/Android/sdk"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"
```

Then reload and install platform-tools:

```bash
source ~/.zshrc
yes | sdkmanager --licenses
sdkmanager "platform-tools"
adb version
```

> **Apple Silicon note:** if `sdkmanager` fails, ensure you have the correct JDK architecture (`arch -arm64 sdkmanager ...`).

### 5 — Appium Server

```bash
npm install -g appium
appium --version
```

### 6 — UIAutomator2 Driver

```bash
appium driver install uiautomator2
```

### 7 — FFmpeg

```bash
brew install ffmpeg
ffmpeg -version
```

### 8 — MariaDB (macOS)

```bash
brew install mariadb
brew services start mariadb
```

Secure the installation:

```bash
sudo mariadb-secure-installation
```

---

## 8 — Python Dependencies (both platforms)

```bash
cd adb-automation
pip install -r requirements.txt
```

---

## Configuration

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

`.env` reference:

```env
# ── Database ──────────────────────────────────────────────────────────────────
ADB_AUTOMATION_DB_HOST=localhost        # MariaDB host
ADB_AUTOMATION_DB_PORT=3306            # MariaDB port
ADB_AUTOMATION_DB_USER=root            # MariaDB user
ADB_AUTOMATION_DB_PASSWORD=yourpassword
ADB_AUTOMATION_DB_NAME=adb_automation  # Database name (auto-created)

# ── API Server ────────────────────────────────────────────────────────────────
ADB_AUTOMATION_API_HOST=0.0.0.0        # Bind address (0.0.0.0 = all interfaces)
ADB_AUTOMATION_API_PORT=5000           # Port

# ── Authentication ────────────────────────────────────────────────────────────
ADB_AUTOMATION_API_KEY=your-secret-key # Required — all API requests must include this

# ── Appium ────────────────────────────────────────────────────────────────────
ADB_AUTOMATION_APPIUM_SERVER=http://127.0.0.1:4723   # Appium server URL

# ── Queue ─────────────────────────────────────────────────────────────────────
ADB_AUTOMATION_QUEUE_WORKERS=          # Leave blank to use CPU count
ADB_AUTOMATION_QUEUE_POLL_SECONDS=1    # How often workers poll for new jobs

# ── Device leasing ────────────────────────────────────────────────────────────
ADB_AUTOMATION_LEASE_SECONDS=600       # How long a device is locked per job (seconds)
```

---

## Starting Services

Start these three things **before** making any API calls:

### 1 — MariaDB

**Windows:**
```powershell
net start MariaDB
```

**macOS:**
```bash
brew services start mariadb
```

### 2 — Appium Server

In a dedicated terminal:

```bash
appium --port 4723
```

### 3 — Flask API Server

In another terminal, from the project root:

```bash
python server.py
# or with explicit host/port:
python server.py --host 0.0.0.0 --port 5000
```

The server starts queue workers automatically on startup.

---

## CLI Reference

The CLI is useful for one-off sends and device management without running the full server.

```bash
python -m adb_automation [OPTIONS] COMMAND
```

### Global Options

| Flag | Default | Description |
|---|---|---|
| `--database NAME` | `adb_automation` | MariaDB database name |
| `--db-host HOST` | `localhost` | MariaDB host |
| `--db-port PORT` | `3306` | MariaDB port |
| `--db-user USER` | `root` | MariaDB user |
| `--db-password PASS` | _(env)_ | MariaDB password |

### `send` — Send a message

```bash
python -m adb_automation send \
  --device "my-phone" \
  --phone "27821234567" \
  --text "Hello from CLI" \
  [--file /path/to/image.jpg] \
  [--business] \
  [--lease-seconds 300]
```

| Flag | Required | Description |
|---|---|---|
| `--device` | Yes | Device name or ID |
| `--phone` | Yes | Phone number with country code, no `+` or spaces |
| `--text` | No | Message text |
| `--file` | No | Local path to image or video file |
| `--business` | No | Use WhatsApp Business instead of regular WhatsApp |
| `--lease-seconds` | No | Override device lease TTL |

### `devices` — Manage devices

**List all registered devices:**
```bash
python -m adb_automation devices list
```

**Add a device:**
```bash
python -m adb_automation devices add \
  --name "my-phone" \
  --ip 192.168.1.50 \
  --port 37001
```

**Unlock a stuck device lease:**
```bash
python -m adb_automation devices unlock --device "my-phone"
```

---

## API Reference

All endpoints require the header:

```
X-API-Key: <your ADB_AUTOMATION_API_KEY value>
```

All request bodies are JSON (`Content-Type: application/json`).

---

### Authentication Error

Returned by every endpoint when the key is missing or wrong.

```json
HTTP 401
{
  "success": false,
  "error": "invalid or missing API key."
}
```

---

### Devices

#### `GET /api/devices` — List devices

Returns all registered devices and their current ADB connection state.

**Response:**
```json
HTTP 200
{
  "success": true,
  "devices": [
    {
      "id": 1,
      "name": "my-phone",
      "ip": "192.168.1.50",
      "port": 37001,
      "serial": "192.168.1.50:37001",
      "adb_state": "device",
      "connected": true,
      "worker_id": null,
      "locked_until": null,
      "last_seen_at": "2025-01-15T10:30:00"
    }
  ]
}
```

`adb_state` values: `"device"` (connected), `"offline"`, `"unauthorized"`, `"disconnected"`.

---

#### `POST /api/devices` — Register a device

**Request:**
```json
{
  "name": "my-phone",
  "ip": "192.168.1.50",
  "port": 37001
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | Yes | Unique human-readable label |
| `ip` | string | Yes | Device Wi-Fi IP address |
| `port` | integer | Yes | Device ADB port (shown in Developer Options) |

**Response:**
```json
HTTP 201
{
  "success": true,
  "device": { ...same shape as list... }
}
```

---

#### `POST /api/pair` — Pair and register a new device

Used for the initial Wi-Fi pairing flow (Android 11+). Pairs the device via the pairing code, then registers it.

**Request:**
```json
{
  "name": "my-phone",
  "pair_ip": "192.168.1.50",
  "pair_port": 37000,
  "pairing_code": "123456",
  "connect_ip": "192.168.1.50",
  "connect_port": 37001
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | Yes | Unique label for this device |
| `pair_ip` | string | Yes | IP shown in the pairing QR screen |
| `pair_port` | integer | Yes | Port shown in the pairing QR screen |
| `pairing_code` | string | Yes | 6-digit code shown on device |
| `connect_ip` | string | Yes | IP to use for ongoing ADB connections |
| `connect_port` | integer | Yes | Port to use for ongoing ADB connections |

**Response:**
```json
HTTP 201
{
  "success": true,
  "adb_output": "Successfully paired to 192.168.1.50:37000",
  "device": { ...device object... }
}
```

---

#### `POST /api/devices/{id}/connect` — Connect to a device

Runs `adb connect` for a registered device.

```
POST /api/devices/1/connect
```

**Response:**
```json
HTTP 200
{
  "success": true,
  "adb_output": "connected to 192.168.1.50:37001",
  "device": { ...device object... }
}
```

---

### Sending Messages

All send endpoints follow the same pattern: they enqueue a job and return immediately with a `job_id`. Use `GET /api/jobs/{id}` to poll the result.

**Common fields for all send requests:**

| Field | Type | Required | Description |
|---|---|---|---|
| `device` | string | Yes | Device name (as registered) |
| `phone` | string | Yes | Recipient phone number with country code, no `+` (e.g. `"27821234567"`) |
| `business` | boolean | No | `true` to use WhatsApp Business. Default: `false` |
| `worker_id` | string | No | Identifier for this caller. Auto-generated if omitted |
| `lease_seconds` | integer | No | Device lock TTL. Defaults to `ADB_AUTOMATION_LEASE_SECONDS` (600) |

**Common success response (HTTP 202):**
```json
{
  "success": true,
  "queued": true,
  "job_id": 42,
  "status": "pending",
  "endpoint": "/api/sendText",
  "device": "my-phone",
  "device_id": 1,
  "phone": "27821234567"
}
```

---

#### `POST /api/sendText` — Send a text message

```json
{
  "device": "my-phone",
  "phone": "27821234567",
  "text": "Hello, world!"
}
```

| Field | Type | Required |
|---|---|---|
| `text` | string | **Yes** |

---

#### `POST /api/sendImage` — Send an image

The file can be supplied three ways (choose one):

**Option A — Local file path on the server:**
```json
{
  "device": "my-phone",
  "phone": "27821234567",
  "file_path": "/home/user/photos/image.jpg",
  "caption": "Check this out"
}
```

**Option B — `file` as a string path:**
```json
{
  "device": "my-phone",
  "phone": "27821234567",
  "file": "/home/user/photos/image.jpg",
  "caption": "Check this out"
}
```

**Option C — Download from URL:**
```json
{
  "device": "my-phone",
  "phone": "27821234567",
  "file": {
    "url": "https://example.com/photo.jpg",
    "filename": "photo.jpg"
  },
  "caption": "Check this out"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `file_path` | string | Yes* | Server-local path to the image |
| `file` | string or object | Yes* | Path string **or** `{ "url": "...", "filename": "..." }` |
| `file_url` | string | Yes* | Direct URL to download the image |
| `caption` | string | No | Optional caption text (alias for `text`) |

\* One of `file_path`, `file`, or `file_url` is required.

---

#### `POST /api/sendVideo` — Send a video

Same request shape as `sendImage`. Accepts `.mp4` and other common formats.

```json
{
  "device": "my-phone",
  "phone": "27821234567",
  "file_path": "/home/user/videos/clip.mp4",
  "caption": "Watch this"
}
```

---

#### `POST /api/sendVoice` — Send a voice message

Same request shape as `sendImage`. The server automatically converts audio to the OGG/Opus format WhatsApp requires (via FFmpeg).

```json
{
  "device": "my-phone",
  "phone": "27821234567",
  "file_path": "/home/user/audio/voice.mp3"
}
```

---

### Jobs

#### `GET /api/jobs/{id}` — Get a job

```
GET /api/jobs/42
```

**Response:**
```json
HTTP 200
{
  "success": true,
  "job": {
    "id": 42,
    "status": "succeeded",
    "endpoint": "/api/sendText",
    "device_id": 1,
    "device": "my-phone",
    "phone": "27821234567",
    "text": "Hello, world!",
    "file_path": null,
    "business": false,
    "worker_id": "api-hostname-1234",
    "lease_seconds": 600,
    "queue_worker_id": "worker-0",
    "device_locked_until": "2025-01-15T10:40:00",
    "error": null,
    "created_at": "2025-01-15T10:30:00",
    "updated_at": "2025-01-15T10:30:45",
    "started_at": "2025-01-15T10:30:01",
    "finished_at": "2025-01-15T10:30:45"
  }
}
```

**`status` values:**

| Value | Meaning |
|---|---|
| `pending` | Waiting in queue |
| `running` | Device is locked and processing |
| `succeeded` | Message was sent successfully |
| `failed` | An error occurred — check `error` field |

---

#### `GET /api/jobs` — List jobs

```
GET /api/jobs?status=pending&limit=20
```

| Query param | Type | Default | Description |
|---|---|---|---|
| `status` | string | _(all)_ | Filter: `pending`, `running`, `succeeded`, or `failed` |
| `limit` | integer | `50` | Number of jobs to return (max 500) |

Jobs are returned newest-first.

**Response:**
```json
HTTP 200
{
  "success": true,
  "jobs": [ ...array of job objects... ]
}
```

---

### Error Responses

All endpoints return a consistent error shape:

```json
{
  "success": false,
  "error": "human-readable error message."
}
```

| HTTP Status | Meaning |
|---|---|
| `400` | Bad request — missing or invalid field |
| `401` | Missing or invalid `X-API-Key` |
| `404` | Resource not found |
| `500` | Server error (Appium, ADB, or database failure) |

---

## Device Setup (Android)

### Enable Wireless Debugging (Android 11+)

1. Go to **Settings → About Phone** and tap **Build Number** 7 times.
2. Go to **Settings → Developer Options**.
3. Enable **Wireless Debugging**.
4. Tap **Wireless Debugging** to open it — note the **IP address** and **port** shown.

### First-time pairing (QR or code)

1. In Wireless Debugging, tap **Pair device with pairing code**.
2. Note the **pairing port** and **6-digit code**.
3. Use `POST /api/pair` (or `adb pair`) with those values.

### Subsequent connections

After the first pair, the device remembers the host. Use `POST /api/devices/{id}/connect` or:

```bash
adb connect 192.168.1.50:37001
```

### WhatsApp must be open

The automation drives the WhatsApp UI. WhatsApp must be installed and logged in on the device. The app does not need to be in the foreground — Appium launches it automatically.

For WhatsApp Business, pass `"business": true` in the request or use `--business` in the CLI.
# adb-automation
ADB automation with endpoints
