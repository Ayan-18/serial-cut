import { FolderPlus, Sparkles, Trash2 } from "lucide-react";

import type { SerialCutsController } from "../hooks/useSerialCutsController";
import { QueuePanel } from "./QueuePanel";

type DashboardSectionProps = {
  controller: SerialCutsController;
};

/** "Сезоны" (import a season, kick off analysis) + the queue panel. */
export function DashboardSection({ controller }: DashboardSectionProps) {
  const {
    rootPath, setRootPath, seasons, importSeason, enqueueSeason, deleteSeason,
    queue, jobStages, runQueueNext, setPaused, loadJobStages, cancelJob, retryJob, retryJobStage, deleteJob,
  } = controller;

  return <section className="grid dashboard-grid">
    <div className="panel"><div className="panel-title"><FolderPlus size={19} /><h2>Сезоны</h2></div><div className="path-row"><input value={rootPath} onChange={(event) => setRootPath(event.target.value)} placeholder="D:\Сериалы\Название\Сезон 1" /><button onClick={importSeason}>Добавить</button></div><div className="season-list">
      {seasons.map((season) => <article className="season" key={season.id}><div><strong>{season.title}</strong><small>{season.episodes.length} серий</small></div><button onClick={() => enqueueSeason(season.id, false)}>Анализ сезона</button><button onClick={() => enqueueSeason(season.id, true)}><Sparkles size={16} /> Auto</button><button className="text-button danger" title="Удалить сезон" onClick={() => deleteSeason(season)}><Trash2 size={15} /></button></article>)}
      {!seasons.length && <p className="empty">Добавьте папку с сериями — исходные файлы останутся без изменений.</p>}
    </div></div>
    <QueuePanel queue={queue} jobStages={jobStages} onRunNext={runQueueNext} onSetPaused={setPaused} onLoadStages={loadJobStages} onCancel={cancelJob} onRetry={retryJob} onRetryStage={retryJobStage} onDelete={deleteJob} />
  </section>;
}
