import { Check, Clapperboard, X } from "lucide-react";

import type { Candidate } from "../types";

type BatchActionBarProps = {
  episodeId: number;
  visibleCandidates: Candidate[];
  selection: number[];
  busy: boolean;
  onSelectAll: (ids: number[]) => void;
  onClear: () => void;
  onReview: (episodeId: number, decision: "approve" | "reject") => void;
  onRender: () => void;
};

export function BatchActionBar({
  episodeId,
  visibleCandidates,
  selection,
  busy,
  onSelectAll,
  onClear,
  onReview,
  onRender,
}: BatchActionBarProps) {
  const visibleIds = visibleCandidates.map((candidate) => candidate.id);
  const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selection.includes(id));

  return (
    <div className="batch-bar">
      <label className="inline-check">
        <input
          type="checkbox"
          checked={allSelected}
          onChange={(event) => (event.target.checked ? onSelectAll(visibleIds) : onClear())}
        />
        {selection.length ? `Выбрано: ${selection.length}` : "Выбрать видимые"}
      </label>
      <div className="batch-bar-actions">
        <button disabled={busy || !selection.length} onClick={() => onReview(episodeId, "approve")}>
          <Check size={15} /> Принять
        </button>
        <button className="secondary" disabled={busy || !selection.length} onClick={() => onReview(episodeId, "reject")}>
          <X size={15} /> Отклонить
        </button>
        <button disabled={busy || !selection.length} onClick={onRender}>
          <Clapperboard size={15} /> В рендер
        </button>
        {selection.length > 0 && (
          <button className="text-button" onClick={onClear}>
            снять
          </button>
        )}
      </div>
    </div>
  );
}
