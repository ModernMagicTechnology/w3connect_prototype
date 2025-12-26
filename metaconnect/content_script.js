(() => {
  const STORAGE_DEFAULTS = {
    allowlist: []
  };

  function hostMatchesPattern(host, pattern) {
    if (!pattern) return false;
    if (pattern === "*") return true;
    if (pattern.startsWith("*.")) {
      const suffix = pattern.slice(2);
      return host === suffix || host.endsWith("." + suffix);
    }
    return host === pattern;
  }

  function isAllowed(host, allowlist) {
    if (!Array.isArray(allowlist) || allowlist.length === 0) return false;
    return allowlist.some((pattern) => hostMatchesPattern(host, pattern));
  }

  function injectInpage() {
    const script = document.createElement("script");
    script.src = chrome.runtime.getURL("inpage.js");
    script.async = false;
    (document.head || document.documentElement).appendChild(script);
    script.remove();
  }

  function setupBridge() {
    window.addEventListener("message", (event) => {
      if (event.source !== window) return;
      const data = event.data;
      if (!data || data.target !== "METACONNECT_CONTENT") return;

      chrome.runtime.sendMessage(
        {
          type: "METACONNECT_FORWARD",
          id: data.id,
          method: data.method,
          params: data.params
        },
        (response) => {
          const error = chrome.runtime.lastError
            ? chrome.runtime.lastError.message
            : null;

          window.postMessage(
            {
              target: "METACONNECT_INPAGE",
              id: data.id,
              response,
              error
            },
            "*"
          );
        }
      );
    });
  }

  chrome.storage.local.get(STORAGE_DEFAULTS, (config) => {
    if (!isAllowed(window.location.hostname, config.allowlist)) return;
    injectInpage();
    setupBridge();
  });
})();
