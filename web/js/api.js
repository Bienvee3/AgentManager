// REST + WebSocket access to the Manager.

export function createApi(baseUrl) {
  async function request(path, options) {
    const res = await fetch(baseUrl + path, options);
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res;
  }

  function decide(id, verb, reason) {
    return request(`/api/approvals/${encodeURIComponent(id)}/${verb}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason ?? "", via: "web" }),
    }).then((res) => res.json());
  }

  return {
    async getState() {
      return (await request("/api/state")).json();
    },
    approve(id, reason) {
      return decide(id, "approve", reason);
    },
    reject(id, reason) {
      return decide(id, "reject", reason);
    },
  };
}

const BACKOFF_START_MS = 1000;
const BACKOFF_MAX_MS = 10000;

// Reconnecting WebSocket: backoff starts at 1 s, doubles up to 10 s and resets
// once a connection opens. Returns { close() }.
export function connectEvents(wsUrl, { onEvent, onStatus }) {
  let delay = BACKOFF_START_MS;
  let ws = null;
  let timer = null;
  let closed = false;

  function scheduleReconnect() {
    if (closed || timer !== null) return;
    timer = setTimeout(() => {
      timer = null;
      connect();
    }, delay);
    delay = Math.min(delay * 2, BACKOFF_MAX_MS);
  }

  function connect() {
    if (closed) return;
    try {
      ws = new WebSocket(wsUrl);
    } catch (err) {
      onStatus("offline");
      scheduleReconnect();
      return;
    }
    const socket = ws;
    socket.onopen = () => {
      delay = BACKOFF_START_MS;
      onStatus("online");
    };
    socket.onmessage = (msg) => {
      let event;
      try {
        event = JSON.parse(msg.data);
      } catch (err) {
        return;
      }
      onEvent(event);
    };
    socket.onclose = () => {
      if (ws === socket) ws = null;
      onStatus("offline");
      scheduleReconnect();
    };
    socket.onerror = () => {
      // "close" always follows; reconnection is handled there.
    };
  }

  connect();

  return {
    close() {
      closed = true;
      clearTimeout(timer);
      if (ws) ws.close();
    },
  };
}
