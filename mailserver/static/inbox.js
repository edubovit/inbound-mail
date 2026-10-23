(() => {
  const content = document.getElementById("inbox-content");
  if (!content) return;

  const status = document.getElementById("inbox-status");
  const refreshLink = document.getElementById("inbox-refresh");
  const interval = 10000;
  const account = content.querySelector("[data-inbox-content]").dataset.account;
  let timer;
  let pending;
  let requested = false;
  let stopped = false;

  function setStatus(text, state) {
    status.textContent = text;
    status.dataset.state = state;
  }

  function active() {
    return !stopped && !document.hidden && navigator.onLine;
  }

  function schedule() {
    clearTimeout(timer);
    if (active()) timer = setTimeout(refresh, interval);
  }

  async function refresh() {
    clearTimeout(timer);
    if (!active()) return;
    if (pending) {
      requested = true;
      return;
    }

    requested = false;
    pending = new AbortController();
    const timeout = setTimeout(() => pending?.abort(), 8000);
    const url = new URL(content.dataset.updatesUrl, location.origin);
    url.search = location.search;
    try {
      const response = await fetch(url, {
        credentials: "same-origin",
        cache: "no-store",
        signal: pending.signal,
      });
      if (!active()) return;
      if (response.redirected) {
        const target = new URL(response.url);
        if (target.origin !== location.origin) throw new Error("Unexpected redirect");
        stopped = true;
        content.replaceChildren();
        location.replace(target.href);
        return;
      }
      if (!response.ok) throw new Error("Inbox unavailable");
      const documentUpdate = new DOMParser().parseFromString(await response.text(), "text/html");
      const next = documentUpdate.querySelector("[data-inbox-content]");
      if (!next) throw new Error("Invalid inbox response");
      if (!active()) return;
      if (next.dataset.account !== account) {
        stopped = true;
        content.replaceChildren();
        location.reload();
        return;
      }
      const current = content.querySelector("[data-inbox-content]");
      if (!current.isEqualNode(next)) {
        const focus = content.contains(document.activeElement) ? document.activeElement.getAttribute("href") : null;
        current.replaceWith(next);
        if (focus) {
          const replacement = [...content.querySelectorAll("a")].find(link => link.getAttribute("href") === focus);
          (replacement || content).focus({preventScroll: true});
        }
      }
      setStatus("Live · every 10s", "live");
    } catch {
      if (active()) setStatus("Could not refresh · retrying", "error");
    } finally {
      clearTimeout(timeout);
      pending = null;
      if (requested && active()) {
        requested = false;
        timer = setTimeout(refresh, 0);
      } else {
        schedule();
      }
    }
  }

  function visibilityChanged() {
    if (active()) {
      refresh();
    } else {
      clearTimeout(timer);
      pending?.abort();
      setStatus(navigator.onLine ? "Paused in background" : "Offline · waiting for connection", "idle");
    }
  }

  refreshLink.addEventListener("click", event => {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    refresh();
  });
  document.addEventListener("visibilitychange", visibilityChanged);
  window.addEventListener("online", visibilityChanged);
  window.addEventListener("offline", visibilityChanged);
  window.addEventListener("pagehide", () => {
    stopped = true;
    clearTimeout(timer);
    pending?.abort();
  });
  window.addEventListener("pageshow", event => {
    if (event.persisted) {
      stopped = false;
      visibilityChanged();
    }
  });
  setStatus(active() ? "Live · every 10s" : "Automatic refresh paused", active() ? "live" : "idle");
  schedule();
})();
