import { describe, expect, it } from "vitest";

import type { Candidate } from "../types";
import { candidateMomentTypes, selectVisibleCandidates } from "./useCandidates";

const baseCandidate: Candidate = {
  id: 1,
  episode_id: 7,
  start_time: 10,
  end_time: 45,
  title: "Сильный конфликт",
  description: "Герой узнаёт правду",
  moment_type: "конфликт",
  score: 90,
  scores_json: { boundary_quality: 70, hook: 80, payoff: 85, standalone_context: 75 },
  rationale: "ясный поворот",
  problems_json: [],
  crop_mode: "center-crop",
  crop_offset_x: 0,
  crop_scale: 1,
  thumbnail_path: null,
  status: "new",
  story_order: null,
  story_role: null,
  continuity_note: null,
  crop_keyframes_json: [],
};

function candidate(patch: Partial<Candidate>): Candidate {
  return { ...baseCandidate, ...patch };
}

describe("selectVisibleCandidates", () => {
  it("filters by status, moment type, minimum score and search text", () => {
    const result = selectVisibleCandidates({
      candidates: {
        7: [
          candidate({ id: 1, title: "Побег", moment_type: "действие", score: 91, status: "approved" }),
          candidate({ id: 2, title: "Шутка", moment_type: "юмор", score: 88, status: "approved" }),
          candidate({ id: 3, title: "Побег слабый", moment_type: "действие", score: 45, status: "approved" }),
        ],
      },
      selectedEpisodeId: 7,
      filter: "approved",
      sort: "score",
      search: "побег",
      momentType: "действие",
      minScore: 80,
    });

    expect(result.map((item) => item.id)).toEqual([1]);
  });

  it("sorts by boundary quality and exposes problem filter", () => {
    const result = selectVisibleCandidates({
      candidates: {
        7: [
          candidate({ id: 1, score: 99, scores_json: { boundary_quality: 20 }, problems_json: ["обрыв"] }),
          candidate({ id: 2, score: 80, scores_json: { boundary_quality: 95 }, problems_json: ["пауза"] }),
        ],
      },
      selectedEpisodeId: 7,
      filter: "problem",
      sort: "boundary",
      search: "",
      momentType: "all",
      minScore: 0,
    });

    expect(result.map((item) => item.id)).toEqual([2, 1]);
  });
});

describe("candidateMomentTypes", () => {
  it("returns sorted unique moment types for the selected episode", () => {
    expect(
      candidateMomentTypes(
        {
          7: [
            candidate({ id: 1, moment_type: "юмор" }),
            candidate({ id: 2, moment_type: "конфликт" }),
            candidate({ id: 3, moment_type: "юмор" }),
          ],
        },
        7,
      ),
    ).toEqual(["конфликт", "юмор"]);
  });
});
