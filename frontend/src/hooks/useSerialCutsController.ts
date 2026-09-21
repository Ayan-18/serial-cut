import { useEffect, useState } from "react";

import { api } from "../api";
import type { CacheInfo, Candidate, Episode, ExportItem, ProjectDiagnostics, PublishingPlan, QueueData, RuntimeSettings, Season, StoryArc, VideoScript } from "../types";
import { errorMessage } from "../utils";
import { useCandidateWorkspace } from "./controller/useCandidateWorkspace";
import { useCharacterWorkspace } from "./controller/useCharacterWorkspace";
import { useDashboardData } from "./controller/useDashboardData";
import { useStoryArcWorkspace } from "./controller/useStoryArcWorkspace";

/**
 * Composition root for the whole app's client state. The actual state and
 * per-domain logic live in `./controller/*` (dashboard/queue, candidate
 * workspace, characters, story arcs); this file only:
 *  - wires the small number of genuinely cross-domain values each domain
 *    hook needs from another (e.g. the story-arc workspace needs the
 *    candidate workspace's `openCandidate` to jump into a segment),
 *  - owns the handful of truly global concerns (the status `message`,
 *    `refresh`/`refreshActivity`, the mount/SSE effects), and
 *  - re-exposes every domain hook's fields under their original names, so
 *    `AppView` (and the `SerialCutsController` type it's built against)
 *    don't need to change.
 */
export function useSerialCutsController() {
  const [message, setMessage] = useState("");
  const [projectDiagnostics, setProjectDiagnostics] = useState<ProjectDiagnostics | null>(null);

  const dashboard = useDashboardData({ setMessage });

  const candidateWorkspace = useCandidateWorkspace({ setMessage, settings: dashboard.settings });

  const characterWorkspace = useCharacterWorkspace({
    setMessage,
    selectedEpisodeId: candidateWorkspace.selectedEpisodeId,
    selectedCandidate: candidateWorkspace.selectedCandidate,
    setSubtitles: candidateWorkspace.setSubtitles,
    setCandidateSort: candidateWorkspace.setCandidateSort,
  });

  // Loading a season's episode details (story context, characters, speaker
  // labels) is triggered by switching episodes, not bundled into
  // `loadCandidates` itself — this is what used to be an inline
  // `await loadEpisodeDetails(episodeId)` inside `loadCandidates`.
  useEffect(() => {
    if (!candidateWorkspace.selectedEpisodeId) return;
    characterWorkspace.loadEpisodeDetails(candidateWorkspace.selectedEpisodeId).catch((error) => setMessage(errorMessage(error)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidateWorkspace.selectedEpisodeId]);

  const storyArcWorkspace = useStoryArcWorkspace({
    setMessage,
    seasons: dashboard.seasons,
    settings: dashboard.settings,
    storyContext: characterWorkspace.storyContext,
    characters: characterWorkspace.characters,
    setCandidates: candidateWorkspace.setCandidates,
    setSelectedEpisodeId: candidateWorkspace.setSelectedEpisodeId,
    openCandidate: candidateWorkspace.openCandidate,
    loadEpisodeDetails: characterWorkspace.loadEpisodeDetails,
  });

  async function refresh() {
    const [seasonData, queueData, settingsData, exportData, cacheData, arcData, scriptData, publishingData, projectData] = await Promise.all([
      api<Season[]>("/api/seasons"), api<QueueData>("/api/jobs"), api<RuntimeSettings>("/api/settings"),
      api<ExportItem[]>("/api/exports"), api<CacheInfo>("/api/cache"), api<StoryArc[]>("/api/story-arcs"),
      api<VideoScript[]>("/api/video-scripts"), api<PublishingPlan[]>("/api/publishing-plans"), api<ProjectDiagnostics>("/api/project-diagnostics"),
    ]);
    dashboard.setSeasons(seasonData); dashboard.setQueue(queueData); dashboard.setSettings(settingsData);
    dashboard.setExports(exportData); dashboard.setCacheInfo(cacheData);
    storyArcWorkspace.setStoryArcs(arcData); storyArcWorkspace.setVideoScripts(scriptData); storyArcWorkspace.setPublishingPlans(publishingData);
    setProjectDiagnostics(projectData);
  }

  // Same "reload the queue/exports, and the open episode's candidates if
  // nothing is running" behaviour the original single hook had — kept here
  // because it's the one place that legitimately needs both the dashboard's
  // queue state and the candidate workspace's `loadCandidates`.
  async function refreshActivity() {
    const [queueData, exportData] = await Promise.all([api<QueueData>("/api/jobs"), api<ExportItem[]>("/api/exports")]);
    dashboard.setQueue(queueData); dashboard.setExports(exportData);
    if (candidateWorkspace.selectedEpisodeId && !queueData.items.some((job) => job.status === "running")) {
      await candidateWorkspace.loadCandidates(candidateWorkspace.selectedEpisodeId, false);
    }
  }

  async function refreshProjectDiagnostics() {
    const data = await api<ProjectDiagnostics>("/api/project-diagnostics");
    setProjectDiagnostics(data);
    setMessage("Диагностика проекта обновлена");
  }

  async function deleteEpisode(episode: Episode) {
    if (!window.confirm(`Удалить серию «${episode.file_name}» из списка? Её кандидаты, субтитры, готовые ролики и кэш будут удалены безвозвратно. Исходный видеофайл не тронут.`)) return;
    try {
      await api(`/api/episodes/${episode.id}`, { method: "DELETE" });
      if (candidateWorkspace.selectedEpisodeId === episode.id) { candidateWorkspace.setSelectedEpisodeId(null); candidateWorkspace.setSelectedCandidate(null); }
      setMessage(`Серия «${episode.file_name}» удалена`);
      await refresh();
    } catch (error) { setMessage(`Не удалось удалить серию: ${errorMessage(error)}`); }
  }

  async function deleteSeason(season: Season) {
    if (!window.confirm(`Удалить сезон «${season.title}» со всеми сериями (${season.episodes.length}), кандидатами, монтажными планами и персонажами? Исходные видеофайлы не тронуты.`)) return;
    try {
      await api(`/api/seasons/${season.id}`, { method: "DELETE" });
      if (storyArcWorkspace.arcSeasonId === season.id) storyArcWorkspace.setArcSeasonId(null);
      setMessage(`Сезон «${season.title}» удалён`);
      await refresh();
    } catch (error) { setMessage(`Не удалось удалить сезон: ${errorMessage(error)}`); }
  }

  const runDirectStage = async (episode: Episode, kind: "media" | "candidates") => {
    try { await dashboard.runDirectStage(episode, kind); }
    finally { await refresh().catch(() => undefined); }
  };

  async function regenerateStoryCandidates() {
    if (!characterWorkspace.storyContext) return;
    await characterWorkspace.saveStoryContext();
    const episode = dashboard.seasons.flatMap((item) => item.episodes).find((item) => item.id === characterWorkspace.storyContext!.episode_id);
    if (episode) await runDirectStage(episode, "candidates");
  }

  const importSeason = async () => {
    try { await dashboard.importSeason(); await refresh(); }
    catch (error) { setMessage(errorMessage(error)); }
  };
  const enqueueSeason = async (seasonId: number, auto: boolean) => { await dashboard.enqueueSeason(seasonId, auto); await refreshActivity(); };
  const enqueueEpisode = async (episode: Episode) => { await dashboard.enqueueEpisode(episode); await refreshActivity(); };
  const runQueueNext = async () => { await dashboard.runQueueNext(); await refreshActivity(); };
  const setPaused = async (paused: boolean) => { await dashboard.setPaused(paused); await refreshActivity(); };
  const cancelJob = async (jobId: number) => { await dashboard.cancelJob(jobId); await refreshActivity(); };
  const retryJob = async (jobId: number) => { await dashboard.retryJob(jobId); await refreshActivity(); };
  const retryJobStage = async (jobId: number, stageName: string) => { await dashboard.retryJobStage(jobId, stageName); await refreshActivity(); };
  const autoExport = async (episodeId: number) => { await dashboard.autoExport(episodeId); await refreshActivity(); };
  const deleteJob = async (jobId: number) => {
    try { if (await dashboard.deleteJob(jobId)) await refreshActivity(); }
    catch (error) { setMessage(`Не удалось удалить задачу: ${errorMessage(error)}`); }
  };
  const saveSettings = async () => { if (await dashboard.saveSettings()) await refreshActivity(); };

  const renderCandidate = async (candidate: Candidate, includeSubtitles: boolean) => {
    await candidateWorkspace.renderCandidate(candidate, includeSubtitles); await refreshActivity();
  };
  const batchRenderCandidates = async () => {
    try { if (await candidateWorkspace.batchRenderCandidates()) await refreshActivity(); }
    catch (error) { setMessage(`Пакетный рендер: ${errorMessage(error)}`); }
  };

  const renderStoryArc = async (arc: StoryArc, includeSubtitles: boolean) => {
    if (await storyArcWorkspace.renderStoryArc(arc, includeSubtitles)) await refreshActivity();
  };
  const enqueueStoryArcRender = async (arc: StoryArc, includeSubtitles: boolean) => {
    await storyArcWorkspace.enqueueStoryArcRender(arc, includeSubtitles); await refreshActivity();
  };

  useEffect(() => {
    refresh().catch((error) => setMessage(errorMessage(error)));
    dashboard.runSystemCheck().catch((error) => setMessage(errorMessage(error)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // Live queue updates via SSE; fall back to polling only while the stream is down.
    let fallback: number | null = null;
    let hadRunning = false;
    const startFallback = () => { if (fallback === null) fallback = window.setInterval(() => refreshActivity().catch(() => undefined), 4000); };
    const stopFallback = () => { if (fallback !== null) { window.clearInterval(fallback); fallback = null; } };
    const applyQueue = (data: QueueData) => {
      dashboard.setQueue(data);
      const running = data.items.some((job) => job.status === "running");
      if (hadRunning && !running) refreshActivity().catch(() => undefined);
      hadRunning = running;
    };
    let source: EventSource | null = null;
    try {
      source = new EventSource("/api/events");
      source.addEventListener("queue", (event) => {
        try { applyQueue(JSON.parse((event as MessageEvent).data) as QueueData); } catch { /* skip malformed frame */ }
      });
      source.onopen = () => stopFallback();
      source.onerror = () => startFallback();
    } catch { startFallback(); }
    return () => { source?.close(); stopFallback(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidateWorkspace.selectedEpisodeId]);

  return {
    rootPath: dashboard.rootPath,
    setRootPath: dashboard.setRootPath,
    seasons: dashboard.seasons,
    checks: dashboard.checks,
    queue: dashboard.queue,
    settings: dashboard.settings,
    diagnostics: dashboard.diagnostics,
    cacheInfo: dashboard.cacheInfo,
    exports: dashboard.exports,
    selectedEpisodeId: candidateWorkspace.selectedEpisodeId,
    setSelectedEpisodeId: candidateWorkspace.setSelectedEpisodeId,
    candidates: candidateWorkspace.candidates,
    setCandidates: candidateWorkspace.setCandidates,
    selectedCandidate: candidateWorkspace.selectedCandidate,
    setSelectedCandidate: candidateWorkspace.setSelectedCandidate,
    edits: candidateWorkspace.edits,
    setEdits: candidateWorkspace.setEdits,
    candidateFilter: candidateWorkspace.candidateFilter,
    setCandidateFilter: candidateWorkspace.setCandidateFilter,
    candidateSort: candidateWorkspace.candidateSort,
    setCandidateSort: candidateWorkspace.setCandidateSort,
    candidateSearch: candidateWorkspace.candidateSearch,
    setCandidateSearch: candidateWorkspace.setCandidateSearch,
    candidateMomentType: candidateWorkspace.candidateMomentType,
    setCandidateMomentType: candidateWorkspace.setCandidateMomentType,
    candidateMinScore: candidateWorkspace.candidateMinScore,
    setCandidateMinScore: candidateWorkspace.setCandidateMinScore,
    visibleCandidates: candidateWorkspace.visibleCandidates,
    momentTypes: candidateWorkspace.momentTypes,
    selectedEdit: candidateWorkspace.selectedEdit,
    setCandidateEdit: candidateWorkspace.setCandidateEdit,
    subtitles: candidateWorkspace.subtitles,
    setSubtitles: candidateWorkspace.setSubtitles,
    subtitleBusy: candidateWorkspace.subtitleBusy,
    candidateQuality: candidateWorkspace.candidateQuality,
    episodeQuality: candidateWorkspace.episodeQuality,
    subtitleQuality: candidateWorkspace.subtitleQuality,
    jobStages: dashboard.jobStages,
    previewUrl: candidateWorkspace.previewUrl,
    previewBusy: candidateWorkspace.previewBusy,
    message,
    setMessage,
    videoTime: candidateWorkspace.videoTime,
    storyContext: characterWorkspace.storyContext,
    setStoryContext: characterWorkspace.setStoryContext,
    storyArcs: storyArcWorkspace.storyArcs,
    setStoryArcs: storyArcWorkspace.setStoryArcs,
    videoScripts: storyArcWorkspace.videoScripts,
    publishingPlans: storyArcWorkspace.publishingPlans,
    projectDiagnostics,
    arcSeasonId: storyArcWorkspace.arcSeasonId,
    setArcSeasonId: storyArcWorkspace.setArcSeasonId,
    arcTitle: storyArcWorkspace.arcTitle,
    setArcTitle: storyArcWorkspace.setArcTitle,
    arcPrompt: storyArcWorkspace.arcPrompt,
    setArcPrompt: storyArcWorkspace.setArcPrompt,
    arcFormat: storyArcWorkspace.arcFormat,
    setArcFormat: storyArcWorkspace.setArcFormat,
    arcType: storyArcWorkspace.arcType,
    setArcType: storyArcWorkspace.setArcType,
    arcCharacterId: storyArcWorkspace.arcCharacterId,
    setArcCharacterId: storyArcWorkspace.setArcCharacterId,
    arcMaxSegments: storyArcWorkspace.arcMaxSegments,
    setArcMaxSegments: storyArcWorkspace.setArcMaxSegments,
    arcMaxDuration: storyArcWorkspace.arcMaxDuration,
    setArcMaxDuration: storyArcWorkspace.setArcMaxDuration,
    arcRenderBusy: storyArcWorkspace.arcRenderBusy,
    workflowArcId: storyArcWorkspace.workflowArcId,
    setWorkflowArcId: storyArcWorkspace.setWorkflowArcId,
    arcTransition: storyArcWorkspace.arcTransition,
    setArcTransition: storyArcWorkspace.setArcTransition,
    arcIncludeNarration: storyArcWorkspace.arcIncludeNarration,
    setArcIncludeNarration: storyArcWorkspace.setArcIncludeNarration,
    arcNarrationMode: storyArcWorkspace.arcNarrationMode,
    setArcNarrationMode: storyArcWorkspace.setArcNarrationMode,
    seasonSearch: storyArcWorkspace.seasonSearch,
    setSeasonSearch: storyArcWorkspace.setSeasonSearch,
    searchResults: storyArcWorkspace.searchResults,
    scriptPrompt: storyArcWorkspace.scriptPrompt,
    setScriptPrompt: storyArcWorkspace.setScriptPrompt,
    availableArcCharacters: storyArcWorkspace.availableArcCharacters,
    characters: characterWorkspace.characters,
    speakerLabels: characterWorkspace.speakerLabels,
    speakerIdentities: characterWorkspace.speakerIdentities,
    episodeOutline: characterWorkspace.episodeOutline,
    characterName: characterWorkspace.characterName,
    setCharacterName: characterWorkspace.setCharacterName,
    characterDescription: characterWorkspace.characterDescription,
    setCharacterDescription: characterWorkspace.setCharacterDescription,
    characterPhotos: characterWorkspace.characterPhotos,
    videoRef: candidateWorkspace.videoRef,
    backgroundVideoRef: candidateWorkspace.backgroundVideoRef,
    refresh,
    refreshActivity,
    runSystemCheck: dashboard.runSystemCheck,
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
    loadJobStages: dashboard.loadJobStages,
    loadCandidates: candidateWorkspace.loadCandidates,
    loadEpisodeDetails: characterWorkspace.loadEpisodeDetails,
    saveStoryContext: characterWorkspace.saveStoryContext,
    assignSpeaker: characterWorkspace.assignSpeaker,
    regenerateStoryCandidates,
    createCharacter: characterWorkspace.createCharacter,
    deleteCharacter: characterWorkspace.deleteCharacter,
    readCharacterPhotos: characterWorkspace.readCharacterPhotos,
    addCharacterPhotos: characterWorkspace.addCharacterPhotos,
    deleteCharacterPhoto: characterWorkspace.deleteCharacterPhoto,
    setCharacterNarrationVoice: characterWorkspace.setCharacterNarrationVoice,
    identifyCharacters: characterWorkspace.identifyCharacters,
    openCandidate: candidateWorkspace.openCandidate,
    reviewCandidate: candidateWorkspace.reviewCandidate,
    autoCrop: candidateWorkspace.autoCrop,
    chooseCrop: candidateWorkspace.chooseCrop,
    saveSubtitles: candidateWorkspace.saveSubtitles,
    resetSubtitles: candidateWorkspace.resetSubtitles,
    autoSplitSubtitles: candidateWorkspace.autoSplitSubtitles,
    renderCandidate,
    renderPreview: candidateWorkspace.renderPreview,
    createStoryArc: storyArcWorkspace.createStoryArc,
    rebuildStoryArc: storyArcWorkspace.rebuildStoryArc,
    deleteStoryArc: storyArcWorkspace.deleteStoryArc,
    renderStoryArc,
    enqueueStoryArcRender,
    saveArcMeta: storyArcWorkspace.saveArcMeta,
    saveArcSegment: storyArcWorkspace.saveArcSegment,
    moveArcSegment: storyArcWorkspace.moveArcSegment,
    removeArcSegment: storyArcWorkspace.removeArcSegment,
    runSeasonSearch: storyArcWorkspace.runSeasonSearch,
    addSearchResultToArc: storyArcWorkspace.addSearchResultToArc,
    createVideoScriptForArc: storyArcWorkspace.createVideoScriptForArc,
    synthesizeNarration: storyArcWorkspace.synthesizeNarration,
    createPublishingPlanForArc: storyArcWorkspace.createPublishingPlanForArc,
    createPublishingPackageForPlan: storyArcWorkspace.createPublishingPackageForPlan,
    refreshProjectDiagnostics,
    openArcSegment: storyArcWorkspace.openArcSegment,
    mergeCharacter: characterWorkspace.mergeCharacter,
    autoExport,
    saveSettings,
    clearCache: dashboard.clearCache,
    patchArcLocal: storyArcWorkspace.patchArcLocal,
    patchArcSegmentLocal: storyArcWorkspace.patchArcSegmentLocal,
    selectedArcSeasonId: storyArcWorkspace.selectedArcSeasonId,
    patchSettings: dashboard.patchSettings,
    updateSubtitle: candidateWorkspace.updateSubtitle,
    onVideoTimeUpdate: candidateWorkspace.onVideoTimeUpdate,
    isEpisodeBusy: dashboard.isEpisodeBusy,
    activeSubtitle: candidateWorkspace.activeSubtitle,
    arcSeason: storyArcWorkspace.arcSeason,
    arcCharacters: storyArcWorkspace.arcCharacters,
    visibleStoryArcs: storyArcWorkspace.visibleStoryArcs,
    workflowArc: storyArcWorkspace.workflowArc,
    workflowScripts: storyArcWorkspace.workflowScripts,
    workflowPublishing: storyArcWorkspace.workflowPublishing,
    batchSelection: candidateWorkspace.batchSelection,
    toggleBatchCandidate: candidateWorkspace.toggleBatchCandidate,
    setBatchCandidates: candidateWorkspace.setBatchCandidates,
    clearBatchSelection: candidateWorkspace.clearBatchSelection,
    batchReviewCandidates: candidateWorkspace.batchReviewCandidates,
    batchRenderCandidates,
  };
}

export type SerialCutsController = ReturnType<typeof useSerialCutsController>;
