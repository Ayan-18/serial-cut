import type { Candidate, CandidateEdit, StoryArc } from "./types";

export const SILERO_VOICES = [
  { id: "eugene", label: "Евгений (муж.)" },
  { id: "aidar", label: "Айдар (муж.)" },
  { id: "baya", label: "Байя (жен.)" },
  { id: "kseniya", label: "Ксения (жен.)" },
  { id: "xenia", label: "Ксения мягкая (жен.)" },
] as const;
export function voiceLabel(id: string | null | undefined) { return SILERO_VOICES.find((v) => v.id === id)?.label ?? id ?? "—"; }

export function splitLines(value: string) { return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean); }
export function fileDataUrl(file: File) { return new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => typeof reader.result === "string" ? resolve(reader.result) : reject(new Error("Пустой файл")); reader.onerror = () => reject(reader.error ?? new Error("Ошибка чтения")); reader.readAsDataURL(file); }); }
export function identityMethodLabel(method: string) { const labels: Record<string, string> = { manual: "подтверждено вручную", face: "лицо", "face+lip": "лицо + губы", voice: "голос", "face+lip+voice": "лицо + губы + голос" }; return labels[method] ?? method; }
export function editFromCandidate(candidate: Candidate): CandidateEdit { return { start: candidate.start_time.toFixed(3), end: candidate.end_time.toFixed(3), crop: candidate.crop_mode, offset: candidate.crop_offset_x, scale: candidate.crop_scale }; }
export function previewCropOffset(candidate: Candidate, edit: CandidateEdit, absoluteTime: number) { const points = candidate.crop_keyframes_json ?? []; if (edit.crop !== "auto-follow" || !points.length) return edit.offset; const time = Math.max(0, absoluteTime - candidate.start_time); const rightIndex = points.findIndex((item) => item.time >= time); if (rightIndex <= 0) return points[0].offset; if (rightIndex < 0) return points.at(-1)?.offset ?? edit.offset; const left = points[rightIndex - 1]; const right = points[rightIndex]; const ratio = (time - left.time) / Math.max(0.001, right.time - left.time); return left.offset + (right.offset - left.offset) * ratio; }
export function formatBytes(value: number) { if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(2)} GB`; if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)} MB`; if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`; return `${value} B`; }
export function formatEta(value: number | null | undefined) { if (value == null) return "—"; if (value < 60) return `${Math.round(value)} сек`; return `${Math.round(value / 60)} мин`; }
export function formatElapsed(value: number) { const hours = Math.floor(value / 3600); const minutes = Math.floor((value % 3600) / 60); const seconds = value % 60; const base = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`; return hours > 0 ? `${String(hours).padStart(2, "0")}:${base}` : base; }
export function elapsedFrom(value: string) { return formatElapsed(Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000))); }
export function formatRange(start: number, end: number) { return `${formatClock(start)}–${formatClock(end)} · ${(end - start).toFixed(1)} сек`; }
export function formatClock(value: number) { const minutes = Math.floor(value / 60); const seconds = Math.floor(value % 60); return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`; }
export function stageLabel(stage: string | null) { const labels: Record<string, string> = { discovered: "найдена", probed: "метаданные готовы", proxied: "proxy готов", transcribed: "речь распознана", scenes_detected: "сцены найдены", outlined: "сюжет разобран", candidates_generated: "кандидаты готовы", awaiting_review: "ждёт проверки", rendered: "ролик готов", stage2_media: "медиа и речь", stage3_candidates: "поиск кандидатов", auto_export: "автоэкспорт", render_clip: "рендер клипа", render_story_arc: "рендер StoryArc", completed: "завершено" }; return stage ? labels[stage] ?? stage : "ожидание"; }
export function formatArcFormat(format: string) { const labels: Record<string, string> = { single_short: "Один Shorts", shorts_series: "Серия Shorts", story_video: "Видео 2–10 мин", long_video: "Длинное видео" }; return labels[format] ?? format; }
export function arcNarration(arc: StoryArc) { const narration = arc.plan_json.narration; if (!Array.isArray(narration)) return []; return narration.map((item) => typeof item === "object" && item !== null ? item as { order?: unknown; text?: unknown } : null).filter((item): item is { order?: unknown; text?: unknown } => !!item && typeof item.text === "string").map((item, index) => ({ order: Number(item.order) || index + 1, text: String(item.text) })); }
export function arcNarrationSource(arc: StoryArc) { const s = arc.plan_json.narration_source; return typeof s === "string" ? s : null; }
export function statusLabel(status: string) { const labels: Record<string, string> = { queued: "в очереди", running: "выполняется", paused: "пауза", cancel_requested: "останавливается", failed: "ошибка", completed: "готово", stale: "нужно обновить", new: "новый", approved: "принят", rejected: "отклонён", rendered: "готов" }; return labels[status] ?? status; }
export function jobLabel(kind: string) { return kind === "render_clip" ? "рендер" : kind === "render_story_arc" ? "StoryArc" : kind === "analyze_episode" ? "анализ серии" : kind; }
export function errorMessage(error: unknown) { return error instanceof Error ? error.message : "Неизвестная ошибка"; }
