const DEFAULT_ENDPOINT = "http://127.0.0.1:5333";
// const DEFAULT_ALLOWLIST = [];

async function getConfig() {
  return chrome.storage.local.get({
    endpoint: DEFAULT_ENDPOINT
  });
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(["endpoint", "allowlist"], (config) => {
    const updates = {};
    if (!config.endpoint) updates.endpoint = DEFAULT_ENDPOINT;
    if (Object.keys(updates).length > 0) {
      chrome.storage.local.set(updates);
    }
  });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== "METACONNECT_FORWARD") return;

  (async () => {
    const { endpoint } = await getConfig();
    const payload = {
      jsonrpc: "2.0",
      id: message.id,
      method: message.method,
      params: message.params || [],
      origin: sender.origin || sender.url || null
    };

    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      throw new Error(`Wallet HTTP error: ${response.status}`);
    }

    const json = await response.json();
    sendResponse({ ok: true, response: json });
  })().catch((err) => {
    sendResponse({ ok: false, error: err.message });
  });

  return true;
});
