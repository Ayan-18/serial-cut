import { ListVideo, Trash2 } from "lucide-react";

import type { SerialCutsController } from "../hooks/useSerialCutsController";
import { formatBytes, stageLabel } from "../utils";

type EpisodesSectionProps = {
  controller: SerialCutsController;
};

/** "Серии": the flat list of episodes across every imported season. */
export function EpisodesSection({ controller }: EpisodesSectionProps) {
  const { seasons, isEpisodeBusy, enqueueEpisode, runDirectStage, loadCandidates, autoExport, deleteEpisode } = controller;

  return <section className="panel section-gap"><div className="panel-title"><ListVideo size={19} /><h2>Серии</h2></div><div className="episodes">{seasons.flatMap((season) => season.episodes).map((episode) => { const busy = isEpisodeBusy(episode.id); return <article className="episode" key={episode.id}><div><strong>{episode.file_name}</strong><small>{busy ? "Обрабатывается в очереди" : stageLabel(episode.stage)}</small></div><span>{formatBytes(episode.size_bytes)}</span><span>{episode.width && episode.height ? `${episode.width}×${episode.height}` : "без метаданных"}</span><button disabled={busy} onClick={() => enqueueEpisode(episode)}>В очередь</button><button className="secondary" disabled={busy} onClick={() => runDirectStage(episode, "media")}>Только медиа</button><button className="secondary" disabled={busy} onClick={() => runDirectStage(episode, "candidates")}>Только кандидаты</button><button onClick={() => loadCandidates(episode.id)}>Открыть</button><button className="secondary" disabled={busy} onClick={() => autoExport(episode.id)}>Auto export</button><button className="text-button danger" disabled={busy} title="Удалить серию" onClick={() => deleteEpisode(episode)}><Trash2 size={15} /></button></article>; })}</div></section>;
}
