const scriptEl = document.currentScript;
const OIDC_CLIENTS_ENDPOINT = scriptEl.dataset.oidcClientsEndpoint;
const DINGTALK_APPS_ENDPOINT = scriptEl.dataset.dingtalkAppsEndpoint;
const form = document.getElementById("client-form");
const statusEl = document.getElementById("status");
const rowsEl = document.getElementById("client-rows");
const countEl = document.getElementById("client-count");
const editorModeEl = document.getElementById("editor-mode");
const appSelectEl = document.getElementById("dingtalk_app_id");
const adminKeyEl = document.getElementById("admin-key");
const clientIdEl = document.getElementById("client_id");
const nameEl = document.getElementById("name");
const clientSecretEl = document.getElementById("client_secret");
const redirectUrisEl = document.getElementById("redirect_uris");
const enabledEl = document.getElementById("enabled");
const requirePkceEl = document.getElementById("require_pkce");

let currentClients = [];
let editingClientId = null;

function setStatus(message, level) {
  statusEl.textContent = message || "";
  statusEl.className = "status" + (level ? " " + level : "");
}

function getHeaders() {
  const key = adminKeyEl.value.trim();
  if (!key) {
    throw new Error("Admin API Key is required");
  }
  return { "x-admin-key": key, "Content-Type": "application/json" };
}

function setEditingState(isEditing) {
  clientIdEl.readOnly = isEditing;
}

function createCell(text, className) {
  const cell = document.createElement("td");
  if (className) {
    cell.className = className;
  }
  cell.textContent = text;
  return cell;
}

function createEmptyStateRow(message) {
  const row = document.createElement("tr");
  const cell = createCell(message, "muted");
  cell.colSpan = 6;
  row.appendChild(cell);
  return row;
}

function resetForm() {
  form.reset();
  editingClientId = null;
  enabledEl.checked = true;
  requirePkceEl.checked = true;
  appSelectEl.value = "";
  editorModeEl.textContent = "Create or update a client";
  setEditingState(false);
}

function populateForm(client) {
  editingClientId = client.client_id || null;
  clientIdEl.value = editingClientId || "";
  nameEl.value = client.name || "";
  clientSecretEl.value = "";
  redirectUrisEl.value = (client.redirect_uris || []).join("\n");
  enabledEl.checked = Boolean(client.enabled);
  requirePkceEl.checked = client.require_pkce !== false;
  appSelectEl.value = client.dingtalk_app_id == null ? "" : String(client.dingtalk_app_id);
  editorModeEl.textContent = "Editing " + client.client_id;
  setEditingState(true);
  window.scrollTo({ top: form.offsetTop - 20, behavior: "smooth" });
}

function renderClients(clients) {
  currentClients = clients;
  countEl.textContent = clients.length + " clients";
  rowsEl.replaceChildren();
  if (!clients.length) {
    rowsEl.appendChild(createEmptyStateRow("No OIDC clients found."));
    return;
  }

  const fragment = document.createDocumentFragment();
  clients.forEach((client) => {
    const appId = client.dingtalk_app_id == null ? "-" : client.dingtalk_app_id;
    const row = document.createElement("tr");
    row.dataset.clientId = client.client_id;

    const buttonCell = document.createElement("td");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary row-edit";
    button.textContent = client.client_id;
    button.addEventListener("click", (event) => {
      const row = event.target.closest("tr");
      const client = currentClients.find((item) => item.client_id === row.dataset.clientId);
      if (client) {
        populateForm(client);
      }
    });
    buttonCell.appendChild(button);

    const redirectUrisCell = createCell((client.redirect_uris || []).join("\n") || "-", "pre-wrap");

    row.appendChild(buttonCell);
    row.appendChild(createCell(client.name || "-"));
    row.appendChild(createCell(client.enabled ? "true" : "false"));
    row.appendChild(createCell(client.require_pkce === false ? "false" : "true"));
    row.appendChild(createCell(String(appId)));
    row.appendChild(redirectUrisCell);
    fragment.appendChild(row);
  });
  rowsEl.appendChild(fragment);
}

async function loadDingTalkApps() {
  const response = await fetch(DINGTALK_APPS_ENDPOINT, { headers: getHeaders() });
  if (!response.ok) {
    throw new Error("Failed to load DingTalk apps: " + response.status);
  }
  const apps = await response.json();
  appSelectEl.replaceChildren();

  const defaultOption = document.createElement("option");
  defaultOption.value = "";
  defaultOption.textContent = "Use default / none";
  appSelectEl.appendChild(defaultOption);

  apps.forEach((app) => {
    const option = document.createElement("option");
    option.value = String(app.id);
    option.textContent = app.id + " - " + (app.name || app.app_key);
    appSelectEl.appendChild(option);
  });
}

async function loadClients() {
  setStatus("Loading clients...", "");
  await loadDingTalkApps();
  const response = await fetch(OIDC_CLIENTS_ENDPOINT, { headers: getHeaders() });
  if (!response.ok) {
    throw new Error("Failed to load OIDC clients: " + response.status);
  }
  const clients = await response.json();
  renderClients(clients);
  setStatus("Loaded OIDC clients successfully.", "ok");
}

document.getElementById("load-btn").addEventListener("click", async () => {
  try {
    await loadClients();
  } catch (error) {
    setStatus(error.message, "error");
  }
});

document.getElementById("new-btn").addEventListener("click", () => {
  resetForm();
  setStatus("Ready to create a new OIDC client.", "");
});

document.getElementById("reset-btn").addEventListener("click", () => {
  resetForm();
  setStatus("Form reset.", "");
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const payloadClientId = editingClientId || clientIdEl.value.trim();
    const payload = {
      client_id: payloadClientId,
      name: nameEl.value.trim(),
      enabled: enabledEl.checked,
      redirect_uris: redirectUrisEl.value.split(/\n+/).map((item) => item.trim()).filter(Boolean),
      require_pkce: requirePkceEl.checked,
      dingtalk_app_id: appSelectEl.value === "" ? null : Number(appSelectEl.value),
    };
    const secret = clientSecretEl.value.trim();
    if (secret) {
      payload.client_secret = secret;
    }
    const response = await fetch(OIDC_CLIENTS_ENDPOINT, {
      method: "POST",
      headers: getHeaders(),
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Save failed");
    }
    clientSecretEl.value = "";
    setStatus("OIDC client saved successfully.", "ok");
    await loadClients();
    populateForm(data);
  } catch (error) {
    setStatus(error.message, "error");
  }
});
