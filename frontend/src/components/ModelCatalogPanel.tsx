import { useEffect, useRef, useState } from "react";
import { Check, Download, HardDriveDownload } from "lucide-react";

import { api, jsonHeaders } from "../api";
import type { ModelCatalogEntry, ModelInstallProgress } from "../types";

function sizeLabel(mb: number) {
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} ГБ` : `${mb} МБ`;
}

function bytesLabel(bytes: number) {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} МБ` : `${(bytes / 1024).toFixed(0)} КБ`;
}

export function ModelCatalogPanel() {
  const [entries, setEntries] = useState<ModelCatalogEntry[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [progress, setProgress] = useState<ModelInstallProgress | null>(null);
  const [message, setMessage] = useState("");
  const pollRef = useRef<number | null>(null);

  async function load() {
    try {
      setEntries(await api<ModelCatalogEntry[]>("/api/model-catalog"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Каталог моделей недоступен");
    }
  }

  useEffect(() => {
    load();
    return () => {
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
    };
  }, []);

  function watch(key: string) {
    if (pollRef.current !== null) window.clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      try {
        const state = await api<ModelInstallProgress>(`/api/model-catalog/${key}/install-progress`);
        setProgress(state);
        if (state.status === "done" || state.status === "error") {
          window.clearInterval(pollRef.current!);
          pollRef.current = null;
          setBusy(null);
          setMessage(state.status === "done" ? `${state.detail}` : `Ошибка: ${state.detail}`);
          await load();
        }
      } catch {
        /* transient — keep polling */
      }
    }, 800);
  }

  async function install(entry: ModelCatalogEntry) {
    if (!window.confirm(`Скачать «${entry.title}» (~${sizeLabel(entry.approx_size_mb)}) в ${entry.target_dir}?`)) return;
    setBusy(entry.key);
    setProgress({ key: entry.key, status: "running", received_bytes: 0, total_bytes: 0, detail: entry.title });
    setMessage(`Скачиваю ${entry.title}…`);
    try {
      await api(`/api/model-catalog/${entry.key}/install`, {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({ confirm: true }),
      });
      watch(entry.key);
    } catch (error) {
      setBusy(null);
      setProgress(null);
      setMessage(error instanceof Error ? error.message : "Не удалось начать загрузку");
    }
  }

  return (
    <div className="panel">
      <div className="panel-title">
        <HardDriveDownload size={19} />
        <h2>Локальные модели</h2>
      </div>
      {message && <p className="notice" role="status">{message}</p>}
      {progress?.status === "running" && (
        <div className="model-progress">
          <progress value={progress.total_bytes ? progress.received_bytes : undefined} max={progress.total_bytes || undefined} />
          <small>
            {progress.detail}: {bytesLabel(progress.received_bytes)}
            {progress.total_bytes ? ` / ${bytesLabel(progress.total_bytes)}` : ""}
          </small>
        </div>
      )}
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
              <button disabled={busy !== null} onClick={() => install(entry)}>
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
