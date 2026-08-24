const BASE = import.meta.env.VITE_API_URL || "http://localhost:8300";

async function req(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      "X-API-Key": sessionStorage.getItem("jeagent_key") || "",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  if (res.status === 401) throw new Error("Invalid API key");
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  health: () => fetch(`${BASE}/health`).then(r => r.json()),
  runs: () => req("/api/runs"),
  runDetail: id => req(`/api/runs/${id}`),
  universe: id => req(`/api/runs/${id}/universe`),
  saveDecisions: (id, reviewer, decisions) =>
    req(`/api/runs/${id}/decisions`, {
      method: "POST",
      body: JSON.stringify({ reviewer, decisions }),
    }),
  finalize: async id => {
    const r = await fetch(`${BASE}/api/runs/${id}/finalize`, {
      method: "POST", headers: { "X-API-Key": sessionStorage.getItem("jeagent_key") || "" },
    });
    return r.json();
  },
  testConnection: body =>
    req("/api/provider/test-connection", { method: "POST", body: JSON.stringify(body) }),
  artifactUrl: (id, name) => `${BASE}/api/runs/${id}/artifacts/${name}`,
};
