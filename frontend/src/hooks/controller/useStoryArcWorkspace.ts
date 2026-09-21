import { useEffect, useState } from "react";

import { api, jsonHeaders } from "../../api";
import { errorMessage, formatElapsed } from "../../utils";
import type {
  Candidate,
  Character,
  Job,
  PublishingPlan,
  RuntimeSettings,
  Season,
  SearchResult,
  StoryArc,
  StoryArcSegment,
  StoryContext,
  VideoScript,
} from "../../types";

export type UseStoryArcWorkspaceParams = {
  setMessage: (message: string) => void;
  seasons: Season[];
  settings: RuntimeSettings | null;
  storyContext: StoryContext | null;
  characters: Character[];
  /** Needed only by openArcSegment, to jump into a segment's source candidate. */
  setCandidates: (updater: (current: Record<number, Candidate[]>) => Record<number, Candidate[]>) => void;
  setSelectedEpisodeId: (episodeId: number) => void;
  openCandidate: (candidate: Candidate, play?: boolean) => Promise<void>;
  loadEpisodeDetails: (episodeId: number) => Promise<StoryContext>;
};

/**
 * StoryArc plans (single Shorts / series / story video), their segments,
 * season search, video scripts and publishing plans. `renderStoryArc` and
 * `enqueueStoryArcRender` are domain-only — the orchestrator wraps them to
 * refresh the queue afterwards, same as the dashboard/candidate actions.
 */
export function useStoryArcWorkspace({
  setMessage, seasons, settings, storyContext, characters,
  setCandidates, setSelectedEpisodeId, openCandidate, loadEpisodeDetails,
}: UseStoryArcWorkspaceParams) {
  const [storyArcs, setStoryArcs] = useState<StoryArc[]>([]);
  const [videoScripts, setVideoScripts] = useState<VideoScript[]>([]);
  const [publishingPlans, setPublishingPlans] = useState<PublishingPlan[]>([]);
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

  function selectedArcSeasonId() {
    return arcSeasonId ?? storyContext?.season_id ?? seasons[0]?.id ?? null;
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

  /** Domain-only: the caller (orchestrator) refreshes the queue afterwards. Returns false on failure. */
  async function renderStoryArc(arc: StoryArc, includeSubtitles: boolean): Promise<boolean> {
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
      return true;
    } catch (error) { setMessage(`StoryArc не отрендерен: ${errorMessage(error)}`); return false; }
    finally { setArcRenderBusy(null); }
  }

  /** Domain-only: the caller (orchestrator) refreshes the queue afterwards. */
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

  async function openArcSegment(segment: StoryArcSegment) {
    const data = await api<Candidate[]>(`/api/episodes/${segment.episode_id}/candidates`);
    setCandidates((current) => ({ ...current, [segment.episode_id]: data }));
    setSelectedEpisodeId(segment.episode_id);
    await loadEpisodeDetails(segment.episode_id);
    const candidate = data.find((item) => item.id === segment.candidate_id);
    if (candidate) await openCandidate(candidate, true);
  }

  function patchArcLocal(arcId: number, patch: Partial<StoryArc>) {
    setStoryArcs((current) => current.map((arc) => arc.id === arcId ? { ...arc, ...patch } : arc));
  }
  function patchArcSegmentLocal(arcId: number, segmentId: number, patch: Partial<StoryArcSegment>) {
    setStoryArcs((current) => current.map((arc) => arc.id === arcId ? { ...arc, segments: arc.segments.map((segment) => segment.id === segmentId ? { ...segment, ...patch } : segment) } : arc));
  }

  useEffect(() => {
    const seasonId = selectedArcSeasonId();
    if (!seasonId) { setAvailableArcCharacters([]); return; }
    api<Character[]>(`/api/seasons/${seasonId}/characters`)
      .then(setAvailableArcCharacters)
      .catch(() => setAvailableArcCharacters([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [arcSeasonId, storyContext?.season_id, seasons.length]);

  const arcSeason = seasons.find((season) => season.id === selectedArcSeasonId());
  const arcCharacters = availableArcCharacters.length ? availableArcCharacters : characters.filter((character) => character.season_id === arcSeason?.id);
  const visibleStoryArcs = storyArcs.filter((arc) => !arcSeason || arc.season_id === arcSeason.id);
  const workflowArc = visibleStoryArcs.find((arc) => arc.id === workflowArcId) ?? visibleStoryArcs[0] ?? null;
  const workflowScripts = videoScripts.filter((script) => !workflowArc || script.story_arc_id === workflowArc.id || script.season_id === workflowArc.season_id).slice(0, 3);
  const workflowPublishing = publishingPlans.filter((plan) => !workflowArc || plan.story_arc_id === workflowArc.id || plan.season_id === workflowArc.season_id).slice(0, 3);

  return {
    storyArcs, setStoryArcs,
    videoScripts, setVideoScripts,
    publishingPlans, setPublishingPlans,
    arcSeasonId, setArcSeasonId,
    arcTitle, setArcTitle,
    arcPrompt, setArcPrompt,
    arcFormat, setArcFormat,
    arcType, setArcType,
    arcCharacterId, setArcCharacterId,
    arcMaxSegments, setArcMaxSegments,
    arcMaxDuration, setArcMaxDuration,
    arcRenderBusy,
    workflowArcId, setWorkflowArcId,
    arcTransition, setArcTransition,
    arcIncludeNarration, setArcIncludeNarration,
    arcNarrationMode, setArcNarrationMode,
    seasonSearch, setSeasonSearch,
    searchResults,
    scriptPrompt, setScriptPrompt,
    availableArcCharacters,
    selectedArcSeasonId,
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
    openArcSegment,
    patchArcLocal,
    patchArcSegmentLocal,
    arcSeason,
    arcCharacters,
    visibleStoryArcs,
    workflowArc,
    workflowScripts,
    workflowPublishing,
  };
}
