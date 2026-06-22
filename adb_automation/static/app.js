(function () {
  const API_KEY_STORAGE = "adbAutomationApiKey";
  const AUTO_REFRESH_MS = 10000;

  const elements = {
    apiKeyForm: document.getElementById("apiKeyForm"),
    apiKeyInput: document.getElementById("apiKeyInput"),
    apiKeyState: document.getElementById("apiKeyState"),
    clearApiKeyButton: document.getElementById("clearApiKeyButton"),
    refreshButton: document.getElementById("refreshButton"),
    devicesBody: document.getElementById("devicesBody"),
    deviceCount: document.getElementById("deviceCount"),
    lastRefresh: document.getElementById("lastRefresh"),
    pairForm: document.getElementById("pairForm"),
    deviceForm: document.getElementById("deviceForm"),
    pairIpInput: document.getElementById("pairIpInput"),
    connectIpInput: document.getElementById("connectIpInput"),
    toast: document.getElementById("toast"),
  };

  let refreshInFlight = false;
  let toastTimer = null;
  let lastPairIp = "";

  function init() {
    elements.apiKeyInput.value = localStorage.getItem(API_KEY_STORAGE) || "";
    updateApiKeyState();

    elements.apiKeyForm.addEventListener("submit", handleApiKeySave);
    elements.clearApiKeyButton.addEventListener("click", handleApiKeyClear);
    elements.refreshButton.addEventListener("click", () => refreshDevices(false));
    elements.pairForm.addEventListener("submit", handlePairSubmit);
    elements.deviceForm.addEventListener("submit", handleDeviceSubmit);
    elements.pairIpInput.addEventListener("input", syncConnectIp);

    if (getApiKey()) {
      refreshDevices(true);
    }

    window.setInterval(() => {
      if (getApiKey()) {
        refreshDevices(true);
      }
    }, AUTO_REFRESH_MS);
  }

  function getApiKey() {
    return (localStorage.getItem(API_KEY_STORAGE) || "").trim();
  }

  function handleApiKeySave(event) {
    event.preventDefault();
    const apiKey = elements.apiKeyInput.value.trim();

    if (apiKey) {
      localStorage.setItem(API_KEY_STORAGE, apiKey);
      showToast("API key saved.", "success");
      refreshDevices(false);
    } else {
      localStorage.removeItem(API_KEY_STORAGE);
      showToast("API key cleared.", "success");
    }

    updateApiKeyState();
  }

  function handleApiKeyClear() {
    localStorage.removeItem(API_KEY_STORAGE);
    elements.apiKeyInput.value = "";
    updateApiKeyState();
    renderDevices([]);
    elements.lastRefresh.textContent = "Not refreshed";
    showToast("API key cleared.", "success");
  }

  function updateApiKeyState() {
    if (getApiKey()) {
      elements.apiKeyState.textContent = "API key set";
      elements.apiKeyState.className = "pill connected";
      return;
    }

    elements.apiKeyState.textContent = "API key unset";
    elements.apiKeyState.className = "pill muted";
  }

  async function apiRequest(path, options) {
    const apiKey = getApiKey();
    if (!apiKey) {
      throw new Error("API key is required.");
    }

    const requestOptions = Object.assign({ method: "GET" }, options || {});
    const headers = { "X-API-Key": apiKey };

    if (requestOptions.body !== undefined) {
      headers["Content-Type"] = "application/json";
      requestOptions.body = JSON.stringify(requestOptions.body);
    }

    requestOptions.headers = Object.assign(headers, requestOptions.headers || {});

    const response = await fetch(path, requestOptions);
    const payload = await response.json().catch(() => null);

    if (!response.ok || (payload && payload.success === false)) {
      const message = payload && payload.error ? payload.error : `HTTP ${response.status}`;
      throw new Error(message);
    }

    return payload || {};
  }

  async function refreshDevices(silent) {
    if (refreshInFlight) {
      return;
    }

    refreshInFlight = true;
    elements.refreshButton.disabled = true;

    try {
      const payload = await apiRequest("/api/devices");
      renderDevices(payload.devices || []);
      elements.lastRefresh.textContent = `Refreshed ${new Date().toLocaleTimeString()}`;
      if (!silent) {
        showToast("Device list refreshed.", "success");
      }
    } catch (error) {
      if (!silent) {
        showToast(error.message, "error");
      }
    } finally {
      refreshInFlight = false;
      elements.refreshButton.disabled = false;
    }
  }

  function renderDevices(devices) {
    elements.devicesBody.textContent = "";
    elements.deviceCount.textContent = `${devices.length} registered`;

    if (!devices.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 6;
      cell.className = "empty-cell";
      cell.textContent = "No devices registered";
      row.appendChild(cell);
      elements.devicesBody.appendChild(row);
      return;
    }

    devices.forEach((device) => {
      const row = document.createElement("tr");
      row.appendChild(renderNameCell(device));
      row.appendChild(textCell(`${device.ip}:${device.port}`));
      row.appendChild(renderAdbCell(device));
      row.appendChild(textCell(leaseText(device)));
      row.appendChild(textCell(formatValue(device.last_seen_at)));
      row.appendChild(renderActionCell(device));
      elements.devicesBody.appendChild(row);
    });
  }

  function renderNameCell(device) {
    const cell = document.createElement("td");
    const wrap = document.createElement("div");
    const name = document.createElement("strong");
    const serial = document.createElement("span");

    wrap.className = "device-name";
    name.textContent = device.name;
    serial.className = "serial";
    serial.textContent = device.serial;

    wrap.appendChild(name);
    wrap.appendChild(serial);
    cell.appendChild(wrap);
    return cell;
  }

  function renderAdbCell(device) {
    const cell = document.createElement("td");
    const pill = document.createElement("span");
    const state = device.adb_state || "disconnected";

    pill.textContent = state;
    pill.className = `pill ${device.connected ? "connected" : stateClass(state)}`;
    cell.appendChild(pill);
    return cell;
  }

  function renderActionCell(device) {
    const cell = document.createElement("td");
    const button = document.createElement("button");

    cell.className = "action-cell";
    button.className = "button secondary";
    button.type = "button";
    button.textContent = device.connected ? "Reconnect" : "Connect";
    button.addEventListener("click", () => connectDevice(device.id, button));

    cell.appendChild(button);
    return cell;
  }

  async function connectDevice(deviceId, button) {
    button.disabled = true;
    button.textContent = "Connecting";

    try {
      const payload = await apiRequest(`/api/devices/${deviceId}/connect`, {
        method: "POST",
      });
      const connected = payload.device && payload.device.connected;
      showToast(connected ? "Device connected." : "ADB command completed.", "success");
      refreshDevices(true);
    } catch (error) {
      showToast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  async function handlePairSubmit(event) {
    event.preventDefault();
    const body = formBody(elements.pairForm);
    setFormBusy(elements.pairForm, true);

    try {
      await apiRequest("/api/pair", { method: "POST", body });
      elements.pairForm.reset();
      lastPairIp = "";
      showToast("Device paired and saved.", "success");
      refreshDevices(true);
    } catch (error) {
      showToast(error.message, "error");
    } finally {
      setFormBusy(elements.pairForm, false);
    }
  }

  async function handleDeviceSubmit(event) {
    event.preventDefault();
    const body = formBody(elements.deviceForm);
    setFormBusy(elements.deviceForm, true);

    try {
      await apiRequest("/api/devices", { method: "POST", body });
      elements.deviceForm.reset();
      showToast("Device saved.", "success");
      refreshDevices(true);
    } catch (error) {
      showToast(error.message, "error");
    } finally {
      setFormBusy(elements.deviceForm, false);
    }
  }

  function syncConnectIp() {
    const nextPairIp = elements.pairIpInput.value;
    if (!elements.connectIpInput.value || elements.connectIpInput.value === lastPairIp) {
      elements.connectIpInput.value = nextPairIp;
    }
    lastPairIp = nextPairIp;
  }

  function formBody(form) {
    const data = {};
    new FormData(form).forEach((value, key) => {
      data[key] = String(value).trim();
    });
    return data;
  }

  function setFormBusy(form, busy) {
    form.querySelectorAll("button, input").forEach((control) => {
      control.disabled = busy;
    });
  }

  function textCell(value) {
    const cell = document.createElement("td");
    cell.textContent = value;
    return cell;
  }

  function leaseText(device) {
    if (!device.locked_until) {
      return "available";
    }
    return `${device.worker_id || "locked"} until ${device.locked_until}`;
  }

  function stateClass(state) {
    if (state === "offline" || state === "unauthorized") {
      return "warning";
    }
    if (state === "disconnected") {
      return "muted";
    }
    return "offline";
  }

  function formatValue(value) {
    return value || "-";
  }

  function showToast(message, type) {
    window.clearTimeout(toastTimer);
    elements.toast.textContent = message;
    elements.toast.className = `toast visible ${type || ""}`;
    toastTimer = window.setTimeout(() => {
      elements.toast.className = "toast";
    }, 4200);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
