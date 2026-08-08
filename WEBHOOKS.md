# Incoming WhatsApp message webhooks

This describes how the system delivers "a WhatsApp message was received" events to your
downstream service. It covers two hops:

```
Android phone (WhatsApp app)
      │  notification posted
      ▼
notification-listener-app (NotificationListenerService)
      │  POST multipart/form-data
      ▼
adb-automation server: POST /api/notifications/ingest
      │  stores row in `received_notifications`
      │  POST application/json  ──────────────────────► your webhook (ADB_AUTOMATION_WEBHOOK_URL)
      ▼
served back via GET /api/notifications, GET /api/notifications/media/<id>
```

There is no official WhatsApp webhook here — [notification-listener-app/](notification-listener-app/)
is a small Android app that reads WhatsApp's own notifications on-device and reports them in.

## 1. Ingest endpoint (phone → server)

You generally don't call this yourself — the Android app does. Documented here so you know what's
flowing into the server.

```
POST /api/notifications/ingest
Content-Type: multipart/form-data
X-API-Key: <ADB_AUTOMATION_API_KEY>
```

| Field | Type | Required | Description |
|---|---|---|---|
| `payload` | JSON string | yes | See shape below |
| `media` | file | no | Raw bytes of an attached image/media thumbnail, if the notification had one |

**`payload` JSON shape:**

```json
{
  "device_label": "phone-01",
  "package": "com.whatsapp",
  "conversation_title": "Jane Doe",
  "post_time_ms": 1736330200000,
  "messages": [
    {
      "sender": "Jane Doe",
      "text": "Hey, are you free tomorrow?",
      "timestamp_ms": 1736330200000,
      "has_media": false,
      "mime_type": null
    }
  ]
}
```

- `device_label` — free-text label set in the app's settings screen; use it to identify which phone/number the message came in on.
- `package` — `com.whatsapp` (Messenger) or `com.whatsapp.w4b` (Business).
- `messages` — required, non-empty array. WhatsApp's grouped notifications can bundle multiple unread messages into one notification post, so this is a list, not a single message.
- `has_media` / `mime_type` — set when a message has an attached image; the actual bytes travel in the separate `media` form field.

**Response — `202 Accepted`:**

```json
{
  "success": true,
  "notification": {
    "id": 7,
    "device_label": "phone-01",
    "package": "com.whatsapp",
    "sender": "Jane Doe",
    "text": "Hey, are you free tomorrow?",
    "mime_type": null,
    "has_media": false,
    "created_at": "2025-01-15T10:30:00+00:00"
  }
}
```

Note: `sender`/`text` on the stored notification are derived from the **first** message in the
`messages` array (`text` is actually all messages' text joined with `\n`); the full original
payload is kept as-is in the `payload_json` column if you need per-message detail later.

## 2. Webhook delivery (server → your service)

If `ADB_AUTOMATION_WEBHOOK_URL` is set (see `.env`), every successfully-ingested notification is
immediately forwarded there:

```
POST <ADB_AUTOMATION_WEBHOOK_URL>
Content-Type: application/json
```

**Body:**

```json
{
  "id": 7,
  "device_label": "phone-01",
  "package": "com.whatsapp",
  "sender": "Jane Doe",
  "text": "Hey, are you free tomorrow?",
  "mime_type": null,
  "has_media": false,
  "media_url": null,
  "created_at": "2025-01-15T10:30:00+00:00"
}
```

When media was attached:

```json
{
  "id": 8,
  "device_label": "phone-01",
  "package": "com.whatsapp",
  "sender": "Jane Doe",
  "text": "",
  "mime_type": "image/jpeg",
  "has_media": true,
  "media_url": "/api/notifications/media/8",
  "created_at": "2025-01-15T10:31:05+00:00"
}
```

`media_url` is a **relative** path on this adb-automation server, not a fully-qualified URL —
prepend the server's own base URL, then fetch it with the same `X-API-Key` header:

```
GET <server-base-url>/api/notifications/media/8
X-API-Key: <ADB_AUTOMATION_API_KEY>
```

That returns the raw file bytes with the original `Content-Type`.

### Delivery semantics (important)

- **No authentication is added** to the outbound webhook POST — if your endpoint needs a secret/signature, put it in the URL (e.g. a query token) or add verification on your side. `ADB_AUTOMATION_API_KEY` is never sent to your webhook.
- **Best-effort, no retries.** If your endpoint is down or times out (5s), the event is dropped — it is not queued or retried. The event still exists in the database (see below), so you can reconcile via `GET /api/notifications` if needed.
- **Fire-and-forget per notification**, delivered in the same request that does the ingest — no batching.

## 3. Reading events back from the server

Useful for debugging, backfilling, or if you'd rather poll than receive webhooks.

```
GET /api/notifications?limit=50
X-API-Key: <ADB_AUTOMATION_API_KEY>
```

Returns `{"success": true, "notifications": [ ...newest first... ]}`, each item shaped like the
`notification` object in section 1 (no `media_url` field here — check `has_media` and fetch
`/api/notifications/media/<id>` directly).

## 4. Config reference

| Env var | Required | Description |
|---|---|---|
| `ADB_AUTOMATION_API_KEY` | yes | Same key used by every other endpoint; the phone app authenticates with it too. |
| `ADB_AUTOMATION_WEBHOOK_URL` | no | Where to forward events. Leave blank to disable outbound delivery (events are still stored and readable via `GET /api/notifications`). |

## 5. Limits

- Max media size accepted by `/api/notifications/ingest`: 25 MB (`MAX_INGEST_MEDIA_BYTES` in `adb_automation/notifications.py`).
- `limit` on `GET /api/notifications`: max 500, default 50.
- Webhook POST timeout: 5 seconds.

## 6. Quick test without the phone app

```bash
curl -X POST http://localhost:5000/api/notifications/ingest \
  -H "X-API-Key: $ADB_AUTOMATION_API_KEY" \
  -F 'payload={"device_label":"test","package":"com.whatsapp","messages":[{"sender":"Jane","text":"hello"}]}'
```

If `ADB_AUTOMATION_WEBHOOK_URL` is set to something like `https://webhook.site/<id>`, you should see
the JSON event land there immediately.
