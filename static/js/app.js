/**
 * app.js - Shared Frontend Utilities & REST API Client
 */

export const STORAGE_KEY_GEMINI = "gemini_live_api_key";

export function getStoredApiKey() {
  return localStorage.getItem(STORAGE_KEY_GEMINI) || "";
}

export function setStoredApiKey(key) {
  if (key) {
    localStorage.setItem(STORAGE_KEY_GEMINI, key.trim());
  } else {
    localStorage.removeItem(STORAGE_KEY_GEMINI);
  }
}

export function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  const bgColors = {
    info: "bg-slate-800 text-slate-100 border-slate-700",
    success: "bg-emerald-900/90 text-emerald-100 border-emerald-700",
    error: "bg-rose-900/90 text-rose-100 border-rose-700",
    warning: "bg-amber-900/90 text-amber-100 border-amber-700",
  };

  toast.className = `flex items-center gap-3 px-4 py-3 rounded-xl border text-sm font-medium shadow-2xl backdrop-blur-md transition-all duration-300 transform translate-y-2 opacity-0 ${bgColors[type] || bgColors.info}`;
  toast.innerHTML = `<span>${message}</span>`;

  container.appendChild(toast);
  requestAnimationFrame(() => {
    toast.classList.remove("translate-y-2", "opacity-0");
  });

  setTimeout(() => {
    toast.classList.add("opacity-0", "translate-y-2");
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

export async function verifyApiKey(key) {
  const resp = await fetch("/api/verify-key", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ apiKey: key }),
  });
  return await resp.json();
}

export async function fetchGithubPreview(username) {
  const resp = await fetch(`/api/github-preview?username=${encodeURIComponent(username)}`);
  if (!resp.ok) {
    throw new Error(`Failed to fetch GitHub profile (HTTP ${resp.status})`);
  }
  return await resp.json();
}

export async function createInterview(username, selectedRepo, apiKey) {
  const resp = await fetch("/api/pre-interview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, selectedRepo, apiKey }),
  });
  if (!resp.ok) {
    const err = await resp.json();
    throw new Error(err.detail || "Failed to initialize interview");
  }
  return await resp.json();
}

export async function endInterview(interviewId, apiKey) {
  const resp = await fetch(`/api/end-interview/${interviewId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ apiKey }),
  });
  if (!resp.ok) {
    throw new Error("Failed to end interview session");
  }
  return await resp.json();
}

export async function getResultData(interviewId) {
  const resp = await fetch(`/api/result-data/${interviewId}`);
  if (!resp.ok) {
    throw new Error("Failed to retrieve scorecard dossier");
  }
  return await resp.json();
}
