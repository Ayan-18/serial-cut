import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Check,
  Clapperboard,
  FolderPlus,
  ListVideo,
  Pause,
  Play,
  RefreshCcw,
  Save,
  Server,
  Settings,
  X
} from "lucide-react";
import "./styles.css";

type Episode = {
  id: number;
  file_name: string;
  file_path: string;
  stage: string;
  size_bytes: number;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
};

type Season = { id: number; title: string; root_path: string; episodes: Episode[] };
type CheckItem = { name: string; ok: boolean; message: string };
type QueueData = {
  snapshot: { queued: number; running: number; failed: number; paused: boolean; eta_seconds: number | null };
  items: Array<{ id: number; episode_id: number | null; status: string; current_stage: string | null; progress: number; error_message: string | null }>;
};
type RuntimeSettings = {
  cache_dir: string;
  output_dir: string;
  quality_profile: "fast" | "balanced" | "quality";
  min_clip_seconds: number;
  max_clip_seconds: number;
  auto_mode_enabled: boolean;
  auto_score_threshold: number;
  max_clips_per_episode: number;
  render_preset: "youtube_shorts" | "instagram_reels";
  render_use_nvenc: boolean;
  render_loudnorm_two_pass: boolean;
  subtitle_font_name: string;
  asr_adapter: "stub" | "faster-whisper";
  llm_adapter: "stub" | "llama-cpp-http";
  llm_base_url: string;
};
type Candidate = {
  id: number;
  episode_id: number;
  start_time: number;
  end_time: number;
  title: string;
  description: string;
  moment_type: string;
  score: number;
  scores_json: Record<string, number>;
  rationale: string;
  problems_json: string[];
  crop_mode: "auto-follow" | "center-crop" | "blurred-background";
  status: string;
};

function App() {
  const [rootPath, setRootPath] = useState("");
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [checks, setChecks] = useState<CheckItem[]>([]);
  const [queue, setQueue] = useState<QueueData | null>(null);
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [candidates, setCandidates] = useState<Record<number, Candidate[]>>({});
  const [selectedEpisodeId, setSelectedEpisodeId] = useState<number | null>(null);
  const [edits, setEdits] = useState<Record<number, { start: string; end: string; crop: string }>>({});
  const [message, setMessage] = useState("");

  async function api<T>(url: string, init?: RequestInit): Promise<T> {
    const response = await fetch(url, init);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail ?? "Ошибка запроса");
    return data;
  }

  async function refresh() {
    const [seasonData, queueData, settingsData] = await Promise.all([
      api<Season[]>("/api/seasons"),
      api<QueueData>("/api/jobs"),
      api<RuntimeSettings>("/api/settings")
    ]);
    setSeasons(seasonData);
    setQueue(queueData);
    setSettings(settingsData);
  }

  async function runSystemCheck() {
    const data = await api<{ items: CheckItem[] }>("/api/system-check");
    setChecks(data.items);
  }

  async function importSeason() {
    const data = await api<{ created: number; skipped_duplicates: number }>("/api/seasons/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ root_path: rootPath })
    });
    setMessage(`Добавлено: ${data.created}, дубликатов: ${data.skipped_duplicates}`);
    await refresh();
  }

  async function enqueueSeason(seasonId: number, auto: boolean) {
    const jobs = await api<Array<{ id: number }>>(`/api/seasons/${seasonId}/enqueue`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto })
    });
    setMessage(`В очередь добавлено задач: ${jobs.length}`);
    await refresh();
  }

  async function runQueueNext() {
    const result = await api<{ message: string }>("/api/queue/run-next", { method: "POST" });
    setMessage(result.message);
    await refresh();
    if (selectedEpisodeId) await loadCandidates(selectedEpisodeId);
  }

  async function setPaused(paused: boolean) {
    const result = await api<{ state: string }>(paused ? "/api/queue/pause" : "/api/queue/resume", { method: "POST" });
    setMessage(`Очередь: ${result.state}`);
    await refresh();
  }

  async function runStage2(episodeId: number) {
    const data = await api<{ transcript_segments: number; scenes: number }>(`/api/episodes/${episodeId}/stage2`, { method: "POST" });
    setMessage(`Медиа-анализ готов: сегментов ${data.transcript_segments}, сцен ${data.scenes}`);
    await refresh();
  }

  async function runStage3(episodeId: number) {
    const data = await api<{ candidates: number }>(`/api/episodes/${episodeId}/stage3`, { method: "POST" });
    setMessage(`Кандидаты готовы: ${data.candidates}`);
    await loadCandidates(episodeId);
    await refresh();
  }

  async function autoExport(episodeId: number) {
    const data = await api<{ rendered: number }>(`/api/episodes/${episodeId}/auto-export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });
    setMessage(`Автоэкспорт: готово ${data.rendered}`);
    await loadCandidates(episodeId);
    await refresh();
  }

  async function loadCandidates(episodeId: number) {
    const data = await api<Candidate[]>(`/api/episodes/${episodeId}/candidates`);
    setCandidates((current) => ({ ...current, [episodeId]: data }));
    setSelectedEpisodeId(episodeId);
    setEdits((current) => {
      const next = { ...current };
      for (const candidate of data) {
        next[candidate.id] ??= {
          start: candidate.start_time.toFixed(3),
          end: candidate.end_time.toFixed(3),
          crop: candidate.crop_mode
        };
      }
      return next;
    });
  }

  async function reviewCandidate(candidate: Candidate, decision: "approve" | "reject") {
    const edit = edits[candidate.id];
    await api(`/api/candidates/${candidate.id}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision,
        adjusted_start_time: edit ? Number(edit.start) : candidate.start_time,
        adjusted_end_time: edit ? Number(edit.end) : candidate.end_time,
        crop_mode: edit?.crop ?? candidate.crop_mode
      })
    });
    setMessage(decision === "approve" ? "Кандидат принят" : "Кандидат отклонён");
    await loadCandidates(candidate.episode_id);
  }

  async function renderCandidate(candidate: Candidate, includeSubtitles: boolean) {
    const data = await api<{ output_path: string }>(`/api/candidates/${candidate.id}/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        include_subtitles: includeSubtitles,
        use_nvenc: settings?.render_use_nvenc ?? null,
        preset_name: settings?.render_preset,
        loudnorm_two_pass: settings?.render_loudnorm_two_pass ?? null
      })
    });
    setMessage(`Экспорт готов: ${data.output_path}`);
    await loadCandidates(candidate.episode_id);
    await refresh();
  }

  async function saveSettings() {
    if (!settings) return;
    await api<RuntimeSettings>("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings)
    });
    setMessage("Настройки сохранены");
  }

  function setCandidateEdit(candidateId: number, patch: Partial<{ start: string; end: string; crop: string }>) {
    setEdits((current) => ({ ...current, [candidateId]: { ...current[candidateId], ...patch } }));
  }

  function patchSettings(patch: Partial<RuntimeSettings>) {
    setSettings((current) => (current ? { ...current, ...patch } : current));
  }

  useEffect(() => {
    refresh().catch((error) => setMessage(error.message));
    runSystemCheck().catch((error) => setMessage(error.message));
  }, []);

  return (
    <main className="app-shell">
      <section className="topbar">
        <div>
          <h1>SerialCuts</h1>
          <p>Локальная подготовка вертикальных клипов из серий</p>
        </div>
        <button className="icon-button" title="Обновить" onClick={() => refresh()}>
          <RefreshCcw size={20} />
        </button>
      </section>

      {message && <p className="notice">{message}</p>}

      <section className="grid">
        <div className="panel">
          <div className="panel-title">
            <FolderPlus size={19} />
            <h2>Сезоны</h2>
          </div>
          <div className="path-row">
            <input value={rootPath} onChange={(event) => setRootPath(event.target.value)} placeholder="D:\\Сериалы\\Название\\Сезон 1" />
            <button onClick={importSeason}>Добавить</button>
          </div>
          <div className="season-list">
            {seasons.map((season) => (
              <article className="season" key={season.id}>
                <strong>{season.title}</strong>
                <span>{season.episodes.length} серий</span>
                <button onClick={() => enqueueSeason(season.id, false)}>В очередь</button>
                <button onClick={() => enqueueSeason(season.id, true)}>Auto</button>
              </article>
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="panel-title">
            <Server size={19} />
            <h2>Очередь</h2>
          </div>
          <div className="queue-actions">
            <button className="icon-button" title="Выполнить следующую" onClick={runQueueNext}><Play size={18} /></button>
            <button className="icon-button secondary" title="Пауза" onClick={() => setPaused(true)}><Pause size={18} /></button>
            <button className="icon-button" title="Продолжить" onClick={() => setPaused(false)}><Play size={18} /></button>
          </div>
          <div className="checks">
            <div className="check"><strong>queued</strong><span>{queue?.snapshot.queued ?? 0}</span></div>
            <div className="check"><strong>running</strong><span>{queue?.snapshot.running ?? 0}</span></div>
            <div className="check"><strong>failed</strong><span>{queue?.snapshot.failed ?? 0}</span></div>
            <div className="check"><strong>ETA</strong><span>{formatEta(queue?.snapshot.eta_seconds)}</span></div>
          </div>
        </div>
      </section>

      <section className="grid">
        <div className="panel">
          <div className="panel-title">
            <Settings size={19} />
            <h2>Настройки</h2>
          </div>
          {settings && (
            <div className="settings-grid">
              <input value={settings.cache_dir} onChange={(event) => patchSettings({ cache_dir: event.target.value })} />
              <input value={settings.output_dir} onChange={(event) => patchSettings({ output_dir: event.target.value })} />
              <select value={settings.quality_profile} onChange={(event) => patchSettings({ quality_profile: event.target.value as RuntimeSettings["quality_profile"] })}>
                <option value="fast">fast</option>
                <option value="balanced">balanced</option>
                <option value="quality">quality</option>
              </select>
              <input type="number" value={settings.min_clip_seconds} onChange={(event) => patchSettings({ min_clip_seconds: Number(event.target.value) })} />
              <input type="number" value={settings.max_clip_seconds} onChange={(event) => patchSettings({ max_clip_seconds: Number(event.target.value) })} />
              <input type="number" value={settings.auto_score_threshold} onChange={(event) => patchSettings({ auto_score_threshold: Number(event.target.value) })} />
              <input type="number" value={settings.max_clips_per_episode} onChange={(event) => patchSettings({ max_clips_per_episode: Number(event.target.value) })} />
              <select value={settings.render_preset} onChange={(event) => patchSettings({ render_preset: event.target.value as RuntimeSettings["render_preset"] })}>
                <option value="youtube_shorts">YouTube Shorts</option>
                <option value="instagram_reels">Instagram Reels</option>
              </select>
              <label><input type="checkbox" checked={settings.auto_mode_enabled} onChange={(event) => patchSettings({ auto_mode_enabled: event.target.checked })} /> auto</label>
              <label><input type="checkbox" checked={settings.render_use_nvenc} onChange={(event) => patchSettings({ render_use_nvenc: event.target.checked })} /> NVENC</label>
              <label><input type="checkbox" checked={settings.render_loudnorm_two_pass} onChange={(event) => patchSettings({ render_loudnorm_two_pass: event.target.checked })} /> loudnorm 2-pass</label>
              <input value={settings.subtitle_font_name} onChange={(event) => patchSettings({ subtitle_font_name: event.target.value })} />
              <button onClick={saveSettings}><Save size={17} /> Сохранить</button>
            </div>
          )}
        </div>

        <div className="panel">
          <div className="panel-title">
            <Server size={19} />
            <h2>Проверка системы</h2>
          </div>
          <div className="checks">
            {checks.map((item) => (
              <div className="check" key={item.name}>
                <span className={item.ok ? "dot ok" : "dot fail"} />
                <strong>{item.name}</strong>
                <span>{item.message}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-title">
          <ListVideo size={19} />
          <h2>Найденные серии</h2>
        </div>
        <div className="episodes">
          {seasons.flatMap((season) =>
            season.episodes.map((episode) => (
              <article className="episode" key={episode.id}>
                <strong>{episode.file_name}</strong>
                <span>{episode.stage}</span>
                <span>{formatBytes(episode.size_bytes)}</span>
                <span>{episode.width && episode.height ? `${episode.width}x${episode.height}` : "metadata pending"}</span>
                <button onClick={() => runStage2(episode.id)}>Медиа</button>
                <button onClick={() => runStage3(episode.id)}>Кандидаты</button>
                <button onClick={() => autoExport(episode.id)}>Auto export</button>
                <button onClick={() => loadCandidates(episode.id)}>Открыть</button>
              </article>
            ))
          )}
        </div>
      </section>

      {selectedEpisodeId && (
        <section className="panel">
          <div className="panel-title">
            <Clapperboard size={19} />
            <h2>Кандидаты</h2>
          </div>
          <video className="proxy-player" controls src={`/api/episodes/${selectedEpisodeId}/proxy`} />
          <div className="candidate-list">
            {(candidates[selectedEpisodeId] ?? []).map((candidate) => {
              const edit = edits[candidate.id] ?? {
                start: candidate.start_time.toFixed(3),
                end: candidate.end_time.toFixed(3),
                crop: candidate.crop_mode
              };
              return (
                <article className="candidate" key={candidate.id}>
                  <div>
                    <strong>{candidate.title}</strong>
                    <span>{candidate.moment_type} · {candidate.score}/100 · {candidate.status}</span>
                  </div>
                  <p>{candidate.description}</p>
                  <p>{candidate.rationale}</p>
                  <div className="edit-row">
                    <input value={edit.start} onChange={(event) => setCandidateEdit(candidate.id, { start: event.target.value })} />
                    <input value={edit.end} onChange={(event) => setCandidateEdit(candidate.id, { end: event.target.value })} />
                    <select value={edit.crop} onChange={(event) => setCandidateEdit(candidate.id, { crop: event.target.value })}>
                      <option value="blurred-background">blurred-background</option>
                      <option value="center-crop">center-crop</option>
                      <option value="auto-follow">auto-follow</option>
                    </select>
                    <button className="icon-button" title="Принять" onClick={() => reviewCandidate(candidate, "approve")}><Check size={18} /></button>
                    <button className="icon-button secondary" title="Отклонить" onClick={() => reviewCandidate(candidate, "reject")}><X size={18} /></button>
                    <button onClick={() => renderCandidate(candidate, true)}>С сабами</button>
                    <button onClick={() => renderCandidate(candidate, false)}>Без сабов</button>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      )}
    </main>
  );
}

function formatBytes(value: number) {
  if (value > 1024 * 1024 * 1024) return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
  if (value > 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${value} B`;
}

function formatEta(value: number | null | undefined) {
  if (value == null) return "нет данных";
  if (value < 60) return `${Math.round(value)} сек`;
  return `${Math.round(value / 60)} мин`;
}

createRoot(document.getElementById("root")!).render(<App />);
