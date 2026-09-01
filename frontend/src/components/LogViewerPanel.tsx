import { useCallback, useEffect, useState } from "react";
import { RefreshCcw, ScrollText } from "lucide-react";

import { api } from "../api";
import type { LogTail } from "../types";

const LEVELS = ["", "INFO", "WARNING", "ERROR"] as const;
const LEVEL_LABEL: Record<string, string> = { "": "всё", INFO: "info+", WARNING: "warn+", ERROR: "только ошибки" };

export function LogViewerPanel() {
  const [tail, setTail] = useState<LogTail | null>(null);
  const [level, setLevel] = useState<string>("");
  const [search, setSearch] = useState("");
  const [auto, setAuto] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({ lines: "200" });
      if (level) params.set("level", level);
      if (search.trim()) params.set("search", search.trim());
      setTail(await api<LogTail>(`/api/logs?${params.toString()}`));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось прочитать журнал");
    }
  }, [level, search]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!auto) return;
    const timer = window.setInterval(load, 4000);
    return () => window.clearInterval(timer);
  }, [auto, load]);

  return (
    <div className="panel">
      <div className="panel-title">
        <ScrollText size={19} />
        <h2>Журнал</h2>
        <button className="icon-button secondary" title="Обновить" onClick={load}>
          <RefreshCcw size={17} />
        </button>
      </div>
      <div className="log-toolbar">
        <select value={level} onChange={(event) => setLevel(event.target.value)}>
          {LEVELS.map((value) => (
            <option key={value} value={value}>
              {LEVEL_LABEL[value]}
            </option>
          ))}
        </select>
        <input
          value={search}
          placeholder="Фильтр по тексту"
          onChange={(event) => setSearch(event.target.value)}
        />
        <label className="inline-check">
          <input type="checkbox" checked={auto} onChange={(event) => setAuto(event.target.checked)} /> авто
        </label>
      </div>
      {error && <p className="error-text">{error}</p>}
      {tail && <small>{tail.path} · {tail.returned} строк</small>}
      <div className="log-list">
        {(tail?.entries ?? []).map((entry, index) => (
          <div className={`log-line level-${entry.level.toLowerCase()}`} key={`${entry.timestamp}-${index}`}>
            <span className="log-meta">
              {entry.timestamp ?? ""} {entry.level} {entry.logger}
            </span>
            <pre>{entry.message}</pre>
          </div>
        ))}
        {tail && !tail.entries.length && <p className="empty">Записей по фильтру нет.</p>}
      </div>
    </div>
  );
}
