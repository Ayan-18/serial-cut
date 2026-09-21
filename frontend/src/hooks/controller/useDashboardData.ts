import { useState } from "react";

import { api, jsonHeaders } from "../../api";
import type {
  CacheInfo,
  CheckItem,
  Episode,
  ExportItem,
  ImportResult,
  Job,
  JobStage,
  ModelDiagnostics,
  QueueData,
  RuntimeSettings,
  Season,
} from "../../types";
import { errorMessage, stageLabel } from "../../utils";

export type UseDashboardDataParams = {
  setMessage: (message: string) => void;
};

/**
 * Seasons / episodes / queue / settings / diagnostics / cache / exports.
 * Every action here only performs its own API call, updates its own state and
 * sets the status message — it deliberately does NOT re-fetch the queue or the
 * candidate list afterwards. That cross-cutting "reload after a queue action"
 * behaviour stays in the orchestrator (`useSerialCutsController`), which wraps
 * these functions with `refresh()` / `refreshActivity()` as needed.
 */
export function useDashboardData({ setMessage }: UseDashboardDataParams) {
  const [rootPath, setRootPath] = useState("");
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [checks, setChecks] = useState<CheckItem[]>([]);
  const [queue, setQueue] = useState<QueueData | null>(null);
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [diagnostics, setDiagnostics] = useState<ModelDiagnostics | null>(null);
  const [cacheInfo, setCacheInfo] = useState<CacheInfo | null>(null);
  const [exports, setExports] = useState<ExportItem[]>([]);
  const [jobStages, setJobStages] = useState<Record<number, JobStage[]>>({});

  async function runSystemCheck() {
    const [systemData, modelData] = await Promise.all([
      api<{ items: CheckItem[] }>("/api/system-check"),
      api<ModelDiagnostics>("/api/model-diagnostics"),
    ]);
    setChecks(systemData.items);
    setDiagnostics(modelData);
  }

  async function importSeason() {
    const data = await api<ImportResult>("/api/seasons/import", {
      method: "POST", headers: jsonHeaders, body: JSON.stringify({ root_path: rootPath }),
    });
    const errorNote = data.errors.length
      ? `, не прочитано: ${data.errors.length} (${data.errors.map((item) => item.file_name).join(", ")})`
      : "";
    setMessage(`Просканировано ${data.scanned}: добавлено ${data.created}, дубликатов ${data.skipped_duplicates}${errorNote}`);
  }

  async function enqueueSeason(seasonId: number, auto: boolean) {
    const jobs = await api<Job[]>(`/api/seasons/${seasonId}/enqueue`, {
      method: "POST", headers: jsonHeaders, body: JSON.stringify({ auto }),
    });
    setMessage(`В очередь добавлено задач: ${jobs.length}. Она начнёт работу автоматически.`);
  }

  async function enqueueEpisode(episode: Episode) {
    const job = await api<Job>(`/api/episodes/${episode.id}/enqueue`, { method: "POST" });
    setMessage(`Серия добавлена в очередь, задача №${job.id}`);
  }

  async function runQueueNext() {
    const result = await api<{ message: string }>("/api/queue/run-next", { method: "POST" });
    setMessage(result.message);
  }

  async function setPaused(paused: boolean) {
    const result = await api<{ state: string }>(paused ? "/api/queue/pause" : "/api/queue/resume", { method: "POST" });
    setMessage(`Очередь: ${result.state}`);
  }

  async function cancelJob(jobId: number) {
    const job = await api<Job>(`/api/jobs/${jobId}/cancel`, { method: "POST" });
    setMessage(job.status === "paused" ? "Задача остановлена." : "Остановка запрошена. Текущий шаг завершится безопасно.");
  }

  async function retryJob(jobId: number) {
    await api(`/api/jobs/${jobId}/retry`, { method: "POST" });
    setMessage("Задача снова поставлена в очередь");
  }

  async function retryJobStage(jobId: number, stageName: string) {
    await api<Job>(`/api/jobs/${jobId}/retry-stage`, {
      method: "POST", headers: jsonHeaders, body: JSON.stringify({ stage_name: stageName }),
    });
    setMessage(`Задача №${jobId} продолжит с этапа «${stageLabel(stageName)}»`);
    await loadJobStages(jobId);
  }

  async function runDirectStage(episode: Episode, kind: "media" | "candidates") {
    try {
      const resume_from_stage = kind === "media" ? "stage2_media" : "stage3_candidates";
      const job = await api<Job>(`/api/episodes/${episode.id}/enqueue`, {
        method: "POST", headers: jsonHeaders, body: JSON.stringify({ resume_from_stage }),
      });
      setMessage(kind === "media" ? `Медиа-анализ поставлен в очередь, задача №${job.id}` : `Поиск кандидатов поставлен в очередь, задача №${job.id}`);
    } catch (error) { setMessage(`Ошибка: ${errorMessage(error)}`); }
  }

  async function loadJobStages(jobId: number) {
    const stages = await api<JobStage[]>(`/api/jobs/${jobId}/stages`);
    setJobStages((current) => ({ ...current, [jobId]: stages }));
  }

  /** Returns false when there was nothing to save (no settings loaded yet). */
  async function saveSettings(): Promise<boolean> {
    if (!settings) return false;
    await api<RuntimeSettings>("/api/settings", { method: "PUT", headers: jsonHeaders, body: JSON.stringify(settings) });
    setMessage("Настройки сохранены");
    return true;
  }

  async function clearCache() {
    if (!window.confirm("Удалить временные WAV, proxy и данные анализа? Исходные серии и готовые ролики останутся на месте.")) return;
    const data = await api<CacheInfo>("/api/cache", { method: "DELETE", headers: jsonHeaders, body: JSON.stringify({ confirm: true }) });
    setCacheInfo(data);
    setMessage("Кэш очищен. Исходные видео и экспорты не изменены.");
  }

  function patchSettings(patch: Partial<RuntimeSettings>) {
    setSettings((current) => current ? { ...current, ...patch } : current);
  }

  function isEpisodeBusy(episodeId: number) {
    return (queue?.items ?? []).some((job) => job.episode_id === episodeId && ["queued", "running", "paused", "cancel_requested"].includes(job.status));
  }

  /** Returns false when the user declined the confirmation. */
  async function deleteJob(jobId: number): Promise<boolean> {
    if (!window.confirm(`Удалить задачу №${jobId} из очереди вместе с историей её этапов?`)) return false;
    await api(`/api/jobs/${jobId}`, { method: "DELETE" });
    setMessage(`Задача №${jobId} удалена`);
    return true;
  }

  async function autoExport(episodeId: number) {
    const job = await api<Job>(`/api/episodes/${episodeId}/enqueue`, {
      method: "POST", headers: jsonHeaders, body: JSON.stringify({ resume_from_stage: "auto_export", auto: true }),
    });
    setMessage(`Автоэкспорт поставлен в очередь, задача №${job.id}`);
  }

  return {
    rootPath, setRootPath,
    seasons, setSeasons,
    checks,
    queue, setQueue,
    settings, setSettings,
    diagnostics,
    cacheInfo, setCacheInfo,
    exports, setExports,
    jobStages,
    runSystemCheck,
    importSeason,
    enqueueSeason,
    enqueueEpisode,
    deleteJob,
    runQueueNext,
    setPaused,
    cancelJob,
    retryJob,
    retryJobStage,
    runDirectStage,
    loadJobStages,
    saveSettings,
    clearCache,
    patchSettings,
    isEpisodeBusy,
    autoExport,
  };
}
