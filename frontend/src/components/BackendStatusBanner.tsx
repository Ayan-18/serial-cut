import { useEffect, useRef, useState } from "react";
import { RefreshCcw } from "lucide-react";

import { api } from "../api";
import type { Health } from "../types";

// Polls /api/health so an out-of-band backend restart (which rotates the local
// API token and clears in-memory state) is visible instead of surfacing as
// confusing 403s.
export function BackendStatusBanner() {
  const firstBootId = useRef<string | null>(null);
  const [restarted, setRestarted] = useState(false);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let active = true;
    async function poll() {
      try {
        const health = await api<Health>("/api/health");
        if (!active) return;
        setOffline(false);
        if (firstBootId.current === null) firstBootId.current = health.boot_id;
        else if (health.boot_id !== firstBootId.current) setRestarted(true);
      } catch {
        if (active) setOffline(true);
      }
    }
    poll();
    const timer = window.setInterval(poll, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  if (!restarted && !offline) return null;
  return (
    <div className={`backend-banner ${restarted ? "warn" : "error"}`} role="alert">
      <span>
        {restarted
          ? "Бэкенд перезапущен. Обновите страницу, чтобы получить новый локальный токен и свежие данные."
          : "Нет связи с бэкендом SerialCuts. Проверьте, что приложение запущено."}
      </span>
      {restarted && (
        <button onClick={() => window.location.reload()}>
          <RefreshCcw size={15} /> Обновить
        </button>
      )}
    </div>
  );
}
