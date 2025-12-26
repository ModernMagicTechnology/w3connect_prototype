const DEFAULT_ENDPOINT = "http://127.0.0.1:5333";
const DEFAULT_ALLOWLIST = [];

const endpointInput = document.getElementById("endpoint");
const allowlistInput = document.getElementById("allowlist");
const statusEl = document.getElementById("status");

function setStatus(message) {
  statusEl.textContent = message;
  if (!message) return;
  setTimeout(() => {
    statusEl.textContent = "";
  }, 1500);
}

function loadOptions() {
  chrome.storage.local.get(
    {
      endpoint: DEFAULT_ENDPOINT,
      allowlist: DEFAULT_ALLOWLIST
    },
    (config) => {
      endpointInput.value = config.endpoint || DEFAULT_ENDPOINT;
      allowlistInput.value = (config.allowlist || []).join("\n");
    }
  );
}

function saveOptions() {
  const endpoint = endpointInput.value.trim() || DEFAULT_ENDPOINT;
  const allowlist = allowlistInput.value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

  chrome.storage.local.set({ endpoint, allowlist }, () => {
    setStatus("Saved");
  });
}

function resetDefaults() {
  chrome.storage.local.set(
    {
      endpoint: DEFAULT_ENDPOINT,
      allowlist: DEFAULT_ALLOWLIST
    },
    () => {
      loadOptions();
      setStatus("Reset");
    }
  );
}


document.getElementById("save").addEventListener("click", saveOptions);
document.getElementById("reset").addEventListener("click", resetDefaults);

loadOptions();
