import { Clapperboard, FolderOpen } from "lucide-react";
import { api } from "../api";
import type { ExportItem } from "../types";

type ExportsPanelProps = {
  exports: ExportItem[];
};

export function ExportsPanel({ exports }: ExportsPanelProps) {
  return (
    <section className="panel section-gap">
      <div className="panel-title">
        <FolderOpen size={19} />
        <h2>Готовые ролики</h2>
        <span className="badge">{exports.length}</span>
      </div>
      <div className="exports-grid">
        {exports.map((item) => (
          <article className="export-card" key={item.id}>
            {item.cover_path ? (
              <img src={`/api/exports/${item.id}/cover`} alt="Обложка клипа" />
            ) : (
              <div className="export-placeholder">
                <Clapperboard />
              </div>
            )}
            <div>
              <strong>Экспорт №{item.id}</strong>
              <small>{item.preset_name} · {item.include_subtitles ? "с субтитрами" : "без субтитров"}</small>
              <small title={item.output_path}>{item.output_path}</small>
            </div>
            <video controls preload="none" src={`/api/exports/${item.id}/file`} />
            <button onClick={() => api(`/api/exports/${item.id}/open-folder`, { method: "POST" })}>
              <FolderOpen size={16} /> Открыть папку
            </button>
          </article>
        ))}
        {!exports.length && <p className="empty">После рендера готовые MP4 появятся здесь.</p>}
      </div>
    </section>
  );
}
