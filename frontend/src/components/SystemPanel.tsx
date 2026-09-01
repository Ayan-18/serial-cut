import { RefreshCcw, Server, Trash2 } from "lucide-react";
import type { CacheInfo, CheckItem, ModelDiagnostics } from "../types";
import { formatBytes } from "../utils";

type SystemPanelProps = {
  checks: CheckItem[];
  diagnostics: ModelDiagnostics | null;
  cacheInfo: CacheInfo | null;
  onRefresh: () => void;
  onClearCache: () => void;
};

export function SystemPanel({ checks, diagnostics, cacheInfo, onRefresh, onClearCache }: SystemPanelProps) {
  return <div className="panel">
    <div className="panel-title"><Server size={19} /><h2>Готовность системы</h2><button className="icon-button secondary" onClick={onRefresh}><RefreshCcw size={17} /></button></div>
    <div className="checks">
      {checks.map((item) => <div className="check" key={item.name}><span className={item.ok ? "dot ok" : "dot fail"} /><strong>{item.name}</strong><span>{item.message}</span></div>)}
      {diagnostics && <>
        <div className="check"><span className={diagnostics.asr_ready ? "dot ok" : "dot fail"} /><strong>Whisper</strong><span>{diagnostics.asr_adapter} · {diagnostics.asr_model} · {diagnostics.asr_device}/{diagnostics.asr_compute_type}</span></div>
        <div className="check"><span className={diagnostics.llm_ready ? "dot ok" : "dot fail"} /><strong>Qwen</strong><span>{diagnostics.llm_adapter} · {diagnostics.llm_model_hint}{diagnostics.llm_latency_ms != null ? ` · ${diagnostics.llm_latency_ms} мс` : ""}</span></div>
        <div className="check"><span className={diagnostics.tts_ready ? "dot ok" : "dot fail"} /><strong>Озвучка</strong><span>{diagnostics.tts_adapter}{diagnostics.tts_adapter === "silero" ? ` · torch ${diagnostics.tts_torch_installed ? "есть" : "нет"} · модель ${diagnostics.tts_model_exists ? "есть" : "нет"} · ${diagnostics.tts_narrator_voice}` : ""}</span></div>
        <div className="check"><span className={diagnostics.face_ready ? "dot ok" : "dot fail"} /><strong>Лица</strong><span>{diagnostics.face_model}</span></div>
        <div className="diagnostic-details">{diagnostics.details.map((item) => <small key={item}>{item}</small>)}{diagnostics.recommendations.map((item) => <small className="warn-text" key={item}>{item}</small>)}{diagnostics.asr_local_model_path && <small>Whisper path: {diagnostics.asr_local_model_path} · {diagnostics.asr_local_model_exists ? "найден" : "не найден"}</small>}<small>YuNet: {diagnostics.face_detector_path} · {diagnostics.face_detector_exists ? "найден" : "не найден"}</small><small>SFace: {diagnostics.face_recognizer_path} · {diagnostics.face_recognizer_exists ? "найден" : "не найден"}</small></div>
      </>}
    </div>
    <div className="cache-card"><div><strong>Временные файлы</strong><small>{cacheInfo?.files ?? 0} файлов · {formatBytes(cacheInfo?.bytes ?? 0)}</small><small>{cacheInfo?.cache_dir}</small></div><button className="danger" onClick={onClearCache}><Trash2 size={16} /> Очистить кэш</button></div>
  </div>;
}
