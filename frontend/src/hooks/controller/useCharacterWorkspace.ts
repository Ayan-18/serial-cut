import { useState } from "react";

import { api, jsonHeaders } from "../../api";
import type {
  Candidate,
  Character,
  EpisodeOutline,
  SpeakerIdentity,
  StoryContext,
  Subtitle,
} from "../../types";
import { errorMessage, fileDataUrl } from "../../utils";
import type { CandidateSort } from "../useCandidates";

export type UseCharacterWorkspaceParams = {
  setMessage: (message: string) => void;
  selectedEpisodeId: number | null;
  selectedCandidate: Candidate | null;
  setSubtitles: (subtitles: Subtitle[]) => void;
  setCandidateSort: (sort: CandidateSort) => void;
};

/**
 * Story context / candidate mode for the open episode, the season's character
 * roster, speaker-label ↔ character assignment and face/voice identification.
 * `regenerateStoryCandidates` stays in the orchestrator: it also needs
 * `seasons` (dashboard) and the wrapped `runDirectStage` (which reloads the
 * dashboard afterwards), so it's inherently cross-domain glue.
 */
export function useCharacterWorkspace({
  setMessage, selectedEpisodeId, selectedCandidate, setSubtitles, setCandidateSort,
}: UseCharacterWorkspaceParams) {
  const [storyContext, setStoryContext] = useState<StoryContext | null>(null);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [speakerLabels, setSpeakerLabels] = useState<string[]>([]);
  const [speakerIdentities, setSpeakerIdentities] = useState<SpeakerIdentity[]>([]);
  const [episodeOutline, setEpisodeOutline] = useState<EpisodeOutline | null>(null);
  const [characterName, setCharacterName] = useState("");
  const [characterDescription, setCharacterDescription] = useState("");
  const [characterPhotos, setCharacterPhotos] = useState<string[]>([]);

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
    return context;
  }

  async function saveStoryContext() {
    if (!storyContext) return;
    const saved = await api<StoryContext>(`/api/episodes/${storyContext.episode_id}/story-context`, {
      method: "PUT", headers: jsonHeaders, body: JSON.stringify(storyContext),
    });
    setStoryContext(saved); setMessage("Контекст и режим кандидатов сохранены");
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

  async function mergeCharacter(sourceId: number, targetId: number) {
    if (!storyContext || !targetId || sourceId === targetId) return;
    if (!window.confirm("Объединить этого персонажа с выбранным? Привязки голосов перейдут к целевой карточке.")) return;
    await api<Character>(`/api/characters/${sourceId}/merge`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({ target_character_id: targetId }) });
    await loadEpisodeDetails(storyContext.episode_id); setMessage("Карточки персонажей объединены");
  }

  return {
    storyContext, setStoryContext,
    characters,
    speakerLabels,
    speakerIdentities,
    episodeOutline,
    characterName, setCharacterName,
    characterDescription, setCharacterDescription,
    characterPhotos,
    loadEpisodeDetails,
    saveStoryContext,
    createCharacter,
    deleteCharacter,
    readCharacterPhotos,
    addCharacterPhotos,
    deleteCharacterPhoto,
    setCharacterNarrationVoice,
    assignSpeaker,
    identifyCharacters,
    mergeCharacter,
  };
}
