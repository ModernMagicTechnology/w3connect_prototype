const DEFAULT_ENDPOINT = "http://127.0.0.1:5333";

const endpointInput = document.getElementById("endpoint");
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
    },
    (config) => {
      endpointInput.value = config.endpoint || DEFAULT_ENDPOINT;
    }
  );
}

function saveOptions() {
  const endpoint = endpointInput.value.trim() || DEFAULT_ENDPOINT;

  chrome.storage.local.set({ endpoint, allowlist }, () => {
    setStatus("Saved");
  });
}

function resetDefaults() {
  chrome.storage.local.set(
    {
      endpoint: DEFAULT_ENDPOINT
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
