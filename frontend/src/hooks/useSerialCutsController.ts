import { useEffect, useRef, useState } from "react";

import { api, jsonHeaders } from "../api";
import { useCandidates } from "./useCandidates";
import type { BatchOutcome, CacheInfo, Candidate, CandidateQuality, Character, CheckItem, Episode, EpisodeOutline, EpisodeQuality, ExportItem, ImportResult, Job, JobStage, ModelDiagnostics, PreviewRender, ProjectDiagnostics, PublishingPlan, QueueData, RuntimeSettings, SearchResult, Season, SpeakerIdentity, StoryArc, StoryArcSegment, StoryContext, Subtitle, SubtitleQuality, VideoScript } from "../types";
import { editFromCandidate, errorMessage, fileDataUrl, formatElapsed, stageLabel } from "../utils";

export function useSerialCutsController() {
  const [rootPath, setRootPath] = useState("");
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [checks, setChecks] = useState<CheckItem[]>([]);
  const [queue, setQueue] = useState<QueueData | null>(null);
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [diagnostics, setDiagnostics] = useState<ModelDiagnostics | null>(null);
  const [cacheInfo, setCacheInfo] = useState<CacheInfo | null>(null);
  const [exports, setExports] = useState<ExportItem[]>([]);
  const [selectedEpisodeId, setSelectedEpisodeId] = useState<number | null>(null);
  const {
    candidates,
    setCandidates,
    selectedCandidate,
    setSelectedCandidate,
    edits,
    setEdits,
    candidateFilter,
    setCandidateFilter,
    candidateSort,
    setCandidateSort,
    candidateSearch,
    setCandidateSearch,
    candidateMomentType,
    setCandidateMomentType,
    candidateMinScore,
    setCandidateMinScore,
    visibleCandidates,
    momentTypes,
    selectedEdit,
    setCandidateEdit,
  } = useCandidates(selectedEpisodeId);
  const [subtitles, setSubtitles] = useState<Subtitle[]>([]);
  const [subtitleBusy, setSubtitleBusy] = useState(false);
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
  const [batchSelection, setBatchSelection] = useState<number[]>([]);
  const videoRef = useRef<HTMLVideoElement>(null);
  const backgroundVideoRef = useRef<HTMLVideoElement>(null);

  function toggleBatchCandidate(candidateId: number) {
    setBatchSelection((current) => current.includes(candidateId) ? current.filter((id) => id !== candidateId) : [...current, candidateId]);
  }
  function setBatchCandidates(ids: number[]) { setBatchSelection(ids); }
  function clearBatchSelection() { setBatchSelection([]); }

  async function batchReviewCandidates(episodeId: number, decision: "approve" | "reject") {
    if (!batchSelection.length) return;
    try {
      const outcome = await api<BatchOutcome>(`/api/episodes/${episodeId}/candidates/batch-review`, {
        method: "POST", headers: jsonHeaders, body: JSON.stringify({ candidate_ids: batchSelection, decision }),
      });
      setMessage(`${decision === "approve" ? "Принято" : "Отклонено"}: ${outcome.succeeded.length}${outcome.skipped.length ? `, пропущено ${outcome.skipped.length}` : ""}`);
      clearBatchSelection();
      await loadCandidates(episodeId, false);
    } catch (error) { setMessage(`Пакетная проверка: ${errorMessage(error)}`); }
  }

  async function batchRenderCandidates() {
    if (!batchSelection.length) return;
    try {
      const outcome = await api<BatchOutcome>("/api/candidates/batch-render-job", {
        method: "POST", headers: jsonHeaders, body: JSON.stringify({
          candidate_ids: batchSelection,
          include_subtitles: true,
          use_nvenc: settings?.render_use_nvenc ?? null,
          preset_name: settings?.render_preset ?? null,
          loudnorm_two_pass: settings?.render_loudnorm_two_pass ?? null,
        }),
      });
      setMessage(`Рендеров в очереди: ${outcome.job_ids.length}${outcome.skipped.length ? `, пропущено ${outcome.skipped.length} (не принятые)` : ""}`);
      clearBatchSelection();
      await refreshActivity();
    } catch (error) { setMessage(`Пакетный рендер: ${errorMessage(error)}`); }
  }

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
      const data = await api<ImportResult>("/api/seasons/import", { method: "POST", headers: jsonHeaders, body: JSON.stringify({ root_path: rootPath }) });
      const errorNote = data.errors.length ? `, не прочитано: ${data.errors.length} (${data.errors.map((item) => item.file_name).join(", ")})` : "";
      setMessage(`Просканировано ${data.scanned}: добавлено ${data.created}, дубликатов ${data.skipped_duplicates}${errorNote}`); await refresh();
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

  async function setCharacterNarrationVoice(characterId: number, voice: string | null) {
    if (!storyContext) return;
    await api<Character>(`/api/characters/${characterId}/narration-voice`, {
      method: "PUT", headers: jsonHeaders, body: JSON.stringify({ narration_voice: voice }),
    });
    await loadEpisodeDetails(storyContext.episode_id);
    setMessage(voice ? "Голос озвучки персонажа закреплён" : "Голос озвучки — авто по полу персонажа");
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
      const result = await api<{ analyzed_labels: number; assigned_labels: number; face_model: string; voice_profiles_used: number }>(`/api/episodes/${selectedEpisodeId}/identify-characters`, { method: "POST" });
      await loadEpisodeDetails(selectedEpisodeId);
      if (selectedCandidate) setSubtitles(await api<Subtitle[]>(`/api/candidates/${selectedCandidate.id}/subtitles`));
      if (result.assigned_labels) {
        setMessage(`Определено голосов: ${result.assigned_labels} · ${result.face_model} · голосовых профилей: ${result.voice_profiles_used}`);
      } else if (!result.analyzed_labels) {
        setMessage("Нет меток «Говорящий N» — сначала выполните медиа-анализ серии");
      } else {
        const facePart = result.face_model.includes("YuNet") ? "" : ` (${result.face_model})`;
        setMessage(`Надёжных совпадений не найдено — имена не назначены${facePart}. Проверьте фото персонажей и модели YuNet/SFace.`);
      }
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
  
  function chooseCrop(candidate: Candidate, mode: Candidate["crop_mode"]) {
    // "По лицам" only tracks if a trajectory exists — compute it on selection.
    if (mode === "auto-follow" && !(candidate.crop_keyframes_json?.length)) {
      void autoCrop(candidate);
      return;
    }
    setCandidateEdit(candidate.id, { crop: mode });
  }

  async function autoCrop(candidate: Candidate) {
    setMessage("Ищем активного говорящего по персонажу и движению губ…");
    try {
      const data = await api<{ crop_offset_x: number; faces_detected: number; keyframes: { time: number; offset: number }[]; active_speaker_frames: number; identified_speaker_frames: number; lip_motion_frames: number; face_model: string; held_frames: number; largest_face_frames: number; average_confidence: number }>(`/api/candidates/${candidate.id}/auto-crop`, { method: "POST" });
      setCandidateEdit(candidate.id, { crop: "auto-follow", offset: data.crop_offset_x });
      await loadCandidates(candidate.episode_id, false);
      setMessage(data.keyframes.length
        ? `Траектория: ${data.keyframes.length} точек · ${data.face_model} · персонаж: ${data.identified_speaker_frames} · губы: ${data.lip_motion_frames} · удержано: ${data.held_frames}`
        : "В этом отрывке лица не найдены — оставлен центр кадра");
    } catch (error) {
      setMessage(`Найти лица: ${errorMessage(error)}`);
    }
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
  
  async function deleteEpisode(episode: Episode) {
    if (!window.confirm(`Удалить серию «${episode.file_name}» из списка? Её кандидаты, субтитры, готовые ролики и кэш будут удалены безвозвратно. Исходный видеофайл не тронут.`)) return;
    try {
      await api(`/api/episodes/${episode.id}`, { method: "DELETE" });
      if (selectedEpisodeId === episode.id) { setSelectedEpisodeId(null); setSelectedCandidate(null); }
      setMessage(`Серия «${episode.file_name}» удалена`);
      await refresh();
    } catch (error) { setMessage(`Не удалось удалить серию: ${errorMessage(error)}`); }
  }

  async function deleteSeason(season: Season) {
    if (!window.confirm(`Удалить сезон «${season.title}» со всеми сериями (${season.episodes.length}), кандидатами, монтажными планами и персонажами? Исходные видеофайлы не тронуты.`)) return;
    try {
      await api(`/api/seasons/${season.id}`, { method: "DELETE" });
      if (arcSeasonId === season.id) setArcSeasonId(null);
      setMessage(`Сезон «${season.title}» удалён`);
      await refresh();
    } catch (error) { setMessage(`Не удалось удалить сезон: ${errorMessage(error)}`); }
  }

  async function deleteJob(jobId: number) {
    if (!window.confirm(`Удалить задачу №${jobId} из очереди вместе с историей её этапов?`)) return;
    try {
      await api(`/api/jobs/${jobId}`, { method: "DELETE" });
      setMessage(`Задача №${jobId} удалена`);
      await refreshActivity();
    } catch (error) { setMessage(`Не удалось удалить задачу: ${errorMessage(error)}`); }
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
    try {
      const audio = await api<{ audio_path: string }>(`/api/story-arcs/${arc.id}/narration-audio?narration_mode=${arcNarrationMode}`, { method: "POST" });
      const arcs = await api<StoryArc[]>("/api/story-arcs");
      setStoryArcs(arcs);
      const source = arcs.find((item) => item.id === arc.id)?.plan_json?.narration_source;
      setMessage(source === "template"
        ? `WAV создан, но Qwen недоступна — текст по шаблону. Запустите llama-server и повторите: ${audio.audio_path}`
        : `WAV озвучки создан: ${audio.audio_path}`);
    } catch (error) {
      setMessage(`Озвучка не создана: ${errorMessage(error)}`);
    }
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
  
  useEffect(() => { setBatchSelection([]); }, [selectedEpisodeId]);
  useEffect(() => { refresh().catch((error) => setMessage(errorMessage(error))); runSystemCheck().catch((error) => setMessage(errorMessage(error))); }, []);
  useEffect(() => { const timer = window.setInterval(() => refreshActivity().catch(() => undefined), 2500); return () => window.clearInterval(timer); }, [selectedEpisodeId]);
  useEffect(() => {
    const seasonId = selectedArcSeasonId();
    if (!seasonId) { setAvailableArcCharacters([]); return; }
    api<Character[]>(`/api/seasons/${seasonId}/characters`)
      .then(setAvailableArcCharacters)
      .catch(() => setAvailableArcCharacters([]));
  }, [arcSeasonId, storyContext?.season_id, seasons.length]);
  
  const activeSubtitle = selectedCandidate ? subtitles.find((item) => { const relative = videoTime - Number((edits[selectedCandidate.id] ?? editFromCandidate(selectedCandidate)).start); return relative >= item.start_time && relative <= item.end_time; }) : undefined;
  const arcSeason = seasons.find((season) => season.id === selectedArcSeasonId());
  const arcCharacters = availableArcCharacters.length ? availableArcCharacters : characters.filter((character) => character.season_id === arcSeason?.id);
  const visibleStoryArcs = storyArcs.filter((arc) => !arcSeason || arc.season_id === arcSeason.id);
  const workflowArc = visibleStoryArcs.find((arc) => arc.id === workflowArcId) ?? visibleStoryArcs[0] ?? null;
  const workflowScripts = videoScripts.filter((script) => !workflowArc || script.story_arc_id === workflowArc.id || script.season_id === workflowArc.season_id).slice(0, 3);
  const workflowPublishing = publishingPlans.filter((plan) => !workflowArc || plan.story_arc_id === workflowArc.id || plan.season_id === workflowArc.season_id).slice(0, 3);
  

  return {
    rootPath,
    setRootPath,
    seasons,
    checks,
    queue,
    settings,
    diagnostics,
    cacheInfo,
    exports,
    selectedEpisodeId,
    setSelectedEpisodeId,
    candidates,
    setCandidates,
    selectedCandidate,
    setSelectedCandidate,
    edits,
    setEdits,
    candidateFilter,
    setCandidateFilter,
    candidateSort,
    setCandidateSort,
    candidateSearch,
    setCandidateSearch,
    candidateMomentType,
    setCandidateMomentType,
    candidateMinScore,
    setCandidateMinScore,
    visibleCandidates,
    momentTypes,
    selectedEdit,
    setCandidateEdit,
    subtitles,
    setSubtitles,
    subtitleBusy,
    candidateQuality,
    episodeQuality,
    subtitleQuality,
    jobStages,
    previewUrl,
    previewBusy,
    message,
    setMessage,
    videoTime,
    storyContext,
    setStoryContext,
    storyArcs,
    setStoryArcs,
    videoScripts,
    publishingPlans,
    projectDiagnostics,
    arcSeasonId,
    setArcSeasonId,
    arcTitle,
    setArcTitle,
    arcPrompt,
    setArcPrompt,
    arcFormat,
    setArcFormat,
    arcType,
    setArcType,
    arcCharacterId,
    setArcCharacterId,
    arcMaxSegments,
    setArcMaxSegments,
    arcMaxDuration,
    setArcMaxDuration,
    arcRenderBusy,
    workflowArcId,
    setWorkflowArcId,
    arcTransition,
    setArcTransition,
    arcIncludeNarration,
    setArcIncludeNarration,
    arcNarrationMode,
    setArcNarrationMode,
    seasonSearch,
    setSeasonSearch,
    searchResults,
    scriptPrompt,
    setScriptPrompt,
    availableArcCharacters,
    characters,
    speakerLabels,
    speakerIdentities,
    episodeOutline,
    characterName,
    setCharacterName,
    characterDescription,
    setCharacterDescription,
    characterPhotos,
    videoRef,
    backgroundVideoRef,
    refresh,
    refreshActivity,
    runSystemCheck,
    importSeason,
    enqueueSeason,
    enqueueEpisode,
    deleteEpisode,
    deleteSeason,
    deleteJob,
    runQueueNext,
    setPaused,
    cancelJob,
    retryJob,
    retryJobStage,
    runDirectStage,
    loadJobStages,
    loadCandidates,
    loadEpisodeDetails,
    saveStoryContext,
    assignSpeaker,
    regenerateStoryCandidates,
    createCharacter,
    deleteCharacter,
    readCharacterPhotos,
    addCharacterPhotos,
    deleteCharacterPhoto,
    setCharacterNarrationVoice,
    identifyCharacters,
    openCandidate,
    reviewCandidate,
    autoCrop,
    chooseCrop,
    saveSubtitles,
    resetSubtitles,
    autoSplitSubtitles,
    renderCandidate,
    renderPreview,
    createStoryArc,
    rebuildStoryArc,
    deleteStoryArc,
    renderStoryArc,
    enqueueStoryArcRender,
    saveArcMeta,
    saveArcSegment,
    moveArcSegment,
    removeArcSegment,
    runSeasonSearch,
    addSearchResultToArc,
    createVideoScriptForArc,
    synthesizeNarration,
    createPublishingPlanForArc,
    createPublishingPackageForPlan,
    refreshProjectDiagnostics,
    openArcSegment,
    mergeCharacter,
    autoExport,
    saveSettings,
    clearCache,
    patchArcLocal,
    patchArcSegmentLocal,
    selectedArcSeasonId,
    patchSettings,
    updateSubtitle,
    onVideoTimeUpdate,
    isEpisodeBusy,
    activeSubtitle,
    arcSeason,
    arcCharacters,
    visibleStoryArcs,
    workflowArc,
    workflowScripts,
    workflowPublishing,
    batchSelection,
    toggleBatchCandidate,
    setBatchCandidates,
    clearBatchSelection,
    batchReviewCandidates,
    batchRenderCandidates,
  };
}

export type SerialCutsController = ReturnType<typeof useSerialCutsController>;
