import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, BookOpen, CalendarDays, Check, Clapperboard, FileText, FolderPlus, ListFilter, ListVideo, LoaderCircle, Play, RefreshCcw, RotateCcw, Save, Search, Sparkles, Trash2, UserRound, Volume2, WandSparkles, X } from "lucide-react";
import { api, jsonHeaders } from "./api";
import { ExportsPanel } from "./components/ExportsPanel";
import { SettingCheck, SettingNumber, SettingText } from "./components/SettingsFields";
import { SettingsPanel } from "./components/SettingsPanel";
import { QueuePanel } from "./components/QueuePanel";
import { SystemPanel } from "./components/SystemPanel";
import type { CacheInfo, Candidate, CandidateEdit, CandidateQuality, Character, CheckItem, Episode, EpisodeOutline, EpisodeQuality, ExportItem, Job, JobStage, ModelDiagnostics, PreviewRender, ProjectDiagnostics, PublishingPlan, QueueData, RuntimeSettings, SearchResult, Season, SpeakerIdentity, StoryArc, StoryArcSegment, StoryContext, Subtitle, SubtitleQuality, VideoScript } from "./types";
import { arcNarration, editFromCandidate, errorMessage, fileDataUrl, formatArcFormat, formatBytes, formatClock, formatElapsed, formatRange, identityMethodLabel, previewCropOffset, splitLines, stageLabel, statusLabel } from "./utils";
import "./styles.css";

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
  const [videoTime, setVideoTime] = useState(0);
  const [storyContext, setStoryContext] = useState<StoryContext | null>(null);
  const [storyArcs, setStoryArcs] = useState<StoryArc[]>([]);
  const [videoScripts, setVideoScripts] = useState<VideoScript[]>([]);
  const [publishingPlans, setPublishingPlans] = useState<PublishingPlan[]>([]);
  const [projectDiagnostics, setProjectDiagnostics] = useState<ProjectDiagnostics | null>(null);
  const [arcSeasonId, setArcSeasonId] = useState<number | null>(null);
  const [arcTitle, setArcTitle] = useState("");
  const [arcPrompt, setArcPrompt] = useState("");
  const [arcFormat, setArcFormat] = useState<StoryArc["output_format"]>("shorts_series");
  const [arcType, setArcType] = useState<StoryArc["arc_type"]>("story_arc");
  const [arcCharacterId, setArcCharacterId] = useState<number | null>(null);
  const [arcMaxSegments, setArcMaxSegments] = useState(8);
  const [arcMaxDuration, setArcMaxDuration] = useState(420);
  const [arcRenderBusy, setArcRenderBusy] = useState<number | null>(null);
  const [workflowArcId, setWorkflowArcId] = useState<number | null>(null);
  const [arcTransition, setArcTransition] = useState<"cut" | "fade">("fade");
  const [arcIncludeNarration, setArcIncludeNarration] = useState(true);
  const [arcNarrationMode, setArcNarrationMode] = useState<"first_person" | "narrator" | "none">("first_person");
  const [seasonSearch, setSeasonSearch] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [scriptPrompt, setScriptPrompt] = useState("");
  const [availableArcCharacters, setAvailableArcCharacters] = useState<Character[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [speakerLabels, setSpeakerLabels] = useState<string[]>([]);
  const [speakerIdentities, setSpeakerIdentities] = useState<SpeakerIdentity[]>([]);
  const [episodeOutline, setEpisodeOutline] = useState<EpisodeOutline | null>(null);
  const [characterName, setCharacterName] = useState("");
  const [characterDescription, setCharacterDescription] = useState("");
  const [characterPhotos, setCharacterPhotos] = useState<string[]>([]);
  const videoRef = useRef<HTMLVideoElement>(null);
  const backgroundVideoRef = useRef<HTMLVideoElement>(null);

  async function refresh() {
    const [seasonData, queueData, settingsData, exportData, cacheData, arcData, scriptData, publishingData, projectData] = await Promise.all([
      api<Season[]>("/api/seasons"), api<QueueData>("/api/jobs"), api<RuntimeSettings>("/api/settings"),
      api<ExportItem[]>("/api/exports"), api<CacheInfo>("/api/cache"), api<StoryArc[]>("/api/story-arcs"),
      api<VideoScript[]>("/api/video-scripts"), api<PublishingPlan[]>("/api/publishing-plans"), api<ProjectDiagnostics>("/api/project-diagnostics")
    ]);
    setSeasons(seasonData); setQueue(queueData); setSettings(settingsData); setExports(exportData); setCacheInfo(cacheData); setStoryArcs(arcData);
    setVideoScripts(scriptData); setPublishingPlans(publishingData); setProjectDiagnostics(projectData);
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
    const job = await api<Job>(`/api/jobs/${jobId}/cancel`, { method: "POST" });
    setMessage(job.status === "paused" ? "Задача остановлена." : "Остановка запрошена. Текущий шаг завершится безопасно.");
    await refreshActivity();
  }

  async function retryJob(jobId: number) {
    await api(`/api/jobs/${jobId}/retry`, { method: "POST" }); setMessage("Задача снова поставлена в очередь"); await refreshActivity();
  }

  async function retryJobStage(jobId: number, stageName: string) {
    await api<Job>(`/api/jobs/${jobId}/retry-stage`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({ stage_name: stageName }) });
    setMessage(`Задача №${jobId} продолжит с этапа «${stageLabel(stageName)}»`);
    await loadJobStages(jobId); await refreshActivity();
  }

  async function runDirectStage(episode: Episode, kind: "media" | "candidates") {
    try {
      const resume_from_stage = kind === "media" ? "stage2_media" : "stage3_candidates";
      const job = await api<Job>(`/api/episodes/${episode.id}/enqueue`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({ resume_from_stage }) });
      setMessage(kind === "media" ? `Медиа-анализ поставлен в очередь, задача №${job.id}` : `Поиск кандидатов поставлен в очередь, задача №${job.id}`);
    } catch (error) { setMessage(`Ошибка: ${errorMessage(error)}`); }
    finally { await refresh().catch(() => undefined); }
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
    const data = await api<{ crop_offset_x: number; faces_detected: number; keyframes: { time: number; offset: number }[]; active_speaker_frames: number; identified_speaker_frames: number; lip_motion_frames: number; face_model: string; held_frames: number; largest_face_frames: number; average_confidence: number }>(`/api/candidates/${candidate.id}/auto-crop`, { method: "POST" });
    setCandidateEdit(candidate.id, { crop: "auto-follow", offset: data.crop_offset_x });
    await loadCandidates(candidate.episode_id, false);
    setMessage(data.faces_detected ? `Траектория: ${data.keyframes.length} точек · уверенность ${Math.round(data.average_confidence * 100)}% · персонаж: ${data.identified_speaker_frames} · губы: ${data.lip_motion_frames} · удержано: ${data.held_frames}` : "Лица не найдены, оставлен центр кадра");
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

  async function createStoryArc() {
    const seasonId = selectedArcSeasonId();
    if (!seasonId) return;
    try {
      const arc = await api<StoryArc>("/api/story-arcs", {
        method: "POST", headers: jsonHeaders, body: JSON.stringify({
          season_id: seasonId,
          title: arcTitle || null,
          prompt: arcPrompt,
          arc_type: arcCharacterId ? "character" : arcType,
          output_format: arcFormat,
          target_character_id: arcCharacterId,
          max_segments: arcMaxSegments,
          max_duration_seconds: arcMaxDuration,
        }),
      });
      setStoryArcs((current) => [arc, ...current.filter((item) => item.id !== arc.id)]);
      setMessage(`Монтажный план создан: ${arc.segments.length} частей, ${formatElapsed(Math.round(arc.total_duration_seconds))}`);
    } catch (error) { setMessage(`Арка не создана: ${errorMessage(error)}`); }
  }

  async function rebuildStoryArc(arcId: number) {
    const arc = await api<StoryArc>(`/api/story-arcs/${arcId}/rebuild`, { method: "POST" });
    setStoryArcs((current) => current.map((item) => item.id === arc.id ? arc : item));
    setMessage(`Арка пересобрана: ${arc.segments.length} частей`);
  }

  async function deleteStoryArc(arcId: number) {
    if (!window.confirm("Удалить монтажный план? Кандидаты, серии и готовые ролики останутся на месте.")) return;
    await api(`/api/story-arcs/${arcId}`, { method: "DELETE" });
    setStoryArcs((current) => current.filter((item) => item.id !== arcId));
    setMessage("Монтажный план удалён");
  }

  async function renderStoryArc(arc: StoryArc, includeSubtitles: boolean) {
    setArcRenderBusy(arc.id);
    setMessage(`Ставим монтажный план «${arc.title}» в очередь…`);
    try {
      const result = await api<{ job: Job }>(`/api/story-arcs/${arc.id}/render-job`, {
        method: "POST", headers: jsonHeaders, body: JSON.stringify({
          include_subtitles: includeSubtitles,
          use_nvenc: settings?.render_use_nvenc ?? null,
          preset_name: settings?.render_preset ?? null,
          loudnorm_two_pass: settings?.render_loudnorm_two_pass ?? null,
          force_rerender: true,
          transition_style: arcTransition,
          include_narration: arcIncludeNarration && arcNarrationMode !== "none",
          narration_mode: arcNarrationMode,
        }),
      });
      setMessage(`StoryArc поставлен в очередь, задача №${result.job.id}`);
      await refreshActivity();
    } catch (error) { setMessage(`StoryArc не отрендерен: ${errorMessage(error)}`); }
    finally { setArcRenderBusy(null); }
  }

  async function enqueueStoryArcRender(arc: StoryArc, includeSubtitles: boolean) {
    const result = await api<{ job: Job }>(`/api/story-arcs/${arc.id}/render-job`, {
      method: "POST", headers: jsonHeaders, body: JSON.stringify({
        include_subtitles: includeSubtitles,
        use_nvenc: settings?.render_use_nvenc ?? null,
        preset_name: settings?.render_preset ?? null,
        loudnorm_two_pass: settings?.render_loudnorm_two_pass ?? null,
        force_rerender: true,
        transition_style: arcTransition,
        include_narration: arcIncludeNarration && arcNarrationMode !== "none",
        narration_mode: arcNarrationMode,
      }),
    });
    setMessage(`StoryArc поставлен в очередь, задача №${result.job.id}`);
    await refreshActivity();
  }

  async function saveArcMeta(arc: StoryArc) {
    const updated = await api<StoryArc>(`/api/story-arcs/${arc.id}`, {
      method: "PATCH", headers: jsonHeaders, body: JSON.stringify({
        title: arc.title,
        prompt: arc.prompt,
        output_format: arc.output_format,
        status: arc.status,
      }),
    });
    setStoryArcs((current) => current.map((item) => item.id === updated.id ? updated : item));
    setMessage("StoryArc сохранён");
  }

  async function saveArcSegment(arcId: number, segment: StoryArcSegment) {
    const updated = await api<StoryArc>(`/api/story-arcs/${arcId}/segments/${segment.id}`, {
      method: "PATCH", headers: jsonHeaders, body: JSON.stringify({
        sort_order: segment.sort_order,
        start_time: segment.start_time,
        end_time: segment.end_time,
        title: segment.title,
        note: segment.note,
        role: segment.role,
      }),
    });
    setStoryArcs((current) => current.map((item) => item.id === updated.id ? updated : item));
    setMessage("Сегмент сохранён");
  }

  async function moveArcSegment(arcId: number, segment: StoryArcSegment, delta: number) {
    const updated = await api<StoryArc>(`/api/story-arcs/${arcId}/segments/${segment.id}`, {
      method: "PATCH", headers: jsonHeaders, body: JSON.stringify({ sort_order: Math.max(1, segment.sort_order + delta) }),
    });
    setStoryArcs((current) => current.map((item) => item.id === updated.id ? updated : item));
  }

  async function removeArcSegment(arcId: number, segmentId: number) {
    const updated = await api<StoryArc>(`/api/story-arcs/${arcId}/segments/${segmentId}`, { method: "DELETE" });
    setStoryArcs((current) => current.map((item) => item.id === updated.id ? updated : item));
    setMessage("Сегмент удалён из плана");
  }

  async function runSeasonSearch() {
    const seasonId = selectedArcSeasonId();
    if (!seasonId || !seasonSearch.trim()) return;
    const data = await api<{ results: SearchResult[] }>(`/api/seasons/${seasonId}/search?q=${encodeURIComponent(seasonSearch)}&limit=30`);
    setSearchResults(data.results);
    setMessage(`Найдено по сезону: ${data.results.length}`);
  }

  async function addSearchResultToArc(arc: StoryArc, result: SearchResult) {
    if (!result.candidate_id) { setMessage("В StoryArc можно добавить только готовый кандидат"); return; }
    const updated = await api<StoryArc>(`/api/story-arcs/${arc.id}/segments`, {
      method: "POST", headers: jsonHeaders, body: JSON.stringify({ candidate_id: result.candidate_id }),
    });
    setStoryArcs((current) => current.map((item) => item.id === updated.id ? updated : item));
    setMessage("Кандидат добавлен в StoryArc");
  }

  async function createVideoScriptForArc(arc: StoryArc) {
    const script = await api<VideoScript>("/api/video-scripts", {
      method: "POST", headers: jsonHeaders, body: JSON.stringify({
        season_id: arc.season_id,
        story_arc_id: arc.id,
        title: `Сценарий: ${arc.title}`,
        prompt: scriptPrompt,
        style: "chronological",
      }),
    });
    setVideoScripts((current) => [script, ...current]);
    setMessage("Сценарий создан");
  }

  async function synthesizeNarration(arc: StoryArc) {
    const audio = await api<{ audio_path: string }>(`/api/story-arcs/${arc.id}/narration-audio?narration_mode=${arcNarrationMode}`, { method: "POST" });
    setMessage(`WAV озвучки создан: ${audio.audio_path}`);
    setStoryArcs(await api<StoryArc[]>("/api/story-arcs"));
  }

  async function createPublishingPlanForArc(arc: StoryArc) {
    const latestExport = arc.exports[0];
    const plan = await api<PublishingPlan>("/api/publishing-plans", {
      method: "POST", headers: jsonHeaders, body: JSON.stringify({
        season_id: arc.season_id,
        story_arc_id: arc.id,
        story_arc_export_id: latestExport?.id ?? null,
        platform: settings?.render_preset ?? "youtube_shorts",
      }),
    });
    setPublishingPlans((current) => [plan, ...current]);
    setMessage("План публикации создан; после рендера соберите локальный пакет");
  }

  async function createPublishingPackageForPlan(plan: PublishingPlan) {
    try {
      const result = await api<{ plan_id: number; manifest_path: string }>(`/api/publishing-plans/${plan.id}/package`, { method: "POST" });
      setMessage(`Локальный пакет готов: ${result.manifest_path}`);
      setPublishingPlans(await api<PublishingPlan[]>("/api/publishing-plans"));
    } catch (error) { setMessage(`Пакет не создан: ${errorMessage(error)}`); }
  }

  async function refreshProjectDiagnostics() {
    const data = await api<ProjectDiagnostics>("/api/project-diagnostics");
    setProjectDiagnostics(data);
    setMessage("Диагностика проекта обновлена");
  }

  async function openArcSegment(segment: StoryArcSegment) {
    const data = await api<Candidate[]>(`/api/episodes/${segment.episode_id}/candidates`);
    setCandidates((current) => ({ ...current, [segment.episode_id]: data }));
    setSelectedEpisodeId(segment.episode_id);
    await loadEpisodeDetails(segment.episode_id);
    const candidate = data.find((item) => item.id === segment.candidate_id);
    if (candidate) await openCandidate(candidate, true);
  }

  async function mergeCharacter(sourceId: number, targetId: number) {
    if (!storyContext || !targetId || sourceId === targetId) return;
    if (!window.confirm("Объединить этого персонажа с выбранным? Привязки голосов перейдут к целевой карточке.")) return;
    await api<Character>(`/api/characters/${sourceId}/merge`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({ target_character_id: targetId }) });
    await loadEpisodeDetails(storyContext.episode_id); setMessage("Карточки персонажей объединены");
  }

  async function autoExport(episodeId: number) {
    const job = await api<Job>(`/api/episodes/${episodeId}/enqueue`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ resume_from_stage: "auto_export", auto: true }),
    });
    setMessage(`Автоэкспорт поставлен в очередь, задача №${job.id}`);
    await refreshActivity();
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
  function patchArcLocal(arcId: number, patch: Partial<StoryArc>) {
    setStoryArcs((current) => current.map((arc) => arc.id === arcId ? { ...arc, ...patch } : arc));
  }
  function patchArcSegmentLocal(arcId: number, segmentId: number, patch: Partial<StoryArcSegment>) {
    setStoryArcs((current) => current.map((arc) => arc.id === arcId ? { ...arc, segments: arc.segments.map((segment) => segment.id === segmentId ? { ...segment, ...patch } : segment) } : arc));
  }
  function selectedArcSeasonId() {
    return arcSeasonId ?? storyContext?.season_id ?? seasons[0]?.id ?? null;
  }
  function patchSettings(patch: Partial<RuntimeSettings>) { setSettings((current) => current ? { ...current, ...patch } : current); }
  function updateSubtitle(index: number, patch: Partial<Subtitle>) { setSubtitles((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item)); }
  function onVideoTimeUpdate() { const player = videoRef.current; const background = backgroundVideoRef.current; if (!player) return; setVideoTime(player.currentTime); if (background && Math.abs(background.currentTime - player.currentTime) > 0.2) background.currentTime = player.currentTime; if (selectedCandidate) { const end = Number((edits[selectedCandidate.id] ?? editFromCandidate(selectedCandidate)).end); if (player.currentTime >= end) player.pause(); } }
  function isEpisodeBusy(episodeId: number) { return (queue?.items ?? []).some((job) => job.episode_id === episodeId && ["queued", "running", "paused", "cancel_requested"].includes(job.status)); }

  useEffect(() => { refresh().catch((error) => setMessage(errorMessage(error))); runSystemCheck().catch((error) => setMessage(errorMessage(error))); }, []);
  useEffect(() => { const timer = window.setInterval(() => refreshActivity().catch(() => undefined), 2500); return () => window.clearInterval(timer); }, [selectedEpisodeId]);
  useEffect(() => {
    const seasonId = selectedArcSeasonId();
    if (!seasonId) { setAvailableArcCharacters([]); return; }
    api<Character[]>(`/api/seasons/${seasonId}/characters`)
      .then(setAvailableArcCharacters)
      .catch(() => setAvailableArcCharacters([]));
  }, [arcSeasonId, storyContext?.season_id, seasons.length]);

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
  const arcSeason = seasons.find((season) => season.id === selectedArcSeasonId());
  const arcCharacters = availableArcCharacters.length ? availableArcCharacters : characters.filter((character) => character.season_id === arcSeason?.id);
  const visibleStoryArcs = storyArcs.filter((arc) => !arcSeason || arc.season_id === arcSeason.id);
  const workflowArc = visibleStoryArcs.find((arc) => arc.id === workflowArcId) ?? visibleStoryArcs[0] ?? null;
  const workflowScripts = videoScripts.filter((script) => !workflowArc || script.story_arc_id === workflowArc.id || script.season_id === workflowArc.season_id).slice(0, 3);
  const workflowPublishing = publishingPlans.filter((plan) => !workflowArc || plan.story_arc_id === workflowArc.id || plan.season_id === workflowArc.season_id).slice(0, 3);

  return <main className="app-shell">
    <section className="topbar"><div><h1>SerialCuts</h1><p>Локальная подготовка вертикальных клипов из серий</p></div><button className="icon-button" title="Обновить всё" onClick={() => refresh()}><RefreshCcw size={20} /></button></section>
    {message && <p className="notice" role="status">{message}</p>}
    <section className="grid dashboard-grid">
      <div className="panel"><div className="panel-title"><FolderPlus size={19} /><h2>Сезоны</h2></div><div className="path-row"><input value={rootPath} onChange={(event) => setRootPath(event.target.value)} placeholder="D:\Сериалы\Название\Сезон 1" /><button onClick={importSeason}>Добавить</button></div><div className="season-list">
        {seasons.map((season) => <article className="season" key={season.id}><div><strong>{season.title}</strong><small>{season.episodes.length} серий</small></div><button onClick={() => enqueueSeason(season.id, false)}>Анализ сезона</button><button onClick={() => enqueueSeason(season.id, true)}><Sparkles size={16} /> Auto</button></article>)}
        {!seasons.length && <p className="empty">Добавьте папку с сериями — исходные файлы останутся без изменений.</p>}
      </div></div>
      <QueuePanel queue={queue} jobStages={jobStages} onRunNext={runQueueNext} onSetPaused={setPaused} onLoadStages={loadJobStages} onCancel={cancelJob} onRetry={retryJob} onRetryStage={retryJobStage} />
    </section>

    <section className="panel section-gap"><div className="panel-title"><ListVideo size={19} /><h2>Серии</h2></div><div className="episodes">{seasons.flatMap((season) => season.episodes).map((episode) => { const busy = isEpisodeBusy(episode.id); return <article className="episode" key={episode.id}><div><strong>{episode.file_name}</strong><small>{busy ? "Обрабатывается в очереди" : stageLabel(episode.stage)}</small></div><span>{formatBytes(episode.size_bytes)}</span><span>{episode.width && episode.height ? `${episode.width}×${episode.height}` : "без метаданных"}</span><button disabled={busy} onClick={() => enqueueEpisode(episode)}>В очередь</button><button className="secondary" disabled={busy} onClick={() => runDirectStage(episode, "media")}>Только медиа</button><button className="secondary" disabled={busy} onClick={() => runDirectStage(episode, "candidates")}>Только кандидаты</button><button onClick={() => loadCandidates(episode.id)}>Открыть</button><button className="secondary" disabled={busy} onClick={() => autoExport(episode.id)}>Auto export</button></article>; })}</div></section>

    <section className="story-arc-workspace section-gap">
      <div className="panel"><div className="panel-title"><BookOpen size={19} /><h2>Сюжетные видео</h2><span className="badge">{visibleStoryArcs.length}</span></div><div className="arc-form"><label><span>Сезон</span><select value={arcSeason?.id ?? ""} onChange={(event) => setArcSeasonId(Number(event.target.value) || null)}>{seasons.map((season) => <option key={season.id} value={season.id}>{season.title}</option>)}</select></label><label><span>Формат</span><select value={arcFormat} onChange={(event) => setArcFormat(event.target.value as StoryArc["output_format"])}><option value="single_short">Один Shorts</option><option value="shorts_series">Серия Shorts</option><option value="story_video">Видео 2–10 мин</option><option value="long_video">Длинное видео</option></select></label><label><span>Персонаж</span><select value={arcCharacterId ?? ""} onChange={(event) => setArcCharacterId(Number(event.target.value) || null)}><option value="">Без персонажа</option>{arcCharacters.map((character) => <option key={character.id} value={character.id}>{character.name}</option>)}</select></label><SettingNumber title="Частей" hint="Сколько фрагментов попадёт в план." value={arcMaxSegments} min={1} max={40} onChange={setArcMaxSegments} /><SettingNumber title="Лимит, сек." hint="Суммарная длительность монтажного плана." value={arcMaxDuration} min={15} max={7200} onChange={setArcMaxDuration} /><SettingText title="Название" hint="Можно оставить пустым." value={arcTitle} onChange={setArcTitle} /><label className="setting-field setting-field-wide"><span>Запрос к арке</span><textarea rows={3} value={arcPrompt} onChange={(event) => setArcPrompt(event.target.value)} placeholder="Например: как герой узнал правду об отце, развитие отношений, вся линия конфликта…" /><small>План строится из уже найденных кандидатов сезона.</small></label><button disabled={!arcSeason} onClick={createStoryArc}><Sparkles size={16} /> Создать план</button></div></div>
      <div className="panel"><div className="panel-title"><Clapperboard size={19} /><h2>Монтажные планы</h2></div><div className="arc-list">{visibleStoryArcs.map((arc) => { const latestExport = arc.exports[0]; const narration = arcNarration(arc); return <article className="arc-card" key={arc.id}><div className="arc-head"><div><strong>{arc.title}</strong><small>{formatArcFormat(arc.output_format)} · {formatElapsed(Math.round(arc.total_duration_seconds))}{arc.target_character_name ? ` · ${arc.target_character_name}` : ""}</small></div><div><button className="text-button" onClick={() => rebuildStoryArc(arc.id)}>Пересобрать</button><button className="text-button danger" onClick={() => deleteStoryArc(arc.id)}>Удалить</button></div></div>{arc.prompt && <p>{arc.prompt}</p>}<div className="arc-actions"><button disabled={arcRenderBusy === arc.id || !arc.segments.length} onClick={() => renderStoryArc(arc, true)}>{arcRenderBusy === arc.id ? <LoaderCircle className="spinner" size={16} /> : <Clapperboard size={16} />} Рендер плана</button><button className="secondary" disabled={arcRenderBusy === arc.id || !arc.segments.length} onClick={() => renderStoryArc(arc, false)}>Без субтитров</button></div>{latestExport && <div className="arc-export"><video controls preload="none" src={`/api/story-arc-exports/${latestExport.id}/file`} /><small title={latestExport.output_path}>{latestExport.segment_count} частей · {latestExport.preset_name} · {latestExport.transition_style} · {latestExport.narration_included ? "с озвучкой" : "без озвучки"} · {statusLabel(latestExport.status)} · {latestExport.output_path}</small></div>}{narration.length > 0 && <details className="arc-narration"><summary>Текст озвучки от лица героя</summary>{narration.map((line) => <p key={line.order}><strong>{line.order}.</strong> {line.text}</p>)}</details>}<ol className="arc-segments">{arc.segments.map((segment) => <li key={segment.id}><button onClick={() => openArcSegment(segment)}><span>{segment.sort_order}</span><strong>{segment.title}</strong><small>{segment.episode_file_name} · {formatRange(segment.start_time, segment.end_time)} · {segment.role ?? "часть"}{segment.candidate_score != null ? ` · score ${segment.candidate_score}` : ""}</small></button></li>)}</ol></article>; })}{!visibleStoryArcs.length && <p className="empty">Когда в сезоне появятся кандидаты, здесь можно собрать арку из нескольких серий.</p>}</div></div>
    </section>

    {selectedEpisodeId && storyContext && <section className="story-dashboard section-gap">
      <div className="panel story-panel"><div className="panel-title"><BookOpen size={19} /><h2>Сюжетный контекст</h2><span className="badge">{storyContext.candidate_mode === "story" ? "Связный пересказ" : "Лучшие моменты"}</span></div>
        <div className="story-mode"><button className={storyContext.candidate_mode === "highlights" ? "" : "secondary"} onClick={() => setStoryContext({ ...storyContext, candidate_mode: "highlights" })}>Лучшие моменты</button><button className={storyContext.candidate_mode === "story" ? "" : "secondary"} onClick={() => setStoryContext({ ...storyContext, candidate_mode: "story" })}>Сюжет серии</button></div>
        <label className="story-field"><span>Общая суть сезона</span><textarea rows={4} value={storyContext.season_context} onChange={(event) => setStoryContext({ ...storyContext, season_context: event.target.value })} placeholder="Главные персонажи, отношения, общая история и тон сезона…" /></label>
        <label className="story-field"><span>Суть этой серии</span><textarea rows={4} value={storyContext.episode_summary} onChange={(event) => setStoryContext({ ...storyContext, episode_summary: event.target.value })} placeholder="Завязка, конфликт, важный поворот и итог серии…" /></label>
        <div className="story-columns"><label className="story-field"><span>Обязательно показать</span><textarea rows={3} value={storyContext.required_events.join("\n")} onChange={(event) => setStoryContext({ ...storyContext, required_events: splitLines(event.target.value) })} placeholder="По одному событию на строку" /></label><label className="story-field"><span>Не включать</span><textarea rows={3} value={storyContext.excluded_events.join("\n")} onChange={(event) => setStoryContext({ ...storyContext, excluded_events: splitLines(event.target.value) })} placeholder="Второстепенные линии или нежелательные сцены" /></label></div>
        <label className="inline-check"><input type="checkbox" checked={storyContext.spoilers_allowed} onChange={(event) => setStoryContext({ ...storyContext, spoilers_allowed: event.target.checked })} /> Можно показывать концовку серии</label>
        <div className="story-actions"><button onClick={saveStoryContext}><Save size={16} /> Сохранить контекст</button><button className="secondary" disabled={isEpisodeBusy(selectedEpisodeId)} onClick={regenerateStoryCandidates}><Sparkles size={16} /> Пересоздать кандидатов</button></div>
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

    <section className="panel section-gap workflow-panel"><div className="panel-title"><Activity size={19} /><h2>Workflow сезона</h2><button className="icon-button secondary" title="Диагностика проекта" onClick={refreshProjectDiagnostics}><RefreshCcw size={17} /></button></div>
      <div className="workflow-grid">
        <div className="workflow-block"><h3>Поиск</h3><div className="search-row"><input value={seasonSearch} onChange={(event) => setSeasonSearch(event.target.value)} placeholder="Найти сцену, реплику или событие по сезону" /><button disabled={!arcSeason || !seasonSearch.trim()} onClick={runSeasonSearch}><Search size={16} /> Найти</button></div><div className="search-results">{searchResults.slice(0, 6).map((result) => <article key={`${result.kind}-${result.episode_id}-${result.start_time}`}><div><strong>{result.title}</strong><small>{result.episode_file_name} · {formatRange(result.start_time, result.end_time)} · score {result.score}</small></div><p>{result.snippet}</p>{workflowArc && result.candidate_id && <button className="text-button" onClick={() => addSearchResultToArc(workflowArc, result)}>Добавить в StoryArc</button>}</article>)}{!searchResults.length && <small>Поиск работает по кандидатам и транскриптам выбранного сезона.</small>}</div></div>
        <div className="workflow-block">
          <h3>StoryArc редактор</h3>
          {workflowArc ? <>
            <label className="setting-field">
              <span>План</span>
              <select value={workflowArc.id} onChange={(event) => setWorkflowArcId(Number(event.target.value))}>
                {visibleStoryArcs.map((arc) => <option key={arc.id} value={arc.id}>{arc.title}</option>)}
              </select>
              <small>{workflowArc.segments.length} частей · {formatElapsed(Math.round(workflowArc.total_duration_seconds))}</small>
            </label>
            <div className="arc-edit-row">
              <input value={workflowArc.title} onChange={(event) => patchArcLocal(workflowArc.id, { title: event.target.value })} />
              <select value={workflowArc.output_format} onChange={(event) => patchArcLocal(workflowArc.id, { output_format: event.target.value as StoryArc["output_format"] })}>
                <option value="single_short">Один Shorts</option>
                <option value="shorts_series">Серия Shorts</option>
                <option value="story_video">Видео 2–10 мин</option>
                <option value="long_video">Длинное видео</option>
              </select>
              <button onClick={() => saveArcMeta(workflowArc)}><Save size={16} /> Сохранить</button>
            </div>
            <label className="setting-field">
              <span>Переходы</span>
              <select value={arcTransition} onChange={(event) => setArcTransition(event.target.value as "cut" | "fade")}>
                <option value="fade">Fade</option>
                <option value="cut">Склейка без перехода</option>
              </select>
              <small>Применяется при StoryArc-рендере.</small>
            </label>
            <SettingCheck title="Добавлять озвучку" hint="Локальная озвучка смешивается с приглушённым звуком оригинала." checked={arcIncludeNarration} onChange={setArcIncludeNarration} />
            <label className="setting-field">
              <span>Режим озвучки</span>
              <select value={arcNarrationMode} onChange={(event) => { const mode = event.target.value as "first_person" | "narrator" | "none"; setArcNarrationMode(mode); setArcIncludeNarration(mode !== "none"); }}>
                <option value="first_person">От лица героя</option>
                <option value="narrator">Нейтральный диктор</option>
                <option value="none">Без озвучки</option>
              </select>
              <small>Это локальный TTS, не имитация голоса актёра.</small>
            </label>
            <div className="arc-actions">
              <button disabled={arcRenderBusy === workflowArc.id || !workflowArc.segments.length} onClick={() => enqueueStoryArcRender(workflowArc, true)}><Clapperboard size={16} /> В очередь</button>
              <button className="secondary" disabled={arcRenderBusy === workflowArc.id || !workflowArc.segments.length} onClick={() => renderStoryArc(workflowArc, false)}>Без субтитров</button>
              <button className="secondary" onClick={() => synthesizeNarration(workflowArc)}><Volume2 size={16} /> WAV</button>
            </div>
          </> : <p className="empty">Создайте StoryArc, чтобы редактировать сезонный монтаж.</p>}
        </div>
        <div className="workflow-block workflow-wide"><h3>Сегменты</h3>{workflowArc ? <div className="segment-editor">{workflowArc.segments.map((segment) => <article key={segment.id}><div className="segment-row"><button className="icon-button secondary" title="Выше" onClick={() => moveArcSegment(workflowArc.id, segment, -1)}>↑</button><button className="icon-button secondary" title="Ниже" onClick={() => moveArcSegment(workflowArc.id, segment, 1)}>↓</button><input type="number" min="0" step="0.1" value={segment.start_time} onChange={(event) => patchArcSegmentLocal(workflowArc.id, segment.id, { start_time: Number(event.target.value) })} /><input type="number" min="0" step="0.1" value={segment.end_time} onChange={(event) => patchArcSegmentLocal(workflowArc.id, segment.id, { end_time: Number(event.target.value) })} /><input value={segment.title} onChange={(event) => patchArcSegmentLocal(workflowArc.id, segment.id, { title: event.target.value })} /><input value={segment.role ?? ""} onChange={(event) => patchArcSegmentLocal(workflowArc.id, segment.id, { role: event.target.value || null })} /><button onClick={() => saveArcSegment(workflowArc.id, segment)}><Save size={16} /></button><button className="icon-button danger" title="Удалить" onClick={() => removeArcSegment(workflowArc.id, segment.id)}><Trash2 size={16} /></button></div><small>{segment.episode_file_name} · {segment.note}</small></article>)}</div> : <p className="empty">Сегменты появятся после создания плана.</p>}</div>
        <div className="workflow-block"><h3>Сценарий</h3>{workflowArc ? <><textarea rows={3} value={scriptPrompt} onChange={(event) => setScriptPrompt(event.target.value)} placeholder="Акцент для сценария: конфликт, развитие героя, быстрый пересказ…" /><button onClick={() => createVideoScriptForArc(workflowArc)}><FileText size={16} /> Создать сценарий</button></> : <small>Нужен StoryArc.</small>}<div className="script-list">{workflowScripts.map((script) => <details key={script.id}><summary>{script.title}</summary><pre>{script.script_text}</pre></details>)}</div></div>
        <div className="workflow-block"><h3>Публикация</h3>{workflowArc ? <button onClick={() => createPublishingPlanForArc(workflowArc)}><CalendarDays size={16} /> Создать план</button> : <small>Нужен StoryArc.</small>}<div className="publishing-list">{workflowPublishing.map((plan) => <article key={plan.id}><strong>{plan.title}</strong><small>{plan.platform} · {statusLabel(plan.status)}</small><p>{plan.description}</p><small>{plan.hashtags.join(" ")}</small><button className="text-button" disabled={!plan.story_arc_export_id} onClick={() => createPublishingPackageForPlan(plan)}>Собрать publishing.json</button></article>)}</div></div>
        <div className="workflow-block"><h3>Диагностика</h3><div className="checks compact">{projectDiagnostics?.checks.map((item) => <div className="check" key={item.name}><span className={item.ok ? "dot ok" : "dot fail"} /><strong>{item.name}</strong><span>{item.message}</span></div>)}</div>{projectDiagnostics?.recommendations.map((item) => <small className="warn-text" key={item}>{item}</small>)}</div>
      </div>
    </section>

    <ExportsPanel exports={exports} />

    <section className="grid section-gap">
      <SystemPanel checks={checks} diagnostics={diagnostics} cacheInfo={cacheInfo} onRefresh={runSystemCheck} onClearCache={clearCache} />
      <SettingsPanel settings={settings} onPatch={patchSettings} onSave={saveSettings} />
    </section>
  </main>;
}

createRoot(document.getElementById("root")!).render(<App />);
