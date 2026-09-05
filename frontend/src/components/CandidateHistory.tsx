import { useCallback, useEffect, useState } from "react";
import { History, Undo2 } from "lucide-react";

import { api } from "../api";
import type { CandidateSnapshot } from "../types";
import { parseServerDate } from "../utils";

type CandidateHistoryProps = {
  candidateId: number;
  editRevision: number;
  onRestored: () => void;
};

const KIND_LABEL: Record<string, string> = {
  boundaries: "границы",
  crop: "кадр",
  subtitles: "субтитры",
  restore: "откат",
};

export function CandidateHistory({ candidateId, editRevision, onRestored }: CandidateHistoryProps) {
  const [snapshots, setSnapshots] = useState<CandidateSnapshot[]>([]);
  const [selected, setSelected] = useState<number | "">("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    try {
      setSnapshots(await api<CandidateSnapshot[]>(`/api/candidates/${candidateId}/history`));
    } catch {
      setSnapshots([]);
    }
  }, [candidateId]);

  useEffect(() => {
    load();
  }, [load, editRevision]);

  async function restore() {
    if (selected === "") return;
    setBusy(true);
    setMessage("");
    try {
      await api(`/api/candidates/${candidateId}/history/${selected}/restore`, { method: "POST" });
      setSelected("");
      setMessage("Правка откачена");
      await load();
      onRestored();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Не удалось откатить");
    } finally {
      setBusy(false);
    }
  }

  if (!snapshots.length) return null;
  return (
    <div className="candidate-history">
      <label>
        <History size={15} /> История правок
        <select value={selected} onChange={(event) => setSelected(event.target.value ? Number(event.target.value) : "")}>
          <option value="">выберите точку отката</option>
          {snapshots.map((snapshot) => (
            <option key={snapshot.id} value={snapshot.id}>
              {parseServerDate(snapshot.created_at).toLocaleTimeString()} · {KIND_LABEL[snapshot.kind] ?? snapshot.kind} ·{" "}
              {snapshot.start_time.toFixed(1)}–{snapshot.end_time.toFixed(1)} · {snapshot.subtitle_rows} стр.
            </option>
          ))}
        </select>
      </label>
      <button className="secondary" disabled={busy || selected === ""} onClick={restore}>
        <Undo2 size={15} /> Откатить
      </button>
      {message && <small>{message}</small>}
    </div>
  );
}
