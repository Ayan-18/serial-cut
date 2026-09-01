import { useMemo, useState } from "react";

import type { Candidate, CandidateEdit } from "../types";
import { editFromCandidate } from "../utils";

export type CandidateFilter = "all" | "new" | "approved" | "rejected" | "rendered" | "problem";
export type CandidateSort = "score" | "boundary" | "time";

export type CandidateViewOptions = {
  candidates: Record<number, Candidate[]>;
  selectedEpisodeId: number | null;
  filter: string;
  sort: string;
  search: string;
  momentType: string;
  minScore: number;
};

export function useCandidates(selectedEpisodeId: number | null) {
  const [candidates, setCandidates] = useState<Record<number, Candidate[]>>({});
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(null);
  const [edits, setEdits] = useState<Record<number, CandidateEdit>>({});
  const [candidateFilter, setCandidateFilter] = useState<CandidateFilter>("all");
  const [candidateSort, setCandidateSort] = useState<CandidateSort>("score");
  const [candidateSearch, setCandidateSearch] = useState("");
  const [candidateMomentType, setCandidateMomentType] = useState("all");
  const [candidateMinScore, setCandidateMinScore] = useState(0);

  const visibleCandidates = useMemo(
    () =>
      selectVisibleCandidates({
        candidates,
        selectedEpisodeId,
        filter: candidateFilter,
        sort: candidateSort,
        search: candidateSearch,
        momentType: candidateMomentType,
        minScore: candidateMinScore,
      }),
    [candidateFilter, candidateMinScore, candidateMomentType, candidateSearch, candidateSort, candidates, selectedEpisodeId],
  );
  const momentTypes = useMemo(() => candidateMomentTypes(candidates, selectedEpisodeId), [candidates, selectedEpisodeId]);
  const selectedEdit = selectedCandidate ? edits[selectedCandidate.id] ?? editFromCandidate(selectedCandidate) : null;

  function setCandidateEdit(candidateId: number, patch: Partial<CandidateEdit>) {
    setEdits((current) => ({ ...current, [candidateId]: { ...current[candidateId], ...patch } }));
  }

  return {
    candidates,
    setCandidates,
    selectedCandidate,
    setSelectedCandidate,
    edits,
    setEdits,
    candidateFilter,
    setCandidateFilter,
    candidateSort,
    setCandidateSort,
    candidateSearch,
    setCandidateSearch,
    candidateMomentType,
    setCandidateMomentType,
    candidateMinScore,
    setCandidateMinScore,
    visibleCandidates,
    momentTypes,
    selectedEdit,
    setCandidateEdit,
  };
}

export function selectVisibleCandidates(options: CandidateViewOptions): Candidate[] {
  const items = [...(options.selectedEpisodeId ? options.candidates[options.selectedEpisodeId] ?? [] : [])];
  const search = options.search.trim().toLocaleLowerCase("ru");
  const filtered = items.filter((item) => {
    if (options.filter === "problem" && !item.problems_json.length) return false;
    if (options.filter !== "all" && options.filter !== "problem" && item.status !== options.filter) return false;
    if (options.momentType !== "all" && item.moment_type !== options.momentType) return false;
    if (item.score < options.minScore) return false;
    if (!search) return true;
    return `${item.title} ${item.description} ${item.rationale} ${item.moment_type}`
      .toLocaleLowerCase("ru")
      .includes(search);
  });
  return filtered.sort(candidateSorter(options.sort));
}

export function candidateMomentTypes(candidates: Record<number, Candidate[]>, selectedEpisodeId: number | null) {
  const items = selectedEpisodeId ? candidates[selectedEpisodeId] ?? [] : [];
  return Array.from(new Set(items.map((item) => item.moment_type))).sort();
}

function candidateSorter(sort: string) {
  if (sort === "time") return (a: Candidate, b: Candidate) => a.start_time - b.start_time;
  if (sort === "boundary") {
    return (a: Candidate, b: Candidate) =>
      (b.scores_json.boundary_quality ?? 0) - (a.scores_json.boundary_quality ?? 0);
  }
  return (a: Candidate, b: Candidate) => b.score - a.score;
}
