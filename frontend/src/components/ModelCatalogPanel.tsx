import { useEffect, useState } from "react";
import { Check, Download, HardDriveDownload } from "lucide-react";

import { api, jsonHeaders } from "../api";
import type { ModelCatalogEntry } from "../types";

function sizeLabel(mb: number) {
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} ГБ` : `${mb} МБ`;
}

export function ModelCatalogPanel() {
  const [entries, setEntries] = useState<ModelCatalogEntry[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  async function load() {
    try {
      setEntries(await api<ModelCatalogEntry[]>("/api/model-catalog"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Каталог моделей недоступен");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function install(entry: ModelCatalogEntry) {
    if (!window.confirm(`Скачать «${entry.title}» (~${sizeLabel(entry.approx_size_mb)}) в ${entry.target_dir}?`)) return;
    setBusy(entry.key);
    setMessage(`Скачиваю ${entry.title}…`);
    try {
      await api(`/api/model-catalog/${entry.key}/install`, {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({ confirm: true }),
      });
      setMessage(`${entry.title}: готово`);
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось скачать");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="panel">
      <div className="panel-title">
        <HardDriveDownload size={19} />
        <h2>Локальные модели</h2>
      </div>
      {message && <p className="notice" role="status">{message}</p>}
      <div className="model-catalog">
        {entries.map((entry) => (
          <article className="model-entry" key={entry.key}>
            <div>
              <strong>
                {entry.installed ? <Check size={15} className="ok-icon" /> : null} {entry.title}
              </strong>
              <small>{entry.purpose}</small>
              <small>
                ~{sizeLabel(entry.approx_size_mb)} · {entry.target_dir}
                {entry.installed ? " · установлено" : entry.files_missing.length ? ` · нет: ${entry.files_missing.join(", ")}` : ""}
              </small>
            </div>
            {entry.installable_in_app && !entry.installed ? (
              <button disabled={busy === entry.key} onClick={() => install(entry)}>
                <Download size={15} /> Скачать
              </button>
            ) : (
              <code className="install-command" title="Скопируйте и выполните в PowerShell">
                {entry.install_command}
              </code>
            )}
          </article>
        ))}
        {!entries.length && <p className="empty">Каталог моделей загружается…</p>}
      </div>
    </div>
  );
}
