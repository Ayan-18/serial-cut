import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { BookOpen, Check, Clapperboard, FolderOpen, FolderPlus, ListFilter, ListVideo, LoaderCircle, Pause, Play, RefreshCcw, RotateCcw, Save, Server, Sparkles, Trash2, UserRound, WandSparkles, X } from "lucide-react";
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
  subtitle_show_speaker_names: boolean;
  asr_adapter: "stub" | "faster-whisper"; llm_adapter: "stub" | "llama-cpp-http"; llm_base_url: string;
};
type Candidate = {
  id: number; episode_id: number; start_time: number; end_time: number; title: string; description: string;
  moment_type: string; score: number; scores_json: Record<string, number>; rationale: string; problems_json: string[];
  crop_mode: "auto-follow" | "center-crop" | "blurred-background"; crop_offset_x: number; crop_scale: number;
  thumbnail_path: string | null; status: string; story_order: number | null; story_role: string | null; continuity_note: string | null;
  crop_keyframes_json: { time: number; offset: number }[];
};
type CandidateEdit = { start: string; end: string; crop: Candidate["crop_mode"]; offset: number; scale: number };
type Subtitle = { id?: number | null; start_time: number; end_time: number; text: string; speaker_label?: string | null };
type ExportItem = { id: number; candidate_id: number; output_path: string; cover_path: string | null; include_subtitles: boolean; preset_name: string; status: string };
type ModelDiagnostics = { asr_adapter: string; asr_ready: boolean; llm_adapter: string; llm_ready: boolean; llm_url: string; face_ready: boolean; face_model: string; details: string[] };
type CacheInfo = { cache_dir: string; files: number; bytes: number };
type CandidateQuality = { candidate_id: number; duration_seconds: number; final_score: number; boundary_score: number; standalone_score: number; payoff_score: number; audio_score: number; visual_score: number; problems: string[]; recommendations: string[] };
type EpisodeQuality = { episode_id: number; stage: string; transcript_segments: number; words: number; scenes: number; candidates: number; approved: number; rejected: number; rendered: number; average_score: number; problem_candidates: number; top_problems: string[] };
type SubtitleQuality = { candidate_id: number; rows: number; warnings: string[]; long_rows: number; overlaps: number; too_fast_rows: number };
type JobStage = { id: number; job_id: number; name: string; status: string; started_at: string | null; finished_at: string | null; error_message: string | null; artifact_path: string | null };
type PreviewRender = { candidate_id: number; output_path: string; preview_url: string; duration_seconds: number };
type BlockingProgress = { kind: "media" | "candidates"; episodeId: number; fileName: string; startedAt: number };
type StoryContext = {
  season_id: number; episode_id: number; season_context: string; episode_summary: string;
  required_events: string[]; excluded_events: string[]; spoilers_allowed: boolean; candidate_mode: "highlights" | "story";
};
type Character = { id: number; season_id: number; name: string; description: string; aliases: string[]; color: string; photo_count: number; photo_urls: string[]; voice_sample_count: number };
type SpeakerIdentity = { source_label: string; character_id: number; character_name: string; confidence: number | null; method: string };
type EpisodeOutline = { summary: string; main_events: string[]; conflicts: string[]; time_ranges: { start_time: number; end_time: number; summary: string }[] };

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
  const [candidateSearch, setCandidateSearch] = useState("");
  const [candidateMomentType, setCandidateMomentType] = useState("all");
  const [candidateMinScore, setCandidateMinScore] = useState(0);
  const [candidateQuality, setCandidateQuality] = useState<CandidateQuality | null>(null);
  const [episodeQuality, setEpisodeQuality] = useState<EpisodeQuality | null>(null);
  const [subtitleQuality, setSubtitleQuality] = useState<SubtitleQuality | null>(null);
  const [jobStages, setJobStages] = useState<Record<number, JobStage[]>>({});
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [blockingProgress, setBlockingProgress] = useState<BlockingProgress | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [videoTime, setVideoTime] = useState(0);
  const [storyContext, setStoryContext] = useState<StoryContext | null>(null);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [speakerLabels, setSpeakerLabels] = useState<string[]>([]);
  const [speakerIdentities, setSpeakerIdentities] = useState<SpeakerIdentity[]>([]);
  const [episodeOutline, setEpisodeOutline] = useState<EpisodeOutline | null>(null);
  const [characterName, setCharacterName] = useState("");
  const [characterDescription, setCharacterDescription] = useState("");
  const [characterPhotos, setCharacterPhotos] = useState<string[]>([]);
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
    setEpisodeQuality(await api<EpisodeQuality>(`/api/episodes/${episodeId}/quality`).catch(() => null));
    if (selectEpisode) { setSelectedEpisodeId(episodeId); await loadEpisodeDetails(episodeId); }
    setEdits((current) => { const next = { ...current }; for (const candidate of data) next[candidate.id] ??= editFromCandidate(candidate); return next; });
    if (selectedCandidate?.episode_id === episodeId) { const updated = data.find((item) => item.id === selectedCandidate.id); if (updated) setSelectedCandidate(updated); }
  }

  async function loadEpisodeDetails(episodeId: number) {
    const context = await api<StoryContext>(`/api/episodes/${episodeId}/story-context`);
    const [characterData, labelData, identityData] = await Promise.all([
      api<Character[]>(`/api/seasons/${context.season_id}/characters`),
      api<{ labels: string[] }>(`/api/episodes/${episodeId}/speaker-labels`),
      api<SpeakerIdentity[]>(`/api/episodes/${episodeId}/speaker-identities`),
    ]);
    setStoryContext(context); setCharacters(characterData); setSpeakerLabels(labelData.labels); setSpeakerIdentities(identityData);
    const outline = await api<{ summary_json: EpisodeOutline }>(`/api/episodes/${episodeId}/outline`).catch(() => null);
    setEpisodeOutline(outline?.summary_json ?? null);
    if (context.candidate_mode === "story") setCandidateSort("time");
  }

  async function saveStoryContext() {
    if (!storyContext) return;
    const saved = await api<StoryContext>(`/api/episodes/${storyContext.episode_id}/story-context`, {
      method: "PUT", headers: jsonHeaders, body: JSON.stringify(storyContext),
    });
    setStoryContext(saved); setMessage("Контекст и режим кандидатов сохранены");
  }

  async function regenerateStoryCandidates() {
    if (!storyContext) return;
    await saveStoryContext();
    const episode = seasons.flatMap((item) => item.episodes).find((item) => item.id === storyContext.episode_id);
    if (episode) await runDirectStage(episode, "candidates");
  }

  async function createCharacter() {
    if (!storyContext || !characterName.trim()) return;
    const created = await api<Character>(`/api/seasons/${storyContext.season_id}/characters`, {
      method: "POST", headers: jsonHeaders, body: JSON.stringify({
        name: characterName, description: characterDescription, photo_data_url: characterPhotos[0] ?? null,
      }),
    });
    for (const photo of characterPhotos.slice(1)) {
      await api<Character>(`/api/characters/${created.id}/photos`, {
        method: "POST", headers: jsonHeaders, body: JSON.stringify({ photo_data_url: photo }),
      });
    }
    setCharacterName(""); setCharacterDescription(""); setCharacterPhotos([]);
    await loadEpisodeDetails(storyContext.episode_id); setMessage(`Персонаж добавлен: ${Math.max(0, characterPhotos.length)} фото сохранено локально`);
  }

  async function deleteCharacter(characterId: number) {
    if (!storyContext || !window.confirm("Удалить карточку персонажа и локальные копии его фотографий?")) return;
    await api(`/api/characters/${characterId}`, { method: "DELETE" });
    await loadEpisodeDetails(storyContext.episode_id); setMessage("Персонаж удалён; исходная фотография не изменена");
  }

  async function readCharacterPhotos(files: FileList | null) {
    if (!files?.length) { setCharacterPhotos([]); return; }
    try { setCharacterPhotos(await Promise.all(Array.from(files).slice(0, 8).map(fileDataUrl))); }
    catch (error) { setMessage(`Не удалось прочитать фотографию: ${errorMessage(error)}`); }
  }

  async function addCharacterPhotos(characterId: number, files: FileList | null) {
    if (!storyContext || !files?.length) return;
    const photos = await Promise.all(Array.from(files).slice(0, 8).map(fileDataUrl));
    for (const photo of photos) await api<Character>(`/api/characters/${characterId}/photos`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({ photo_data_url: photo }) });
    await loadEpisodeDetails(storyContext.episode_id); setMessage(`Добавлено фотографий: ${photos.length}`);
  }

  async function deleteCharacterPhoto(characterId: number, photoIndex: number) {
    if (!storyContext) return;
    await api<Character>(`/api/characters/${characterId}/photos/${photoIndex}`, { method: "DELETE" });
    await loadEpisodeDetails(storyContext.episode_id); setMessage("Локальная копия фотографии удалена");
  }

  async function assignSpeaker(sourceLabel: string, characterId: number) {
    if (!selectedEpisodeId || !characterId) return;
    await api<SpeakerIdentity>(`/api/episodes/${selectedEpisodeId}/speaker-identities`, {
      method: "PUT", headers: jsonHeaders, body: JSON.stringify({ source_label: sourceLabel, character_id: characterId }),
    });
    await loadEpisodeDetails(selectedEpisodeId);
    if (selectedCandidate) setSubtitles(await api<Subtitle[]>(`/api/candidates/${selectedCandidate.id}/subtitles`));
    setMessage(`Голос «${sourceLabel}» привязан; голосовой профиль персонажа обновлён локально`);
  }

  async function identifyCharacters() {
    if (!selectedEpisodeId) return;
    setMessage("Сравниваем лица, движение губ и локальные голосовые профили…");
    try {
      const result = await api<{ assigned_labels: number; face_model: string; voice_profiles_used: number }>(`/api/episodes/${selectedEpisodeId}/identify-characters`, { method: "POST" });
      await loadEpisodeDetails(selectedEpisodeId);
      if (selectedCandidate) setSubtitles(await api<Subtitle[]>(`/api/candidates/${selectedCandidate.id}/subtitles`));
      setMessage(result.assigned_labels ? `Определено голосов: ${result.assigned_labels} · ${result.face_model} · голосовых профилей: ${result.voice_profiles_used}` : "Надёжных совпадений лиц, губ и голосов не найдено — имена не назначены");
    } catch (error) { setMessage(`Распознавание персонажей: ${errorMessage(error)}`); }
  }

  async function openCandidate(candidate: Candidate, play = false) {
    setSelectedCandidate(candidate); setSubtitleBusy(true); setPreviewUrl(null);
    try {
      const [subtitleRows, quality, subtitleReport] = await Promise.all([
        api<Subtitle[]>(`/api/candidates/${candidate.id}/subtitles`),
        api<CandidateQuality>(`/api/candidates/${candidate.id}/quality`),
        api<SubtitleQuality>(`/api/candidates/${candidate.id}/subtitles/quality`),
      ]);
      setSubtitles(subtitleRows); setCandidateQuality(quality); setSubtitleQuality(subtitleReport);
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
    setMessage("Ищем активного говорящего по персонажу и движению губ…");
    const data = await api<{ crop_offset_x: number; faces_detected: number; keyframes: { time: number; offset: number }[]; active_speaker_frames: number; identified_speaker_frames: number; lip_motion_frames: number; face_model: string }>(`/api/candidates/${candidate.id}/auto-crop`, { method: "POST" });
    setCandidateEdit(candidate.id, { crop: "auto-follow", offset: data.crop_offset_x });
    await loadCandidates(candidate.episode_id, false);
    setMessage(data.faces_detected ? `Траектория: ${data.keyframes.length} точек · персонаж: ${data.identified_speaker_frames} · губы: ${data.lip_motion_frames} · ${data.face_model}` : "Лица не найдены, оставлен центр кадра");
  }

  async function saveSubtitles() {
    if (!selectedCandidate) return; setSubtitleBusy(true);
    try {
      const saved = await api<Subtitle[]>(`/api/candidates/${selectedCandidate.id}/subtitles`, { method: "PUT", headers: jsonHeaders, body: JSON.stringify({ subtitles }) });
      setSubtitles(saved);
      setSubtitleQuality(await api<SubtitleQuality>(`/api/candidates/${selectedCandidate.id}/subtitles/quality`));
      setMessage("Субтитры сохранены");
    } catch (error) { setMessage(`Субтитры не сохранены: ${errorMessage(error)}`); }
    finally { setSubtitleBusy(false); }
  }

  async function resetSubtitles() {
    if (!selectedCandidate) return; setSubtitleBusy(true);
    try {
      setSubtitles(await api<Subtitle[]>(`/api/candidates/${selectedCandidate.id}/subtitles`, { method: "DELETE" }));
      setSubtitleQuality(await api<SubtitleQuality>(`/api/candidates/${selectedCandidate.id}/subtitles/quality`));
      setMessage("Субтитры пересобраны из распознанных слов");
    }
    finally { setSubtitleBusy(false); }
  }

  async function autoSplitSubtitles() {
    if (!selectedCandidate) return; setSubtitleBusy(true);
    try {
      setSubtitles(await api<Subtitle[]>(`/api/candidates/${selectedCandidate.id}/subtitles/auto-split`, { method: "POST" }));
      setSubtitleQuality(await api<SubtitleQuality>(`/api/candidates/${selectedCandidate.id}/subtitles/quality`));
      setMessage("Длинные субтитры разбиты на короткие строки");
    } catch (error) { setMessage(`Не удалось разбить субтитры: ${errorMessage(error)}`); }
    finally { setSubtitleBusy(false); }
  }

  async function renderCandidate(candidate: Candidate, includeSubtitles: boolean) {
    const edit = edits[candidate.id] ?? editFromCandidate(candidate);
    await api(`/api/candidates/${candidate.id}/review`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({ decision: "approve", adjusted_start_time: Number(edit.start), adjusted_end_time: Number(edit.end), crop_mode: edit.crop, crop_offset_x: edit.offset, crop_scale: edit.scale }) });
    const job = await api<Job>(`/api/candidates/${candidate.id}/render-job`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({ include_subtitles: includeSubtitles, use_nvenc: settings?.render_use_nvenc ?? null, preset_name: settings?.render_preset, loudnorm_two_pass: settings?.render_loudnorm_two_pass ?? null, force_rerender: true }) });
    setMessage(`Рендер поставлен в очередь, задача №${job.id}. Можно продолжать работу.`); await refreshActivity();
  }

  async function renderPreview(candidate: Candidate) {
    const edit = edits[candidate.id] ?? editFromCandidate(candidate);
    setPreviewBusy(true); setMessage("Быстрый preview рендерится…");
    try {
      await api(`/api/candidates/${candidate.id}`, { method: "PATCH", headers: jsonHeaders, body: JSON.stringify({ adjusted_start_time: Number(edit.start), adjusted_end_time: Number(edit.end), crop_mode: edit.crop, crop_offset_x: edit.offset, crop_scale: edit.scale }) });
      const data = await api<PreviewRender>(`/api/candidates/${candidate.id}/preview`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({ include_subtitles: true, force_rerender: true }) });
      setPreviewUrl(`${data.preview_url}?t=${Date.now()}`);
      setMessage(`Preview готов: ${data.duration_seconds.toFixed(1)} сек`);
      await loadCandidates(candidate.episode_id, false);
    } catch (error) { setMessage(`Preview не создан: ${errorMessage(error)}`); }
    finally { setPreviewBusy(false); }
  }

  async function loadJobStages(jobId: number) {
    const stages = await api<JobStage[]>(`/api/jobs/${jobId}/stages`);
    setJobStages((current) => ({ ...current, [jobId]: stages }));
  }

  async function mergeCharacter(sourceId: number, targetId: number) {
    if (!storyContext || !targetId || sourceId === targetId) return;
    if (!window.confirm("Объединить этого персонажа с выбранным? Привязки голосов перейдут к целевой карточке.")) return;
    await api<Character>(`/api/characters/${sourceId}/merge`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({ target_character_id: targetId }) });
    await loadEpisodeDetails(storyContext.episode_id); setMessage("Карточки персонажей объединены");
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
    const search = candidateSearch.trim().toLocaleLowerCase("ru");
    const filtered = items.filter((item) => {
      if (candidateFilter === "problem" && !item.problems_json.length) return false;
      if (candidateFilter !== "all" && candidateFilter !== "problem" && item.status !== candidateFilter) return false;
      if (candidateMomentType !== "all" && item.moment_type !== candidateMomentType) return false;
      if (item.score < candidateMinScore) return false;
      if (!search) return true;
      return `${item.title} ${item.description} ${item.rationale} ${item.moment_type}`.toLocaleLowerCase("ru").includes(search);
    });
    return filtered.sort(candidateSort === "time" ? (a, b) => a.start_time - b.start_time : candidateSort === "boundary" ? (a, b) => (b.scores_json.boundary_quality ?? 0) - (a.scores_json.boundary_quality ?? 0) : (a, b) => b.score - a.score);
  }, [candidateFilter, candidateMinScore, candidateMomentType, candidateSearch, candidateSort, candidates, selectedEpisodeId]);
  const momentTypes = useMemo(() => Array.from(new Set((selectedEpisodeId ? candidates[selectedEpisodeId] ?? [] : []).map((item) => item.moment_type))).sort(), [candidates, selectedEpisodeId]);
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
        <div className="job-list">{(queue?.items ?? []).slice(0, 6).map((job) => <article className="job" key={job.id}><div><strong>№{job.id} · {jobLabel(job.kind)}</strong><span>{stageLabel(job.current_stage)} · {statusLabel(job.status)}{job.status === "running" ? ` · ${elapsedFrom(job.updated_at)}` : ""}</span></div><div className={`progress ${job.status === "running" ? "active" : ""}`}><i style={{ width: `${Math.round(job.progress * 100)}%` }} /></div>{job.error_message && <small className="error-text">{job.error_message}</small>}<div className="job-actions"><button className="text-button" onClick={() => loadJobStages(job.id)}>Этапы</button>{["queued", "running", "paused", "cancel_requested"].includes(job.status) && <button className="text-button danger" onClick={() => cancelJob(job.id)}>Остановить</button>}{job.status === "failed" && <button className="text-button" onClick={() => retryJob(job.id)}>Повторить</button>}</div>{jobStages[job.id] && <ol className="job-timeline">{jobStages[job.id].map((stage) => <li key={stage.id}><span className={`dot ${stage.status === "completed" ? "ok" : stage.status === "failed" ? "fail" : ""}`} /><strong>{stageLabel(stage.name)}</strong><small>{statusLabel(stage.status)}{stage.error_message ? ` · ${stage.error_message}` : ""}</small></li>)}</ol>}</article>)}</div>
      </div>
    </section>

    <section className="panel section-gap"><div className="panel-title"><ListVideo size={19} /><h2>Серии</h2></div><div className="episodes">{seasons.flatMap((season) => season.episodes).map((episode) => { const busy = isEpisodeBusy(episode.id); return <article className="episode" key={episode.id}><div><strong>{episode.file_name}</strong><small>{busy ? "Обрабатывается в очереди" : stageLabel(episode.stage)}</small></div><span>{formatBytes(episode.size_bytes)}</span><span>{episode.width && episode.height ? `${episode.width}×${episode.height}` : "без метаданных"}</span><button disabled={busy} onClick={() => enqueueEpisode(episode)}>В очередь</button><button className="secondary" disabled={blockingProgress !== null || busy} onClick={() => runDirectStage(episode, "media")}>Только медиа</button><button className="secondary" disabled={blockingProgress !== null || busy} onClick={() => runDirectStage(episode, "candidates")}>Только кандидаты</button><button onClick={() => loadCandidates(episode.id)}>Открыть</button><button className="secondary" disabled={busy} onClick={() => autoExport(episode.id)}>Auto export</button></article>; })}</div></section>

    {selectedEpisodeId && storyContext && <section className="story-dashboard section-gap">
      <div className="panel story-panel"><div className="panel-title"><BookOpen size={19} /><h2>Сюжетный контекст</h2><span className="badge">{storyContext.candidate_mode === "story" ? "Связный пересказ" : "Лучшие моменты"}</span></div>
        <div className="story-mode"><button className={storyContext.candidate_mode === "highlights" ? "" : "secondary"} onClick={() => setStoryContext({ ...storyContext, candidate_mode: "highlights" })}>Лучшие моменты</button><button className={storyContext.candidate_mode === "story" ? "" : "secondary"} onClick={() => setStoryContext({ ...storyContext, candidate_mode: "story" })}>Сюжет серии</button></div>
        <label className="story-field"><span>Общая суть сезона</span><textarea rows={4} value={storyContext.season_context} onChange={(event) => setStoryContext({ ...storyContext, season_context: event.target.value })} placeholder="Главные персонажи, отношения, общая история и тон сезона…" /></label>
        <label className="story-field"><span>Суть этой серии</span><textarea rows={4} value={storyContext.episode_summary} onChange={(event) => setStoryContext({ ...storyContext, episode_summary: event.target.value })} placeholder="Завязка, конфликт, важный поворот и итог серии…" /></label>
        <div className="story-columns"><label className="story-field"><span>Обязательно показать</span><textarea rows={3} value={storyContext.required_events.join("\n")} onChange={(event) => setStoryContext({ ...storyContext, required_events: splitLines(event.target.value) })} placeholder="По одному событию на строку" /></label><label className="story-field"><span>Не включать</span><textarea rows={3} value={storyContext.excluded_events.join("\n")} onChange={(event) => setStoryContext({ ...storyContext, excluded_events: splitLines(event.target.value) })} placeholder="Второстепенные линии или нежелательные сцены" /></label></div>
        <label className="inline-check"><input type="checkbox" checked={storyContext.spoilers_allowed} onChange={(event) => setStoryContext({ ...storyContext, spoilers_allowed: event.target.checked })} /> Можно показывать концовку серии</label>
        <div className="story-actions"><button onClick={saveStoryContext}><Save size={16} /> Сохранить контекст</button><button className="secondary" disabled={isEpisodeBusy(selectedEpisodeId) || blockingProgress !== null} onClick={regenerateStoryCandidates}><Sparkles size={16} /> Пересоздать кандидатов</button></div>
        {episodeOutline && <details className="outline-card"><summary>Построенная карта серии</summary><p>{episodeOutline.summary}</p><ol>{episodeOutline.time_ranges.map((item, index) => <li key={`${item.start_time}-${index}`}><strong>{formatClock(item.start_time)}–{formatClock(item.end_time)}</strong> {item.summary}</li>)}</ol></details>}
      </div>
      <div className="panel character-panel"><div className="panel-title"><UserRound size={19} /><h2>Персонажи и голоса</h2><span className="badge">{characters.length}</span></div>
        <div className="character-create"><input value={characterName} onChange={(event) => setCharacterName(event.target.value)} placeholder="Имя персонажа" /><input value={characterDescription} onChange={(event) => setCharacterDescription(event.target.value)} placeholder="Краткое описание" /><label className="file-picker">{characterPhotos.length ? `Выбрано фото: ${characterPhotos.length}` : "Выбрать несколько фото"}<input multiple type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => readCharacterPhotos(event.target.files)} /></label><button disabled={!characterName.trim()} onClick={createCharacter}>Добавить</button></div>
        <div className="character-list">{characters.map((character) => <article className="character-card" key={character.id}><div className="character-photos">{character.photo_urls.map((url, index) => <span className="character-photo" key={url}><img src={url} alt={`${character.name}, фото ${index + 1}`} /><button title="Удалить это фото" onClick={() => deleteCharacterPhoto(character.id, index)}>×</button></span>)}{!character.photo_urls.length && <span className="character-placeholder"><UserRound /></span>}<label className="character-photo-add" title="Добавить фотографии">+<input multiple type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => addCharacterPhotos(character.id, event.target.files)} /></label></div><div className="character-info"><strong>{character.name}</strong><small>{character.description || "Без описания"}</small><small>{character.photo_count} фото · голосовых образцов: {character.voice_sample_count}</small><select title="Объединить дубль в другого персонажа" value="" onChange={(event) => mergeCharacter(character.id, Number(event.target.value))}><option value="">Объединить в…</option>{characters.filter((item) => item.id !== character.id).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div><button className="icon-button danger" title="Удалить персонажа" onClick={() => deleteCharacter(character.id)}><Trash2 size={15} /></button></article>)}{!characters.length && <p className="empty">Добавьте имя и 3–8 фотографий с разными ракурсами. Все файлы останутся на компьютере.</p>}</div>
        {!!speakerLabels.length && <div className="speaker-map"><h3>Кто скрывается за голосами</h3>{speakerLabels.map((label) => { const current = speakerIdentities.find((item) => item.source_label === label); return <label key={label}><span>{label}</span><select value={current?.character_id ?? ""} onChange={(event) => assignSpeaker(label, Number(event.target.value))}><option value="">Не определён</option>{characters.map((character) => <option key={character.id} value={character.id}>{character.name}</option>)}</select>{current && <small>{current.confidence != null ? `${Math.round(current.confidence * 100)}% · ` : ""}{identityMethodLabel(current.method)}</small>}</label>; })}</div>}
        <button className="secondary identify-button" disabled={!characters.some((item) => item.photo_count > 0 || item.voice_sample_count > 0) || isEpisodeBusy(selectedEpisodeId)} onClick={identifyCharacters}><WandSparkles size={16} /> Лица + губы + голоса</button>
      </div>
    </section>}

    {selectedEpisodeId && <section className="workspace section-gap">
      <div className="panel candidate-panel"><div className="panel-title"><Clapperboard size={19} /><h2>Кандидаты</h2>{episodeQuality && <span className="badge">средний score {episodeQuality.average_score}</span>}</div><div className="candidate-toolbar expanded"><label><ListFilter size={16} /><select value={candidateFilter} onChange={(event) => setCandidateFilter(event.target.value)}><option value="all">Все статусы</option><option value="new">Новые</option><option value="approved">Принятые</option><option value="rejected">Отклонённые</option><option value="rendered">Готовые</option><option value="problem">С проблемами</option></select></label><select value={candidateSort} onChange={(event) => setCandidateSort(event.target.value)}><option value="score">Сначала лучшие</option><option value="boundary">Лучшие границы</option><option value="time">По времени</option></select><select value={candidateMomentType} onChange={(event) => setCandidateMomentType(event.target.value)}><option value="all">Все типы</option>{momentTypes.map((type) => <option key={type} value={type}>{type}</option>)}</select><input value={candidateSearch} onChange={(event) => setCandidateSearch(event.target.value)} placeholder="Поиск по смыслу" /><label className="score-filter">Score ≥ <input type="number" min="0" max="100" value={candidateMinScore} onChange={(event) => setCandidateMinScore(Number(event.target.value))} /></label></div>{episodeQuality && <div className="quality-strip"><span>{episodeQuality.transcript_segments} сегм.</span><span>{episodeQuality.scenes} сцен</span><span>{episodeQuality.candidates} кандид.</span><span>{episodeQuality.problem_candidates} с замечаниями</span>{episodeQuality.top_problems.slice(0, 2).map((problem) => <span key={problem}>{problem}</span>)}</div>}
        <div className="candidate-list">{visibleCandidates.map((candidate) => { const edit = edits[candidate.id] ?? editFromCandidate(candidate); const busy = isEpisodeBusy(candidate.episode_id); return <article className={`candidate ${selectedCandidate?.id === candidate.id ? "selected" : ""}`} key={candidate.id}><button className="candidate-main" onClick={() => openCandidate(candidate, true)}><span className="score">{candidate.score}</span><span><strong>{candidate.story_order ? `Часть ${candidate.story_order} · ` : ""}{candidate.title}</strong><small>{candidate.story_role ? `${candidate.story_role} · ` : ""}{candidate.moment_type} · {statusLabel(candidate.status)} · {formatRange(candidate.start_time, candidate.end_time)}</small></span><Play size={18} /></button><div className="score-breakdown"><span>Hook {candidate.scores_json.hook ?? "—"}</span><span>Контекст {candidate.scores_json.standalone_context ?? "—"}</span><span>Финал {candidate.scores_json.payoff ?? "—"}</span><span>Границы {candidate.scores_json.boundary_quality ?? "—"}</span></div><p>{candidate.description}</p>{candidate.continuity_note && <small className="continuity-note">Связность: {candidate.continuity_note}</small>}{!!candidate.problems_json.length && <small className="error-text">{candidate.problems_json.join(" · ")}</small>}<div className="compact-edit"><label>Начало<input value={edit.start} onChange={(event) => setCandidateEdit(candidate.id, { start: event.target.value })} /></label><label>Конец<input value={edit.end} onChange={(event) => setCandidateEdit(candidate.id, { end: event.target.value })} /></label><select value={edit.crop} onChange={(event) => setCandidateEdit(candidate.id, { crop: event.target.value as Candidate["crop_mode"] })}><option value="blurred-background">Фон с размытием</option><option value="center-crop">Центр</option><option value="auto-follow">По лицам</option></select></div><div className="candidate-actions"><button disabled={busy} onClick={() => reviewCandidate(candidate, "approve")}><Check size={16} /> Принять</button><button className="secondary" disabled={busy} onClick={() => reviewCandidate(candidate, "reject")}><X size={16} /> Отклонить</button><button className="secondary" disabled={busy || previewBusy} onClick={() => renderPreview(candidate)}><Play size={16} /> Preview</button><button disabled={busy} onClick={() => renderCandidate(candidate, true)}>Рендер с субтитрами</button><button className="secondary" disabled={busy} onClick={() => renderCandidate(candidate, false)}>Без субтитров</button></div></article>; })}{!visibleCandidates.length && <p className="empty">Кандидатов с выбранным фильтром нет.</p>}</div>
      </div>
      <div className="panel editor-panel"><div className="panel-title"><WandSparkles size={19} /><h2>Предпросмотр и редактор</h2></div>{selectedCandidate && selectedEdit ? <>
        <div className={`preview-frame ${selectedEdit.crop}`}><video className="preview-background" ref={backgroundVideoRef} muted src={`/api/episodes/${selectedEpisodeId}/proxy`} /><video className="preview-foreground" ref={videoRef} controls src={`/api/episodes/${selectedEpisodeId}/proxy`} onTimeUpdate={onVideoTimeUpdate} onPlay={() => backgroundVideoRef.current?.play().catch(() => undefined)} onPause={() => backgroundVideoRef.current?.pause()} style={{ objectPosition: `${50 + previewCropOffset(selectedCandidate, selectedEdit, videoTime) * 35}% 50%`, transform: `scale(${selectedEdit.scale})` }} />{activeSubtitle && <div className="subtitle-preview"><small>{activeSubtitle.speaker_label}</small>{activeSubtitle.text}</div>}</div>
        {previewUrl && <video className="render-preview" controls src={previewUrl} />}
        <div className="preview-summary"><strong>{selectedCandidate.title}</strong><span>{formatRange(Number(selectedEdit.start), Number(selectedEdit.end))}</span></div>
        {candidateQuality && <div className="quality-panel"><div className="quality-grid"><span><strong>{candidateQuality.final_score}</strong> score</span><span><strong>{candidateQuality.boundary_score}</strong> границы</span><span><strong>{candidateQuality.standalone_score}</strong> контекст</span><span><strong>{candidateQuality.payoff_score}</strong> финал</span></div>{candidateQuality.recommendations.length ? <ul>{candidateQuality.recommendations.map((item) => <li key={item}>{item}</li>)}</ul> : <small>Критичных замечаний нет.</small>}</div>}
        <div className="crop-controls"><label>Смещение по горизонтали <span>{selectedEdit.offset.toFixed(2)}</span><input type="range" min="-1" max="1" step="0.02" value={selectedEdit.offset} onChange={(event) => setCandidateEdit(selectedCandidate.id, { offset: Number(event.target.value) })} /></label><label>Масштаб <span>{selectedEdit.scale.toFixed(2)}×</span><input type="range" min="1" max="2" step="0.02" value={selectedEdit.scale} onChange={(event) => setCandidateEdit(selectedCandidate.id, { scale: Number(event.target.value) })} /></label><button disabled={isEpisodeBusy(selectedCandidate.episode_id)} onClick={() => autoCrop(selectedCandidate)}><WandSparkles size={16} /> Найти лица</button></div>
        <div className="subtitle-header"><div><h3>Субтитры</h3><small>{subtitleQuality ? `${subtitleQuality.rows} строк · замечаний ${subtitleQuality.warnings.length}` : "Время указано относительно начала клипа."}</small></div><div><button className="secondary" disabled={subtitleBusy || isEpisodeBusy(selectedCandidate.episode_id)} onClick={autoSplitSubtitles}>Разбить</button><button className="icon-button secondary" title="Пересобрать" disabled={subtitleBusy || isEpisodeBusy(selectedCandidate.episode_id)} onClick={resetSubtitles}><RotateCcw size={17} /></button><button onClick={saveSubtitles} disabled={subtitleBusy || isEpisodeBusy(selectedCandidate.episode_id)}><Save size={16} /> Сохранить</button></div></div>
        {subtitleQuality?.warnings.length ? <div className="subtitle-warnings">{subtitleQuality.warnings.slice(0, 4).map((warning) => <small key={warning}>{warning}</small>)}</div> : null}
        <div className="subtitle-list">{subtitles.map((subtitle, index) => <article className="subtitle-row" key={`${subtitle.id ?? "new"}-${index}`}><input type="number" step="0.05" value={subtitle.start_time} onChange={(event) => updateSubtitle(index, { start_time: Number(event.target.value) })} /><input type="number" step="0.05" value={subtitle.end_time} onChange={(event) => updateSubtitle(index, { end_time: Number(event.target.value) })} /><textarea rows={2} value={subtitle.text} onChange={(event) => updateSubtitle(index, { text: event.target.value })} /><select title="Говорящий" value={subtitle.speaker_label ?? ""} onChange={(event) => updateSubtitle(index, { speaker_label: event.target.value || null })}><option value="">Неизвестный</option>{subtitle.speaker_label && !characters.some((item) => item.name === subtitle.speaker_label) && <option value={subtitle.speaker_label}>{subtitle.speaker_label}</option>}{characters.map((character) => <option key={character.id} value={character.name}>{character.name}</option>)}</select><button className="icon-button danger" title="Удалить строку" onClick={() => setSubtitles((current) => current.filter((_, itemIndex) => itemIndex !== index))}><Trash2 size={16} /></button></article>)}</div>
        <button className="secondary add-subtitle" onClick={() => setSubtitles((current) => [...current, { start_time: 0, end_time: 1, text: "Новая строка", speaker_label: null }])}>Добавить строку</button>
      </> : <p className="empty">Нажмите на кандидата, чтобы посмотреть только его отрывок и отредактировать кадр и субтитры.</p>}</div>
    </section>}

    <section className="panel section-gap"><div className="panel-title"><FolderOpen size={19} /><h2>Готовые ролики</h2><span className="badge">{exports.length}</span></div><div className="exports-grid">{exports.map((item) => <article className="export-card" key={item.id}>{item.cover_path ? <img src={`/api/exports/${item.id}/cover`} alt="Обложка клипа" /> : <div className="export-placeholder"><Clapperboard /></div>}<div><strong>Экспорт №{item.id}</strong><small>{item.preset_name} · {item.include_subtitles ? "с субтитрами" : "без субтитров"}</small><small title={item.output_path}>{item.output_path}</small></div><video controls preload="none" src={`/api/exports/${item.id}/file`} /><button onClick={() => api(`/api/exports/${item.id}/open-folder`, { method: "POST" })}><FolderOpen size={16} /> Открыть папку</button></article>)}{!exports.length && <p className="empty">После рендера готовые MP4 появятся здесь.</p>}</div></section>

    <section className="grid section-gap">
      <div className="panel"><div className="panel-title"><Server size={19} /><h2>Готовность системы</h2><button className="icon-button secondary" onClick={runSystemCheck}><RefreshCcw size={17} /></button></div><div className="checks">{checks.map((item) => <div className="check" key={item.name}><span className={item.ok ? "dot ok" : "dot fail"} /><strong>{item.name}</strong><span>{item.message}</span></div>)}{diagnostics && <><div className="check"><span className={diagnostics.asr_ready ? "dot ok" : "dot fail"} /><strong>Whisper</strong><span>{diagnostics.asr_adapter}</span></div><div className="check"><span className={diagnostics.llm_ready ? "dot ok" : "dot fail"} /><strong>Qwen</strong><span>{diagnostics.llm_adapter}</span></div><div className="check"><span className={diagnostics.face_ready ? "dot ok" : "dot fail"} /><strong>Лица</strong><span>{diagnostics.face_model}</span></div></>}</div><div className="cache-card"><div><strong>Временные файлы</strong><small>{cacheInfo?.files ?? 0} файлов · {formatBytes(cacheInfo?.bytes ?? 0)}</small><small>{cacheInfo?.cache_dir}</small></div><button className="danger" onClick={clearCache}><Trash2 size={16} /> Очистить кэш</button></div></div>
      <div className="panel"><div className="panel-title"><Server size={19} /><h2>Настройки</h2></div>{settings && <div className="settings-sections">
        <section className="settings-section"><h3>Файлы</h3><div className="settings-grid"><SettingText title="Папка временных файлов" hint="Proxy, WAV и промежуточные данные; их можно безопасно удалить." value={settings.cache_dir} onChange={(value) => patchSettings({ cache_dir: value })} wide /><SettingText title="Папка готовых роликов" hint="Готовые MP4, обложки, субтитры и метаданные." value={settings.output_dir} onChange={(value) => patchSettings({ output_dir: value })} wide /></div></section>
        <section className="settings-section"><h3>Анализ и Auto</h3><div className="settings-grid"><label className="setting-field"><span>Профиль качества</span><select value={settings.quality_profile} onChange={(event) => patchSettings({ quality_profile: event.target.value as RuntimeSettings["quality_profile"] })}><option value="fast">Быстрый</option><option value="balanced">Сбалансированный</option><option value="quality">Качественный</option></select><small>Баланс скорости и тщательности локального анализа.</small></label><SettingNumber title="Минимальная длина, сек." hint="Короткий кандидат будет расширен." value={settings.min_clip_seconds} min={5} max={300} onChange={(value) => patchSettings({ min_clip_seconds: value })} /><SettingNumber title="Максимальная длина, сек." hint="Клип не выйдет за этот предел." value={settings.max_clip_seconds} min={5} max={300} onChange={(value) => patchSettings({ max_clip_seconds: value })} /><SettingNumber title="Порог Auto, баллы" hint="Auto принимает кандидатов с этой оценкой и выше." value={settings.auto_score_threshold} min={0} max={100} onChange={(value) => patchSettings({ auto_score_threshold: value })} /><SettingNumber title="Максимум клипов" hint="Лимит автоматического экспорта из серии." value={settings.max_clips_per_episode} min={1} max={20} onChange={(value) => patchSettings({ max_clips_per_episode: value })} /><SettingCheck title="Фоновая очередь" hint="Новые задачи запускаются сами." checked={settings.background_queue_enabled} onChange={(value) => patchSettings({ background_queue_enabled: value })} /><SettingCheck title="Auto по умолчанию" hint="Лучшие кандидаты принимаются и экспортируются." checked={settings.auto_mode_enabled} onChange={(value) => patchSettings({ auto_mode_enabled: value })} /></div></section>
        <section className="settings-section"><h3>Рендер и субтитры</h3><div className="settings-grid"><label className="setting-field"><span>Платформа</span><select value={settings.render_preset} onChange={(event) => patchSettings({ render_preset: event.target.value as RuntimeSettings["render_preset"] })}><option value="youtube_shorts">YouTube Shorts</option><option value="instagram_reels">Instagram Reels</option></select><small>Битрейт и параметры MP4.</small></label><SettingText title="Шрифт субтитров" hint="Шрифт, установленный в Windows." value={settings.subtitle_font_name} onChange={(value) => patchSettings({ subtitle_font_name: value })} /><SettingNumber title="Размер субтитров" hint="Обычно 36–52 для вертикального кадра." value={settings.subtitle_font_size} min={24} max={96} onChange={(value) => patchSettings({ subtitle_font_size: value })} /><SettingCheck title="Показывать имя персонажа" hint="Добавляет имя говорящего над текстом в готовом видео." checked={settings.subtitle_show_speaker_names} onChange={(value) => patchSettings({ subtitle_show_speaker_names: value })} /><SettingCheck title="NVIDIA NVENC" hint="Ускоряет рендер; при ошибке включится CPU." checked={settings.render_use_nvenc} onChange={(value) => patchSettings({ render_use_nvenc: value })} /><SettingCheck title="Точная громкость" hint="Два прохода: медленнее, но ровнее звук." checked={settings.render_loudnorm_two_pass} onChange={(value) => patchSettings({ render_loudnorm_two_pass: value })} /></div></section>
        <button className="settings-save" onClick={saveSettings}><Save size={17} /> Сохранить настройки</button>
      </div>}</div>
    </section>
  </main>;
}

const jsonHeaders = { "Content-Type": "application/json" };
function splitLines(value: string) { return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean); }
function fileDataUrl(file: File) { return new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => typeof reader.result === "string" ? resolve(reader.result) : reject(new Error("Пустой файл")); reader.onerror = () => reject(reader.error ?? new Error("Ошибка чтения")); reader.readAsDataURL(file); }); }
function identityMethodLabel(method: string) { const labels: Record<string, string> = { manual: "подтверждено вручную", face: "лицо", "face+lip": "лицо + губы", voice: "голос", "face+lip+voice": "лицо + губы + голос" }; return labels[method] ?? method; }
function SettingText({ title, hint, value, onChange, wide = false }: { title: string; hint: string; value: string; onChange: (value: string) => void; wide?: boolean }) { return <label className={`setting-field ${wide ? "setting-field-wide" : ""}`}><span>{title}</span><input value={value} onChange={(event) => onChange(event.target.value)} /><small>{hint}</small></label>; }
function SettingNumber({ title, hint, value, min, max, onChange }: { title: string; hint: string; value: number; min: number; max: number; onChange: (value: number) => void }) { return <label className="setting-field"><span>{title}</span><input type="number" min={min} max={max} value={value} onChange={(event) => onChange(Number(event.target.value))} /><small>{hint}</small></label>; }
function SettingCheck({ title, hint, checked, onChange }: { title: string; hint: string; checked: boolean; onChange: (value: boolean) => void }) { return <label className="setting-checkbox"><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><span><strong>{title}</strong><small>{hint}</small></span></label>; }
function editFromCandidate(candidate: Candidate): CandidateEdit { return { start: candidate.start_time.toFixed(3), end: candidate.end_time.toFixed(3), crop: candidate.crop_mode, offset: candidate.crop_offset_x, scale: candidate.crop_scale }; }
function previewCropOffset(candidate: Candidate, edit: CandidateEdit, absoluteTime: number) {
  const points = candidate.crop_keyframes_json ?? [];
  if (edit.crop !== "auto-follow" || !points.length) return edit.offset;
  const time = Math.max(0, absoluteTime - candidate.start_time);
  const rightIndex = points.findIndex((item) => item.time >= time);
  if (rightIndex <= 0) return points[0].offset;
  if (rightIndex < 0) return points.at(-1)?.offset ?? edit.offset;
  const left = points[rightIndex - 1]; const right = points[rightIndex];
  const ratio = (time - left.time) / Math.max(0.001, right.time - left.time);
  return left.offset + (right.offset - left.offset) * ratio;
}
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
