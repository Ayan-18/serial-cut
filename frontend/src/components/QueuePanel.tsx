import { Pause, Play, Server, SkipForward } from "lucide-react";
import type { JobStage, QueueData } from "../types";
import { elapsedFrom, formatEta, jobLabel, stageLabel, statusLabel } from "../utils";

type QueuePanelProps = {
  queue: QueueData | null;
  jobStages: Record<number, JobStage[]>;
  onRunNext: () => void;
  onSetPaused: (paused: boolean) => void;
  onLoadStages: (jobId: number) => void;
  onCancel: (jobId: number) => void;
  onRetry: (jobId: number) => void;
  onRetryStage: (jobId: number, stageName: string) => void;
  onDelete: (jobId: number) => void;
};

export function QueuePanel({
  queue, jobStages, onRunNext, onSetPaused, onLoadStages, onCancel, onRetry, onRetryStage, onDelete,
}: QueuePanelProps) {
  return <div className="panel">
    <div className="panel-title"><Server size={19} /><h2>Очередь</h2><span className={queue?.snapshot.paused ? "badge warn" : "badge ok"}>{queue?.snapshot.paused ? "пауза" : "авто"}</span></div>
    <div className="queue-actions">
      <button title="Взять следующую задачу из очереди прямо сейчас, не дожидаясь фонового воркера" onClick={onRunNext}><SkipForward size={16} /> Следующая</button>
      {queue?.snapshot.paused
        ? <button title="Возобновить автоматическую обработку очереди" onClick={() => onSetPaused(false)}><Play size={16} /> Продолжить</button>
        : <button className="secondary" title="Остановить автоматическую обработку — текущая задача доработает до конца" onClick={() => onSetPaused(true)}><Pause size={16} /> Пауза</button>}
    </div>
    <div className="queue-stats"><span><strong>{queue?.snapshot.queued ?? 0}</strong> ожидают</span><span><strong>{queue?.snapshot.running ?? 0}</strong> работают</span><span><strong>{queue?.snapshot.failed ?? 0}</strong> ошибок</span><span><strong>{formatEta(queue?.snapshot.eta_seconds)}</strong> ETA</span></div>
    <div className="job-list">{(queue?.items ?? []).slice(0, 6).map((job) => <article className="job" key={job.id}>
      <div><strong>№{job.id} · {jobLabel(job.kind)}</strong><span>{stageLabel(job.current_stage)} · {statusLabel(job.status)}{job.status === "running" ? ` · ${elapsedFrom(job.started_at ?? job.updated_at)}` : ""}</span></div>
      <div className={`progress ${job.status === "running" ? "active" : ""}`}><i style={{ width: `${Math.round(job.progress * 100)}%` }} /></div>
      {job.progress_message && <small>{job.progress_message}</small>}
      {job.error_message && <small className="error-text">{job.error_message}</small>}
      <div className="job-actions"><button className="text-button" onClick={() => onLoadStages(job.id)}>Этапы</button>{["queued", "running", "cancel_requested"].includes(job.status) && <button className="text-button danger" onClick={() => onCancel(job.id)}>Остановить</button>}{["failed", "paused"].includes(job.status) && <button className="text-button" onClick={() => onRetry(job.id)}>{job.status === "paused" ? "Продолжить" : "Повторить"}</button>}{!["running", "cancel_requested"].includes(job.status) && <button className="text-button danger" onClick={() => onDelete(job.id)}>Удалить</button>}</div>
      {jobStages[job.id] && <ol className="job-timeline">{jobStages[job.id].map((stage) => <li key={stage.id}><span className={`dot ${stage.status === "completed" ? "ok" : stage.status === "failed" ? "fail" : ""}`} /><strong>{stageLabel(stage.name)}</strong><small>{statusLabel(stage.status)}{stage.error_message ? ` · ${stage.error_message}` : ""}</small><button className="text-button" disabled={["queued", "running", "cancel_requested"].includes(job.status)} onClick={() => onRetryStage(job.id, stage.name)}>Отсюда</button></li>)}</ol>}
    </article>)}</div>
  </div>;
}
