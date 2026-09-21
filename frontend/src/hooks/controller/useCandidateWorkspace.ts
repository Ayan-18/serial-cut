import { useEffect, useRef, useState } from "react";

import { api, jsonHeaders } from "../../api";
import type {
  BatchOutcome,
  Candidate,
  CandidateQuality,
  EpisodeQuality,
  Job,
  PreviewRender,
  RuntimeSettings,
  Subtitle,
  SubtitleQuality,
} from "../../types";
import { editFromCandidate, errorMessage } from "../../utils";
import { useCandidates } from "../useCandidates";

export type UseCandidateWorkspaceParams = {
  setMessage: (message: string) => void;
  settings: RuntimeSettings | null;
};

/**
 * Which episode is open, its candidates (via `useCandidates`), the selected
 * candidate's subtitles/quality/preview, the vertical-preview video refs, and
 * batch selection/actions. Everything a user does on the "Серии" / candidate
 * editor screens lives here.
 */
export function useCandidateWorkspace({ setMessage, settings }: UseCandidateWorkspaceParams) {
  const [selectedEpisodeId, setSelectedEpisodeId] = useState<number | null>(null);
  const {
    candidates, setCandidates,
    selectedCandidate, setSelectedCandidate,
    edits, setEdits,
    candidateFilter, setCandidateFilter,
    candidateSort, setCandidateSort,
    candidateSearch, setCandidateSearch,
    candidateMomentType, setCandidateMomentType,
    candidateMinScore, setCandidateMinScore,
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
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [videoTime, setVideoTime] = useState(0);
  const [batchSelection, setBatchSelectionState] = useState<number[]>([]);
  const videoRef = useRef<HTMLVideoElement>(null);
  const backgroundVideoRef = useRef<HTMLVideoElement>(null);

  function toggleBatchCandidate(candidateId: number) {
    setBatchSelectionState((current) => current.includes(candidateId) ? current.filter((id) => id !== candidateId) : [...current, candidateId]);
  }
  function setBatchCandidates(ids: number[]) { setBatchSelectionState(ids); }
  function clearBatchSelection() { setBatchSelectionState([]); }

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

  /** Domain-only: the caller (orchestrator) refreshes the queue afterwards. Returns false when there was nothing selected. */
  async function batchRenderCandidates(): Promise<boolean> {
    if (!batchSelection.length) return false;
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
    return true;
  }

  async function loadCandidates(episodeId: number, selectEpisode = true) {
    const data = await api<Candidate[]>(`/api/episodes/${episodeId}/candidates`);
    setCandidates((current) => ({ ...current, [episodeId]: data }));
    setEpisodeQuality(await api<EpisodeQuality>(`/api/episodes/${episodeId}/quality`).catch(() => null));
    if (selectEpisode) setSelectedEpisodeId(episodeId);
    setEdits((current) => { const next = { ...current }; for (const candidate of data) next[candidate.id] ??= editFromCandidate(candidate); return next; });
    if (selectedCandidate?.episode_id === episodeId) { const updated = data.find((item) => item.id === selectedCandidate.id); if (updated) setSelectedCandidate(updated); }
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
    const previousCrop = (edits[candidate.id] ?? editFromCandidate(candidate)).crop;
    setCandidateEdit(candidate.id, { crop: "auto-follow" });  // optimistic: dropdown follows the click
    setMessage("Ищем активного говорящего по персонажу и движению губ…");
    try {
      const data = await api<{ crop_offset_x: number; faces_detected: number; keyframes: { time: number; offset: number }[]; active_speaker_frames: number; identified_speaker_frames: number; lip_motion_frames: number; face_model: string; held_frames: number; largest_face_frames: number; average_confidence: number }>(`/api/candidates/${candidate.id}/auto-crop`, { method: "POST" });
      setCandidateEdit(candidate.id, { crop: "auto-follow", offset: data.crop_offset_x });
      await loadCandidates(candidate.episode_id, false);
      setMessage(data.keyframes.length
        ? `Траектория: ${data.keyframes.length} точек · ${data.face_model} · персонаж: ${data.identified_speaker_frames} · губы: ${data.lip_motion_frames} · удержано: ${data.held_frames}`
        : "В этом отрывке лица не найдены — оставлен центр кадра");
    } catch (error) {
      setCandidateEdit(candidate.id, { crop: previousCrop });  // revert on failure (e.g. 422 no models)
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

  /** Domain-only: the caller (orchestrator) refreshes the queue afterwards. */
  async function renderCandidate(candidate: Candidate, includeSubtitles: boolean) {
    const edit = edits[candidate.id] ?? editFromCandidate(candidate);
    await api(`/api/candidates/${candidate.id}/review`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({ decision: "approve", adjusted_start_time: Number(edit.start), adjusted_end_time: Number(edit.end), crop_mode: edit.crop, crop_offset_x: edit.offset, crop_scale: edit.scale }) });
    const job = await api<Job>(`/api/candidates/${candidate.id}/render-job`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({ include_subtitles: includeSubtitles, use_nvenc: settings?.render_use_nvenc ?? null, preset_name: settings?.render_preset, loudnorm_two_pass: settings?.render_loudnorm_two_pass ?? null, force_rerender: true }) });
    setMessage(`Рендер поставлен в очередь, задача №${job.id}. Можно продолжать работу.`);
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

  function updateSubtitle(index: number, patch: Partial<Subtitle>) {
    setSubtitles((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item));
  }

  function onVideoTimeUpdate() {
    const player = videoRef.current; const background = backgroundVideoRef.current; if (!player) return;
    setVideoTime(player.currentTime);
    if (background && Math.abs(background.currentTime - player.currentTime) > 0.2) background.currentTime = player.currentTime;
    if (selectedCandidate) { const end = Number((edits[selectedCandidate.id] ?? editFromCandidate(selectedCandidate)).end); if (player.currentTime >= end) player.pause(); }
  }

  useEffect(() => { clearBatchSelection(); }, [selectedEpisodeId]);

  const activeSubtitle = selectedCandidate
    ? subtitles.find((item) => { const relative = videoTime - Number((edits[selectedCandidate.id] ?? editFromCandidate(selectedCandidate)).start); return relative >= item.start_time && relative <= item.end_time; })
    : undefined;

  return {
    selectedEpisodeId, setSelectedEpisodeId,
    candidates, setCandidates,
    selectedCandidate, setSelectedCandidate,
    edits, setEdits,
    candidateFilter, setCandidateFilter,
    candidateSort, setCandidateSort,
    candidateSearch, setCandidateSearch,
    candidateMomentType, setCandidateMomentType,
    candidateMinScore, setCandidateMinScore,
    visibleCandidates,
    momentTypes,
    selectedEdit,
    setCandidateEdit,
    subtitles, setSubtitles,
    subtitleBusy,
    candidateQuality,
    episodeQuality,
    subtitleQuality,
    previewUrl,
    previewBusy,
    videoTime,
    videoRef,
    backgroundVideoRef,
    loadCandidates,
    openCandidate,
    reviewCandidate,
    autoCrop,
    chooseCrop,
    saveSubtitles,
    resetSubtitles,
    autoSplitSubtitles,
    renderCandidate,
    renderPreview,
    updateSubtitle,
    onVideoTimeUpdate,
    activeSubtitle,
    batchSelection,
    toggleBatchCandidate,
    setBatchCandidates,
    clearBatchSelection,
    batchReviewCandidates,
    batchRenderCandidates,
  };
}
