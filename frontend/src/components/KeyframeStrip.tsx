import { useEffect, useState } from "react";
import { Film } from "lucide-react";

import { api } from "../api";
import type { KeyframeStripData } from "../types";

type KeyframeStripProps = {
  candidateId: number;
  editRevision: number;
  onSeek: (time: number) => void;
};

// Thumbnail filmstrip across the candidate range so the crop editor is not a
// blind slider. Re-fetches whenever the candidate's edit revision changes.
export function KeyframeStrip({ candidateId, editRevision, onSeek }: KeyframeStripProps) {
  const [strip, setStrip] = useState<KeyframeStripData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    api<KeyframeStripData>(`/api/candidates/${candidateId}/keyframes?count=8`)
      .then((data) => {
        if (active) setStrip(data);
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "Раскадровка недоступна");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [candidateId, editRevision]);

  return (
    <div className="keyframe-strip">
      <div className="keyframe-strip-title">
        <Film size={15} /> Раскадровка
        {loading && <span className="muted"> · строится…</span>}
      </div>
      {error && <small className="warn-text">{error}</small>}
      <div className="keyframe-thumbs">
        {(strip?.frames ?? []).map((frame) => (
          <button
            key={frame.index}
            type="button"
            title={`${frame.time.toFixed(1)} сек`}
            onClick={() => onSeek(frame.time)}
          >
            <img src={frame.url} alt={`Кадр на ${frame.time.toFixed(1)} сек`} loading="lazy" />
            <span>{frame.time.toFixed(1)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
