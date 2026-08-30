import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Check, Clapperboard, FolderOpen, FolderPlus, ListFilter, ListVideo, LoaderCircle, Pause, Play, RefreshCcw, RotateCcw, Save, Server, Sparkles, Trash2, WandSparkles, X } from "lucide-react";
import "./styles.css";

type Episode = { id: number; file_name: string; file_path: string; stage: string; size_bytes: number; duration_seconds: number | null; width: number | null; height: number | null; fps: number | null };
type Season = { id: number; title: string; root_path: string; episodes: Episode[] };
type CheckItem = { name: string; ok: boolean; message: string };
type Job = { id: number; episode_id: number | null; kind: string; status: string; current_stage: string | null; progress: number; error_message: string | null; created_at: string; updated_at: string };
type QueueData = { snapshot: { queued: number; running: number; failed: number; paused: boolean; eta_seconds: number | null }; items: Job[] };
type RuntimeSettings = {
  cache_dir: string; output_dir: string; quality_profile: "fast" | "balanced" | "quality";
  min_clip_seconds: number; max_clip_seconds: number; auto_mode_enabled: boolean; background_queue_enabled: boolean;
  auto_score_threshold: number; max_clips_per_episode: number; render_preset: "youtube_shorts" | "instagram_reels";
  render_use_nvenc: boolean; render_loudnorm_two_pass: boolean; subtitle_font_name: string; subtitle_font_size: number;
  asr_adapter: "stub" | "faster-whisper"; llm_adapter: "stub" | "llama-cpp-http"; llm_base_url: string;
};
type Candidate = {
  id: number; episode_id: number; start_time: number; end_time: number; title: string; description: string;
  moment_type: string; score: number; scores_json: Record<string, number>; rationale: string; problems_json: string[];
  crop_mode: "auto-follow" | "center-crop" | "blurred-background"; crop_offset_x: number; crop_scale: number;
  thumbnail_path: string | null; status: string;
};
type CandidateEdit = { start: string; end: string; crop: Candidate["crop_mode"]; offset: number; scale: number };
type Subtitle = { id?: number | null; start_time: number; end_time: number; text: string; speaker_label?: string | null };
type ExportItem = { id: number; candidate_id: number; output_path: string; cover_path: string | null; include_subtitles: boolean; preset_name: string; status: string };
type ModelDiagnostics = { asr_adapter: string; asr_ready: boolean; llm_adapter: string; llm_ready: boolean; llm_url: string; details: string[] };
type CacheInfo = { cache_dir: string; files: number; bytes: number };
type BlockingProgress = { kind: "media" | "candidates"; episodeId: number; fileName: string; startedAt: number };

function App() {
  const [rootPath, setRootPath] = useState("");
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [checks, setChecks] = useState<CheckItem[]>([]);
  const [queue, setQueue] = useState<QueueData | null>(null);
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [diagnostics, setDiagnostics] = useState<ModelDiagnostics | null>(null);
  const [cacheInfo, setCacheInfo] = useState<CacheInfo | null>(null);
  const [exports, setExports] = useState<ExportItem[]>([]);
  const [candidates, setCandidates] = useState<Record<number, Candidate[]>>({});
  const [selectedEpisodeId, setSelectedEpisodeId] = useState<number | null>(null);
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(null);
  const [edits, setEdits] = useState<Record<number, CandidateEdit>>({});
  const [subtitles, setSubtitles] = useState<Subtitle[]>([]);
  const [subtitleBusy, setSubtitleBusy] = useState(false);
  const [candidateFilter, setCandidateFilter] = useState("all");
  const [candidateSort, setCandidateSort] = useState("score");
  const [message, setMessage] = useState("");
  const [blockingProgress, setBlockingProgress] = useState<BlockingProgress | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [videoTime, setVideoTime] = useState(0);
  const videoRef = useRef<HTMLVideoElement>(null);
  const backgroundVideoRef = useRef<HTMLVideoElement>(null);

  async function api<T>(url: string, init?: RequestInit): Promise<T> {
    const response = await fetch(url, init);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail ?? "Ошибка запроса");
    return data;
  }

  async function refresh() {
    const [seasonData, queueData, settingsData, exportData, cacheData] = await Promise.all([
      api<Season[]>("/api/seasons"), api<QueueData>("/api/jobs"), api<RuntimeSettings>("/api/settings"),
      api<ExportItem[]>("/api/exports"), api<CacheInfo>("/api/cache")
    ]);
    setSeasons(seasonData); setQueue(queueData); setSettings(settingsData); setExports(exportData); setCacheInfo(cacheData);
  }

  async function refreshActivity() {
    const [queueData, exportData] = await Promise.all([api<QueueData>("/api/jobs"), api<ExportItem[]>("/api/exports")]);
    setQueue(queueData); setExports(exportData);
    if (selectedEpisodeId && !queueData.items.some((job) => job.status === "running")) await loadCandidates(selectedEpisodeId, false);
  }

  async function runSystemCheck() {
    const [systemData, modelData] = await Promise.all([api<{ items: CheckItem[] }>("/api/system-check"), api<ModelDiagnostics>("/api/model-diagnostics")]);
    setChecks(systemData.items); setDiagnostics(modelData);
  }

  async function importSeason() {
    try {
      const data = await api<{ created: number; skipped_duplicates: number }>("/api/seasons/import", { method: "POST", headers: jsonHeaders, body: JSON.stringify({ root_path: rootPath }) });
      setMessage(`Добавлено: ${data.created}, дубликатов: ${data.skipped_duplicates}`); await refresh();
    } catch (error) { setMessage(errorMessage(error)); }
  }

  async function enqueueSeason(seasonId: number, auto: boolean) {
    const jobs = await api<Job[]>(`/api/seasons/${seasonId}/enqueue`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({ auto }) });
    setMessage(`В очередь добавлено задач: ${jobs.length}. Она начнёт работу автоматически.`); await refreshActivity();
  }

  async function enqueueEpisode(episode: Episode) {
    const job = await api<Job>(`/api/episodes/${episode.id}/enqueue`, { method: "POST" });
    setMessage(`Серия добавлена в очередь, задача №${job.id}`); await refreshActivity();
  }

  async function runQueueNext() {
    const result = await api<{ message: string }>("/api/queue/run-next", { method: "POST" }); setMessage(result.message); await refreshActivity();
  }

  async function setPaused(paused: boolean) {
    const result = await api<{ state: string }>(paused ? "/api/queue/pause" : "/api/queue/resume", { method: "POST" });
    setMessage(`Очередь: ${result.state}`); await refreshActivity();
  }

  async function cancelJob(jobId: number) {
    await api(`/api/jobs/${jobId}/cancel`, { method: "POST" }); setMessage("Остановка запрошена. Текущий шаг завершится безопасно."); await refreshActivity();
  }

  async function retryJob(jobId: number) {
    await api(`/api/jobs/${jobId}/retry`, { method: "POST" }); setMessage("Задача снова поставлена в очередь"); await refreshActivity();
  }

  async function runDirectStage(episode: Episode, kind: "media" | "candidates") {
    if (blockingProgress) return;
    setBlockingProgress({ kind, episodeId: episode.id, fileName: episode.file_name, startedAt: Date.now() }); setElapsedSeconds(0);
    setMessage(kind === "media" ? "Медиа-анализ начат" : "Поиск кандидатов начат");
    try {
      if (kind === "media") {
        const data = await api<{ transcript_segments: number; scenes: number }>(`/api/episodes/${episode.id}/stage2`, { method: "POST" });
        setMessage(`Медиа готово: сегментов ${data.transcript_segments}, сцен ${data.scenes}`);
      } else {
        const data = await api<{ candidates: number }>(`/api/episodes/${episode.id}/stage3`, { method: "POST" });
        setMessage(`Кандидаты готовы: ${data.candidates}`); await loadCandidates(episode.id);
      }
    } catch (error) { setMessage(`Ошибка: ${errorMessage(error)}`); }
    finally { setBlockingProgress(null); await refresh().catch(() => undefined); }
  }

  async function loadCandidates(episodeId: number, selectEpisode = true) {
    const data = await api<Candidate[]>(`/api/episodes/${episodeId}/candidates`);
    setCandidates((current) => ({ ...current, [episodeId]: data }));
    if (selectEpisode) setSelectedEpisodeId(episodeId);
    setEdits((current) => { const next = { ...current }; for (const candidate of data) next[candidate.id] ??= editFromCandidate(candidate); return next; });
    if (selectedCandidate?.episode_id === episodeId) { const updated = data.find((item) => item.id === selectedCandidate.id); if (updated) setSelectedCandidate(updated); }
  }

  async function openCandidate(candidate: Candidate, play = false) {
    setSelectedCandidate(candidate); setSubtitleBusy(true);
    try {
      setSubtitles(await api<Subtitle[]>(`/api/candidates/${candidate.id}/subtitles`));
      window.setTimeout(() => { const player = videoRef.current; if (!player) return; player.currentTime = Number((edits[candidate.id] ?? editFromCandidate(candidate)).start); if (play) player.play().catch(() => undefined); }, 0);
    } finally { setSubtitleBusy(false); }
  }

  async function reviewCandidate(candidate: Candidate, decision: "approve" | "reject") {
    const edit = edits[candidate.id] ?? editFromCandidate(candidate);
    await api(`/api/candidates/${candidate.id}/review`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({
      decision, adjusted_start_time: Number(edit.start), adjusted_end_time: Number(edit.end), crop_mode: edit.crop,
      crop_offset_x: edit.offset, crop_scale: edit.scale
    }) });
    setMessage(decision === "approve" ? "Кандидат принят и правки сохранены" : "Кандидат отклонён"); await loadCandidates(candidate.episode_id);
  }

  async function autoCrop(candidate: Candidate) {
    setMessage("Ищем лица в выбранном отрывке…");
    const data = await api<{ crop_offset_x: number; faces_detected: number }>(`/api/candidates/${candidate.id}/auto-crop`, { method: "POST" });
    setCandidateEdit(candidate.id, { crop: "auto-follow", offset: data.crop_offset_x });
    setMessage(data.faces_detected ? `Автокадрирование: найдено лиц ${data.faces_detected}` : "Лица не найдены, оставлен центр кадра");
  }

  async function saveSubtitles() {
    if (!selectedCandidate) return; setSubtitleBusy(true);
    try {
      const saved = await api<Subtitle[]>(`/api/candidates/${selectedCandidate.id}/subtitles`, { method: "PUT", headers: jsonHeaders, body: JSON.stringify({ subtitles }) });
      setSubtitles(saved); setMessage("Субтитры сохранены");
    } catch (error) { setMessage(`Субтитры не сохранены: ${errorMessage(error)}`); }
    finally { setSubtitleBusy(false); }
  }

  async function resetSubtitles() {
    if (!selectedCandidate) return; setSubtitleBusy(true);
    try { setSubtitles(await api<Subtitle[]>(`/api/candidates/${selectedCandidate.id}/subtitles`, { method: "DELETE" })); setMessage("Субтитры пересобраны из распознанных слов"); }
    finally { setSubtitleBusy(false); }
  }

  async function renderCandidate(candidate: Candidate, includeSubtitles: boolean) {
    const edit = edits[candidate.id] ?? editFromCandidate(candidate);
    await api(`/api/candidates/${candidate.id}/review`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({ decision: "approve", adjusted_start_time: Number(edit.start), adjusted_end_time: Number(edit.end), crop_mode: edit.crop, crop_offset_x: edit.offset, crop_scale: edit.scale }) });
    const job = await api<Job>(`/api/candidates/${candidate.id}/render-job`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({ include_subtitles: includeSubtitles, use_nvenc: settings?.render_use_nvenc ?? null, preset_name: settings?.render_preset, loudnorm_two_pass: settings?.render_loudnorm_two_pass ?? null, force_rerender: true }) });
    setMessage(`Рендер поставлен в очередь, задача №${job.id}. Можно продолжать работу.`); await refreshActivity();
  }

  async function autoExport(episodeId: number) {
    setMessage("Автоэкспорт выполняется…");
    const data = await api<{ rendered: number }>(`/api/episodes/${episodeId}/auto-export`, { method: "POST", headers: jsonHeaders, body: "{}" });
    setMessage(`Автоэкспорт: готово ${data.rendered}`); await loadCandidates(episodeId); await refresh();
  }

  async function saveSettings() {
    if (!settings) return;
    await api<RuntimeSettings>("/api/settings", { method: "PUT", headers: jsonHeaders, body: JSON.stringify(settings) });
    setMessage("Настройки сохранены"); await refreshActivity();
  }

  async function clearCache() {
    if (!window.confirm("Удалить временные WAV, proxy и данные анализа? Исходные серии и готовые ролики останутся на месте.")) return;
    const data = await api<CacheInfo>("/api/cache", { method: "DELETE", headers: jsonHeaders, body: JSON.stringify({ confirm: true }) });
    setCacheInfo(data); setMessage("Кэш очищен. Исходные видео и экспорты не изменены.");
  }

  function setCandidateEdit(candidateId: number, patch: Partial<CandidateEdit>) {
    setEdits((current) => ({ ...current, [candidateId]: { ...current[candidateId], ...patch } }));
  }
  function patchSettings(patch: Partial<RuntimeSettings>) { setSettings((current) => current ? { ...current, ...patch } : current); }
  function updateSubtitle(index: number, patch: Partial<Subtitle>) { setSubtitles((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item)); }
  function onVideoTimeUpdate() { const player = videoRef.current; const background = backgroundVideoRef.current; if (!player) return; setVideoTime(player.currentTime); if (background && Math.abs(background.currentTime - player.currentTime) > 0.2) background.currentTime = player.currentTime; if (selectedCandidate) { const end = Number((edits[selectedCandidate.id] ?? editFromCandidate(selectedCandidate)).end); if (player.currentTime >= end) player.pause(); } }
  function isEpisodeBusy(episodeId: number) { return (queue?.items ?? []).some((job) => job.episode_id === episodeId && ["queued", "running", "paused", "cancel_requested"].includes(job.status)); }

  useEffect(() => { refresh().catch((error) => setMessage(errorMessage(error))); runSystemCheck().catch((error) => setMessage(errorMessage(error))); }, []);
  useEffect(() => { const timer = window.setInterval(() => refreshActivity().catch(() => undefined), 2500); return () => window.clearInterval(timer); }, [selectedEpisodeId]);
  useEffect(() => { if (!blockingProgress) return; const update = () => setElapsedSeconds(Math.floor((Date.now() - blockingProgress.startedAt) / 1000)); update(); const timer = window.setInterval(update, 1000); return () => window.clearInterval(timer); }, [blockingProgress]);

  const visibleCandidates = useMemo(() => {
    const items = [...(selectedEpisodeId ? candidates[selectedEpisodeId] ?? [] : [])];
    const filtered = candidateFilter === "all" ? items : items.filter((item) => item.status === candidateFilter);
    return filtered.sort(candidateSort === "time" ? (a, b) => a.start_time - b.start_time : (a, b) => b.score - a.score);
  }, [candidateFilter, candidateSort, candidates, selectedEpisodeId]);
  const activeSubtitle = selectedCandidate ? subtitles.find((item) => { const relative = videoTime - Number((edits[selectedCandidate.id] ?? editFromCandidate(selectedCandidate)).start); return relative >= item.start_time && relative <= item.end_time; }) : undefined;
  const selectedEdit = selectedCandidate ? edits[selectedCandidate.id] ?? editFromCandidate(selectedCandidate) : null;

  return <main className="app-shell">
    <section className="topbar"><div><h1>SerialCuts</h1><p>Локальная подготовка вертикальных клипов из серий</p></div><button className="icon-button" title="Обновить всё" onClick={() => refresh()}><RefreshCcw size={20} /></button></section>
    {message && <p className="notice" role="status">{message}</p>}
    {blockingProgress && <div className="processing-banner" role="status"><LoaderCircle className="spinner" size={24} /><div><strong>{blockingProgress.kind === "media" ? "Медиа-анализ" : "Поиск кандидатов"}: {blockingProgress.fileName}</strong><span>Приложение работает · прошло {formatElapsed(elapsedSeconds)}</span></div></div>}

    <section className="grid dashboard-grid">
      <div className="panel"><div className="panel-title"><FolderPlus size={19} /><h2>Сезоны</h2></div><div className="path-row"><input value={rootPath} onChange={(event) => setRootPath(event.target.value)} placeholder="D:\Сериалы\Название\Сезон 1" /><button onClick={importSeason}>Добавить</button></div><div className="season-list">
        {seasons.map((season) => <article className="season" key={season.id}><div><strong>{season.title}</strong><small>{season.episodes.length} серий</small></div><button onClick={() => enqueueSeason(season.id, false)}>Анализ сезона</button><button onClick={() => enqueueSeason(season.id, true)}><Sparkles size={16} /> Auto</button></article>)}
        {!seasons.length && <p className="empty">Добавьте папку с сериями — исходные файлы останутся без изменений.</p>}
      </div></div>
      <div className="panel"><div className="panel-title"><Server size={19} /><h2>Очередь</h2><span className={queue?.snapshot.paused ? "badge warn" : "badge ok"}>{queue?.snapshot.paused ? "пауза" : "авто"}</span></div><div className="queue-actions"><button className="icon-button" title="Выполнить следующую сейчас" onClick={runQueueNext}><Play size={18} /></button><button className="icon-button secondary" title="Пауза" onClick={() => setPaused(true)}><Pause size={18} /></button><button className="icon-button" title="Продолжить" onClick={() => setPaused(false)}><Play size={18} /></button></div>
        <div className="queue-stats"><span><strong>{queue?.snapshot.queued ?? 0}</strong> ожидают</span><span><strong>{queue?.snapshot.running ?? 0}</strong> работают</span><span><strong>{queue?.snapshot.failed ?? 0}</strong> ошибок</span><span><strong>{formatEta(queue?.snapshot.eta_seconds)}</strong> ETA</span></div>
        <div className="job-list">{(queue?.items ?? []).slice(0, 6).map((job) => <article className="job" key={job.id}><div><strong>№{job.id} · {jobLabel(job.kind)}</strong><span>{stageLabel(job.current_stage)} · {statusLabel(job.status)}{job.status === "running" ? ` · ${elapsedFrom(job.updated_at)}` : ""}</span></div><div className={`progress ${job.status === "running" ? "active" : ""}`}><i style={{ width: `${Math.round(job.progress * 100)}%` }} /></div>{job.error_message && <small className="error-text">{job.error_message}</small>}<div className="job-actions">{["queued", "running", "paused", "cancel_requested"].includes(job.status) && <button className="text-button danger" onClick={() => cancelJob(job.id)}>Остановить</button>}{job.status === "failed" && <button className="text-button" onClick={() => retryJob(job.id)}>Повторить</button>}</div></article>)}</div>
      </div>
    </section>

    <section className="panel section-gap"><div className="panel-title"><ListVideo size={19} /><h2>Серии</h2></div><div className="episodes">{seasons.flatMap((season) => season.episodes).map((episode) => { const busy = isEpisodeBusy(episode.id); return <article className="episode" key={episode.id}><div><strong>{episode.file_name}</strong><small>{busy ? "Обрабатывается в очереди" : stageLabel(episode.stage)}</small></div><span>{formatBytes(episode.size_bytes)}</span><span>{episode.width && episode.height ? `${episode.width}×${episode.height}` : "без метаданных"}</span><button disabled={busy} onClick={() => enqueueEpisode(episode)}>В очередь</button><button className="secondary" disabled={blockingProgress !== null || busy} onClick={() => runDirectStage(episode, "media")}>Только медиа</button><button className="secondary" disabled={blockingProgress !== null || busy} onClick={() => runDirectStage(episode, "candidates")}>Только кандидаты</button><button onClick={() => loadCandidates(episode.id)}>Открыть</button><button className="secondary" disabled={busy} onClick={() => autoExport(episode.id)}>Auto export</button></article>; })}</div></section>

    {selectedEpisodeId && <section className="workspace section-gap">
      <div className="panel candidate-panel"><div className="panel-title"><Clapperboard size={19} /><h2>Кандидаты</h2></div><div className="candidate-toolbar"><label><ListFilter size={16} /><select value={candidateFilter} onChange={(event) => setCandidateFilter(event.target.value)}><option value="all">Все статусы</option><option value="new">Новые</option><option value="approved">Принятые</option><option value="rejected">Отклонённые</option><option value="rendered">Готовые</option></select></label><select value={candidateSort} onChange={(event) => setCandidateSort(event.target.value)}><option value="score">Сначала лучшие</option><option value="time">По времени</option></select></div>
        <div className="candidate-list">{visibleCandidates.map((candidate) => { const edit = edits[candidate.id] ?? editFromCandidate(candidate); const busy = isEpisodeBusy(candidate.episode_id); return <article className={`candidate ${selectedCandidate?.id === candidate.id ? "selected" : ""}`} key={candidate.id}><button className="candidate-main" onClick={() => openCandidate(candidate, true)}><span className="score">{candidate.score}</span><span><strong>{candidate.title}</strong><small>{candidate.moment_type} · {statusLabel(candidate.status)} · {formatRange(candidate.start_time, candidate.end_time)}</small></span><Play size={18} /></button><p>{candidate.description}</p>{!!candidate.problems_json.length && <small className="error-text">{candidate.problems_json.join(" · ")}</small>}<div className="compact-edit"><label>Начало<input value={edit.start} onChange={(event) => setCandidateEdit(candidate.id, { start: event.target.value })} /></label><label>Конец<input value={edit.end} onChange={(event) => setCandidateEdit(candidate.id, { end: event.target.value })} /></label><select value={edit.crop} onChange={(event) => setCandidateEdit(candidate.id, { crop: event.target.value as Candidate["crop_mode"] })}><option value="blurred-background">Фон с размытием</option><option value="center-crop">Центр</option><option value="auto-follow">По лицам</option></select></div><div className="candidate-actions"><button disabled={busy} onClick={() => reviewCandidate(candidate, "approve")}><Check size={16} /> Принять</button><button className="secondary" disabled={busy} onClick={() => reviewCandidate(candidate, "reject")}><X size={16} /> Отклонить</button><button disabled={busy} onClick={() => renderCandidate(candidate, true)}>Рендер с субтитрами</button><button className="secondary" disabled={busy} onClick={() => renderCandidate(candidate, false)}>Без субтитров</button></div></article>; })}{!visibleCandidates.length && <p className="empty">Кандидатов с выбранным фильтром нет.</p>}</div>
      </div>
      <div className="panel editor-panel"><div className="panel-title"><WandSparkles size={19} /><h2>Предпросмотр и редактор</h2></div>{selectedCandidate && selectedEdit ? <>
        <div className={`preview-frame ${selectedEdit.crop}`}><video className="preview-background" ref={backgroundVideoRef} muted src={`/api/episodes/${selectedEpisodeId}/proxy`} /><video className="preview-foreground" ref={videoRef} controls src={`/api/episodes/${selectedEpisodeId}/proxy`} onTimeUpdate={onVideoTimeUpdate} onPlay={() => backgroundVideoRef.current?.play().catch(() => undefined)} onPause={() => backgroundVideoRef.current?.pause()} style={{ objectPosition: `${50 + selectedEdit.offset * 35}% 50%`, transform: `scale(${selectedEdit.scale})` }} />{activeSubtitle && <div className="subtitle-preview"><small>{activeSubtitle.speaker_label}</small>{activeSubtitle.text}</div>}</div>
        <div className="preview-summary"><strong>{selectedCandidate.title}</strong><span>{formatRange(Number(selectedEdit.start), Number(selectedEdit.end))}</span></div>
        <div className="crop-controls"><label>Смещение по горизонтали <span>{selectedEdit.offset.toFixed(2)}</span><input type="range" min="-1" max="1" step="0.02" value={selectedEdit.offset} onChange={(event) => setCandidateEdit(selectedCandidate.id, { offset: Number(event.target.value) })} /></label><label>Масштаб <span>{selectedEdit.scale.toFixed(2)}×</span><input type="range" min="1" max="2" step="0.02" value={selectedEdit.scale} onChange={(event) => setCandidateEdit(selectedCandidate.id, { scale: Number(event.target.value) })} /></label><button disabled={isEpisodeBusy(selectedCandidate.episode_id)} onClick={() => autoCrop(selectedCandidate)}><WandSparkles size={16} /> Найти лица</button></div>
        <div className="subtitle-header"><div><h3>Субтитры</h3><small>Время указано относительно начала клипа.</small></div><div><button className="icon-button secondary" title="Пересобрать" disabled={subtitleBusy || isEpisodeBusy(selectedCandidate.episode_id)} onClick={resetSubtitles}><RotateCcw size={17} /></button><button onClick={saveSubtitles} disabled={subtitleBusy || isEpisodeBusy(selectedCandidate.episode_id)}><Save size={16} /> Сохранить</button></div></div>
        <div className="subtitle-list">{subtitles.map((subtitle, index) => <article className="subtitle-row" key={`${subtitle.id ?? "new"}-${index}`}><input type="number" step="0.05" value={subtitle.start_time} onChange={(event) => updateSubtitle(index, { start_time: Number(event.target.value) })} /><input type="number" step="0.05" value={subtitle.end_time} onChange={(event) => updateSubtitle(index, { end_time: Number(event.target.value) })} /><textarea rows={2} value={subtitle.text} onChange={(event) => updateSubtitle(index, { text: event.target.value })} /><input placeholder="Говорящий" value={subtitle.speaker_label ?? ""} onChange={(event) => updateSubtitle(index, { speaker_label: event.target.value || null })} /><button className="icon-button danger" title="Удалить строку" onClick={() => setSubtitles((current) => current.filter((_, itemIndex) => itemIndex !== index))}><Trash2 size={16} /></button></article>)}</div>
        <button className="secondary add-subtitle" onClick={() => setSubtitles((current) => [...current, { start_time: 0, end_time: 1, text: "Новая строка", speaker_label: null }])}>Добавить строку</button>
      </> : <p className="empty">Нажмите на кандидата, чтобы посмотреть только его отрывок и отредактировать кадр и субтитры.</p>}</div>
    </section>}

    <section className="panel section-gap"><div className="panel-title"><FolderOpen size={19} /><h2>Готовые ролики</h2><span className="badge">{exports.length}</span></div><div className="exports-grid">{exports.map((item) => <article className="export-card" key={item.id}>{item.cover_path ? <img src={`/api/exports/${item.id}/cover`} alt="Обложка клипа" /> : <div className="export-placeholder"><Clapperboard /></div>}<div><strong>Экспорт №{item.id}</strong><small>{item.preset_name} · {item.include_subtitles ? "с субтитрами" : "без субтитров"}</small><small title={item.output_path}>{item.output_path}</small></div><video controls preload="none" src={`/api/exports/${item.id}/file`} /><button onClick={() => api(`/api/exports/${item.id}/open-folder`, { method: "POST" })}><FolderOpen size={16} /> Открыть папку</button></article>)}{!exports.length && <p className="empty">После рендера готовые MP4 появятся здесь.</p>}</div></section>

    <section className="grid section-gap">
      <div className="panel"><div className="panel-title"><Server size={19} /><h2>Готовность системы</h2><button className="icon-button secondary" onClick={runSystemCheck}><RefreshCcw size={17} /></button></div><div className="checks">{checks.map((item) => <div className="check" key={item.name}><span className={item.ok ? "dot ok" : "dot fail"} /><strong>{item.name}</strong><span>{item.message}</span></div>)}{diagnostics && <><div className="check"><span className={diagnostics.asr_ready ? "dot ok" : "dot fail"} /><strong>Whisper</strong><span>{diagnostics.asr_adapter}</span></div><div className="check"><span className={diagnostics.llm_ready ? "dot ok" : "dot fail"} /><strong>Qwen</strong><span>{diagnostics.llm_adapter} · {diagnostics.details.at(-1)}</span></div></>}</div><div className="cache-card"><div><strong>Временные файлы</strong><small>{cacheInfo?.files ?? 0} файлов · {formatBytes(cacheInfo?.bytes ?? 0)}</small><small>{cacheInfo?.cache_dir}</small></div><button className="danger" onClick={clearCache}><Trash2 size={16} /> Очистить кэш</button></div></div>
      <div className="panel"><div className="panel-title"><Server size={19} /><h2>Настройки</h2></div>{settings && <div className="settings-sections">
        <section className="settings-section"><h3>Файлы</h3><div className="settings-grid"><SettingText title="Папка временных файлов" hint="Proxy, WAV и промежуточные данные; их можно безопасно удалить." value={settings.cache_dir} onChange={(value) => patchSettings({ cache_dir: value })} wide /><SettingText title="Папка готовых роликов" hint="Готовые MP4, обложки, субтитры и метаданные." value={settings.output_dir} onChange={(value) => patchSettings({ output_dir: value })} wide /></div></section>
        <section className="settings-section"><h3>Анализ и Auto</h3><div className="settings-grid"><label className="setting-field"><span>Профиль качества</span><select value={settings.quality_profile} onChange={(event) => patchSettings({ quality_profile: event.target.value as RuntimeSettings["quality_profile"] })}><option value="fast">Быстрый</option><option value="balanced">Сбалансированный</option><option value="quality">Качественный</option></select><small>Баланс скорости и тщательности локального анализа.</small></label><SettingNumber title="Минимальная длина, сек." hint="Короткий кандидат будет расширен." value={settings.min_clip_seconds} min={5} max={300} onChange={(value) => patchSettings({ min_clip_seconds: value })} /><SettingNumber title="Максимальная длина, сек." hint="Клип не выйдет за этот предел." value={settings.max_clip_seconds} min={5} max={300} onChange={(value) => patchSettings({ max_clip_seconds: value })} /><SettingNumber title="Порог Auto, баллы" hint="Auto принимает кандидатов с этой оценкой и выше." value={settings.auto_score_threshold} min={0} max={100} onChange={(value) => patchSettings({ auto_score_threshold: value })} /><SettingNumber title="Максимум клипов" hint="Лимит автоматического экспорта из серии." value={settings.max_clips_per_episode} min={1} max={20} onChange={(value) => patchSettings({ max_clips_per_episode: value })} /><SettingCheck title="Фоновая очередь" hint="Новые задачи запускаются сами." checked={settings.background_queue_enabled} onChange={(value) => patchSettings({ background_queue_enabled: value })} /><SettingCheck title="Auto по умолчанию" hint="Лучшие кандидаты принимаются и экспортируются." checked={settings.auto_mode_enabled} onChange={(value) => patchSettings({ auto_mode_enabled: value })} /></div></section>
        <section className="settings-section"><h3>Рендер и субтитры</h3><div className="settings-grid"><label className="setting-field"><span>Платформа</span><select value={settings.render_preset} onChange={(event) => patchSettings({ render_preset: event.target.value as RuntimeSettings["render_preset"] })}><option value="youtube_shorts">YouTube Shorts</option><option value="instagram_reels">Instagram Reels</option></select><small>Битрейт и параметры MP4.</small></label><SettingText title="Шрифт субтитров" hint="Шрифт, установленный в Windows." value={settings.subtitle_font_name} onChange={(value) => patchSettings({ subtitle_font_name: value })} /><SettingNumber title="Размер субтитров" hint="Обычно 36–52 для вертикального кадра." value={settings.subtitle_font_size} min={24} max={96} onChange={(value) => patchSettings({ subtitle_font_size: value })} /><SettingCheck title="NVIDIA NVENC" hint="Ускоряет рендер; при ошибке включится CPU." checked={settings.render_use_nvenc} onChange={(value) => patchSettings({ render_use_nvenc: value })} /><SettingCheck title="Точная громкость" hint="Два прохода: медленнее, но ровнее звук." checked={settings.render_loudnorm_two_pass} onChange={(value) => patchSettings({ render_loudnorm_two_pass: value })} /></div></section>
        <button className="settings-save" onClick={saveSettings}><Save size={17} /> Сохранить настройки</button>
      </div>}</div>
    </section>
  </main>;
}

const jsonHeaders = { "Content-Type": "application/json" };
function SettingText({ title, hint, value, onChange, wide = false }: { title: string; hint: string; value: string; onChange: (value: string) => void; wide?: boolean }) { return <label className={`setting-field ${wide ? "setting-field-wide" : ""}`}><span>{title}</span><input value={value} onChange={(event) => onChange(event.target.value)} /><small>{hint}</small></label>; }
function SettingNumber({ title, hint, value, min, max, onChange }: { title: string; hint: string; value: number; min: number; max: number; onChange: (value: number) => void }) { return <label className="setting-field"><span>{title}</span><input type="number" min={min} max={max} value={value} onChange={(event) => onChange(Number(event.target.value))} /><small>{hint}</small></label>; }
function SettingCheck({ title, hint, checked, onChange }: { title: string; hint: string; checked: boolean; onChange: (value: boolean) => void }) { return <label className="setting-checkbox"><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><span><strong>{title}</strong><small>{hint}</small></span></label>; }
function editFromCandidate(candidate: Candidate): CandidateEdit { return { start: candidate.start_time.toFixed(3), end: candidate.end_time.toFixed(3), crop: candidate.crop_mode, offset: candidate.crop_offset_x, scale: candidate.crop_scale }; }
function formatBytes(value: number) { if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(2)} GB`; if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)} MB`; if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`; return `${value} B`; }
function formatEta(value: number | null | undefined) { if (value == null) return "—"; if (value < 60) return `${Math.round(value)} сек`; return `${Math.round(value / 60)} мин`; }
function formatElapsed(value: number) { const hours = Math.floor(value / 3600); const minutes = Math.floor((value % 3600) / 60); const seconds = value % 60; const base = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`; return hours > 0 ? `${String(hours).padStart(2, "0")}:${base}` : base; }
function elapsedFrom(value: string) { const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000)); return formatElapsed(seconds); }
function formatRange(start: number, end: number) { return `${formatClock(start)}–${formatClock(end)} · ${(end - start).toFixed(1)} сек`; }
function formatClock(value: number) { const minutes = Math.floor(value / 60); const seconds = Math.floor(value % 60); return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`; }
function stageLabel(stage: string | null) { const labels: Record<string, string> = { discovered: "найдена", probed: "метаданные готовы", proxied: "proxy готов", transcribed: "речь распознана", scenes_detected: "сцены найдены", outlined: "сюжет разобран", candidates_generated: "кандидаты готовы", awaiting_review: "ждёт проверки", rendered: "ролик готов", stage2_media: "медиа и речь", stage3_candidates: "поиск кандидатов", auto_export: "автоэкспорт", render_clip: "рендер клипа", completed: "завершено" }; return stage ? labels[stage] ?? stage : "ожидание"; }
function statusLabel(status: string) { const labels: Record<string, string> = { queued: "в очереди", running: "выполняется", paused: "пауза", cancel_requested: "останавливается", failed: "ошибка", completed: "готово", new: "новый", approved: "принят", rejected: "отклонён", rendered: "готов" }; return labels[status] ?? status; }
function jobLabel(kind: string) { return kind === "render_clip" ? "рендер" : kind === "analyze_episode" ? "анализ серии" : kind; }
function errorMessage(error: unknown) { return error instanceof Error ? error.message : "Неизвестная ошибка"; }

createRoot(document.getElementById("root")!).render(<App />);
