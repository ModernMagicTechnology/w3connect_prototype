(() => {
  if (window.ethereum) return;

  const pending = new Map();
  let nextId = 1;

  function postRequest(method, params) {
    const id = nextId++;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      window.postMessage(
        {
          target: "METACONNECT_CONTENT",
          id,
          method,
          params
        },
        "*"
      );
    });
  }

  function handleResponse(event) {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.target !== "METACONNECT_INPAGE") return;

    const entry = pending.get(data.id);
    if (!entry) return;
    pending.delete(data.id);

    if (data.error) {
      entry.reject(new Error(data.error));
      return;
    }

    const response = data.response;
    if (!response) {
      entry.reject(new Error("Empty response from extension"));
      return;
    }

    if (!response.ok) {
      entry.reject(new Error(response.error || "Extension error"));
      return;
    }

    if (response.response && response.response.error) {
      const message = response.response.error.message || "RPC error";
      entry.reject(new Error(message));
      return;
    }

    entry.resolve(response.response ? response.response.result : null);
  }

  window.addEventListener("message", handleResponse);

  const listeners = new Map();

  function emit(event, payload) {
    const set = listeners.get(event);
    if (!set) return;
    for (const handler of set.values()) {
      try {
        handler(payload);
      } catch (err) {
        // Ignore listener errors.
      }
    }
  }

  const provider = {
    isMetaConnect: true,
    request: ({ method, params } = {}) => {
      if (!method) {
        return Promise.reject(new Error("Request method is required"));
      }
      return postRequest(method, params || []);
    },
    on: (event, handler) => {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event).add(handler);
    },
    removeListener: (event, handler) => {
      const set = listeners.get(event);
      if (set) set.delete(handler);
    },
    emit
  };

  provider.send = (methodOrPayload, paramsOrCallback) => {
    if (typeof methodOrPayload === "string") {
      return provider.request({ method: methodOrPayload, params: paramsOrCallback });
    }

    const payload = methodOrPayload || {};
    const callback = typeof paramsOrCallback === "function" ? paramsOrCallback : null;
    const promise = provider
      .request({ method: payload.method, params: payload.params })
      .then((result) => ({ id: payload.id, jsonrpc: "2.0", result }))
      .catch((error) => ({ id: payload.id, jsonrpc: "2.0", error: { message: error.message } }));

    if (callback) {
      promise.then((response) => callback(null, response));
      return;
    }

    return promise;
  };

  window.ethereum = provider;
  window.dispatchEvent(new Event("ethereum#initialized"));
})();
