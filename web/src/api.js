export const BASE = import.meta.env.VITE_API_URL || "http://localhost:8300";

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
  metrics: id => req(`/api/runs/${id}/metrics`),
  deleteRun: async id => {
    const r = await fetch(`${BASE}/api/runs/${id}`, { method: "DELETE",
      headers: { "X-API-Key": sessionStorage.getItem("jeagent_key") || "" } });
    const b = await r.json();
    if (b.detail) throw new Error(b.detail);
    return b;
  },
  entryDetail: (id, ref) => req(`/api/runs/${id}/entry/${encodeURIComponent(ref)}`),
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
    const body = await r.json();
    if (body.detail) throw new Error(body.detail);
    return body;
  },
  testConnection: body =>
    req("/api/provider/test-connection", { method: "POST", body: JSON.stringify(body) }),
  createEngagement: (configYaml, file) => {
    const fd = new FormData();
    fd.append("config_yaml", configYaml);
    fd.append("extract", file);
    return fetch(`${BASE}/api/engagements`, {
      method: "POST",
      headers: { "X-API-Key": sessionStorage.getItem("jeagent_key") || "" },
      body: fd,
    }).then(r => r.json());
  },
  autodetect: async file => {
    const fd = new FormData();
    fd.append("extract", file);
    const res = await fetch(`${BASE}/api/autodetect`, {
      method: "POST", headers: { "X-API-Key": sessionStorage.getItem("jeagent_key") || "" },
      body: fd,
    });
    const body = await res.json();
    if (body.detail) throw new Error(body.detail);
    return body;
  },
  artifactUrl: async (id, name) => {
    // Fetch a scoped token, then return a URL that opens WITHOUT the X-API-Key
    // header — so the in-app preview / a new tab can render report.pdf etc.
    // without triggering a browser auth prompt (raw 401 → Windows dialog).
    const r = await fetch(`${BASE}/api/runs/${id}/artifacts/${name}/token`, {
      headers: { "X-API-Key": sessionStorage.getItem("jeagent_key") || "" },
    });
    const b = await r.json();
    if (b.detail) throw new Error(b.detail);
    return `${BASE}/api/runs/${id}/artifact/${name}?token=${encodeURIComponent(b.token)}`;
  },
  download: async (id, name) => {
    const res = await fetch(`${BASE}/api/runs/${id}/artifacts/${name}`, {
      headers: { "X-API-Key": sessionStorage.getItem("jeagent_key") || "" },
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    // Revoke AFTER the browser has had time to read the blob. Revoking
    // immediately races the async download and can write a 0-byte file for
    // large artifacts (e.g. the PDF). Delay improves reliability without
    // leaking the object URL for long (small leak, acceptable).
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  },
};
