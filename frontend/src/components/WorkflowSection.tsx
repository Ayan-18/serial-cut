import { Activity, CalendarDays, Clapperboard, FileText, RefreshCcw, Save, Search, Trash2, Volume2 } from "lucide-react";

import type { SerialCutsController } from "../hooks/useSerialCutsController";
import type { StoryArc } from "../types";
import { formatElapsed, formatRange, statusLabel } from "../utils";
import { SettingCheck } from "./SettingsFields";

type WorkflowSectionProps = {
  controller: SerialCutsController;
};

/** "Workflow сезона": season search, the StoryArc/segment editor, script and publishing drafts, project diagnostics. */
export function WorkflowSection({ controller }: WorkflowSectionProps) {
  const {
    refreshProjectDiagnostics, seasonSearch, setSeasonSearch, arcSeason, runSeasonSearch, searchResults,
    workflowArc, addSearchResultToArc, setWorkflowArcId, visibleStoryArcs, patchArcLocal, saveArcMeta,
    arcTransition, setArcTransition, arcIncludeNarration, setArcIncludeNarration, arcNarrationMode, setArcNarrationMode,
    arcRenderBusy, enqueueStoryArcRender, renderStoryArc, synthesizeNarration, moveArcSegment, patchArcSegmentLocal,
    saveArcSegment, removeArcSegment, scriptPrompt, setScriptPrompt, createVideoScriptForArc, workflowScripts,
    createPublishingPlanForArc, workflowPublishing, createPublishingPackageForPlan, projectDiagnostics,
  } = controller;

  return <section className="panel section-gap workflow-panel"><div className="panel-title"><Activity size={19} /><h2>Workflow сезона</h2><button className="icon-button secondary" title="Диагностика проекта" onClick={refreshProjectDiagnostics}><RefreshCcw size={17} /></button></div>
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
            <button className="secondary" onClick={() => synthesizeNarration(workflowArc)}><Volume2 size={16} /> WAV</button>{typeof workflowArc.plan_json.narration_audio_path === "string" && <audio className="narration-audio" controls preload="none" src={`/api/story-arcs/${workflowArc.id}/narration-audio-file`} />}
          </div>
        </> : <p className="empty">Создайте StoryArc, чтобы редактировать сезонный монтаж.</p>}
      </div>
      <div className="workflow-block workflow-wide"><h3>Сегменты</h3>{workflowArc ? <div className="segment-editor">{workflowArc.segments.map((segment) => <article key={segment.id}><div className="segment-row"><button className="icon-button secondary" title="Выше" onClick={() => moveArcSegment(workflowArc.id, segment, -1)}>↑</button><button className="icon-button secondary" title="Ниже" onClick={() => moveArcSegment(workflowArc.id, segment, 1)}>↓</button><input type="number" min="0" step="0.1" value={segment.start_time} onChange={(event) => patchArcSegmentLocal(workflowArc.id, segment.id, { start_time: Number(event.target.value) })} /><input type="number" min="0" step="0.1" value={segment.end_time} onChange={(event) => patchArcSegmentLocal(workflowArc.id, segment.id, { end_time: Number(event.target.value) })} /><input value={segment.title} onChange={(event) => patchArcSegmentLocal(workflowArc.id, segment.id, { title: event.target.value })} /><input value={segment.role ?? ""} onChange={(event) => patchArcSegmentLocal(workflowArc.id, segment.id, { role: event.target.value || null })} /><button onClick={() => saveArcSegment(workflowArc.id, segment)}><Save size={16} /></button><button className="icon-button danger" title="Удалить" onClick={() => removeArcSegment(workflowArc.id, segment.id)}><Trash2 size={16} /></button></div><small>{segment.episode_file_name} · {segment.note}</small></article>)}</div> : <p className="empty">Сегменты появятся после создания плана.</p>}</div>
      <div className="workflow-block"><h3>Сценарий</h3>{workflowArc ? <><textarea rows={3} value={scriptPrompt} onChange={(event) => setScriptPrompt(event.target.value)} placeholder="Акцент для сценария: конфликт, развитие героя, быстрый пересказ…" /><button onClick={() => createVideoScriptForArc(workflowArc)}><FileText size={16} /> Создать сценарий</button></> : <small>Нужен StoryArc.</small>}<div className="script-list">{workflowScripts.map((script) => <details key={script.id}><summary>{script.title}</summary><pre>{script.script_text}</pre></details>)}</div></div>
      <div className="workflow-block"><h3>Публикация</h3>{workflowArc ? <button onClick={() => createPublishingPlanForArc(workflowArc)}><CalendarDays size={16} /> Создать план</button> : <small>Нужен StoryArc.</small>}<div className="publishing-list">{workflowPublishing.map((plan) => <article key={plan.id}><strong>{plan.title}</strong><small>{plan.platform} · {statusLabel(plan.status)}</small><p>{plan.description}</p><small>{plan.hashtags.join(" ")}</small><button className="text-button" disabled={!plan.story_arc_export_id} onClick={() => createPublishingPackageForPlan(plan)}>Собрать publishing.json</button></article>)}</div></div>
      <div className="workflow-block"><h3>Диагностика</h3><div className="checks compact">{projectDiagnostics?.checks.map((item) => <div className="check" key={item.name}><span className={item.ok ? "dot ok" : "dot fail"} /><strong>{item.name}</strong><span>{item.message}</span></div>)}</div>{projectDiagnostics?.recommendations.map((item) => <small className="warn-text" key={item}>{item}</small>)}</div>
    </div>
  </section>;
}
