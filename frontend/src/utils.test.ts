import { describe, expect, it } from "vitest";
import { editFromCandidate, formatElapsed, previewCropOffset, previewForegroundStyle, splitLines, stageLabel, statusLabel } from "./utils";
import type { Candidate } from "./types";

const candidate: Candidate = {
  id: 1, episode_id: 2, start_time: 10, end_time: 35, title: "Сцена", description: "",
  moment_type: "dialogue", score: 80, scores_json: {}, rationale: "", problems_json: [],
  crop_mode: "auto-follow", crop_offset_x: 0, crop_scale: 1, thumbnail_path: null,
  status: "approved", story_order: null, story_role: null, continuity_note: null,
  crop_keyframes_json: [{ time: 0, offset: -0.5 }, { time: 10, offset: 0.5 }],
};

describe("frontend utilities", () => {
  it("formats statuses and elapsed time", () => {
    expect(formatElapsed(65)).toBe("01:05");
    expect(stageLabel("render_story_arc")).toBe("рендер StoryArc");
    expect(statusLabel("stale")).toBe("нужно обновить");
  });

  it("normalizes multiline inputs", () => {
    expect(splitLines(" событие 1\n\n событие 2 ")).toEqual(["событие 1", "событие 2"]);
  });

  it("interpolates automatic crop keyframes", () => {
    const edit = editFromCandidate(candidate);
    expect(previewCropOffset(candidate, edit, 15)).toBeCloseTo(0);
    expect(previewCropOffset(candidate, { ...edit, crop: "center-crop" }, 15)).toBe(0);
    expect(previewCropOffset(candidate, edit, 30)).toBe(0.5);
  });

  it("opens legacy blurred candidates with the centre choice", () => {
    expect(editFromCandidate({ ...candidate, crop_mode: "blurred-background" }).crop).toBe("center-crop");
  });

  it("matches FFmpeg crop position and zoom at both frame edges", () => {
    expect(previewForegroundStyle(-1, 1)).toEqual({
      objectPosition: "0% 50%", transformOrigin: "0% 50%", transform: "scale(1)",
    });
    expect(previewForegroundStyle(1, 1.25)).toEqual({
      objectPosition: "100% 50%", transformOrigin: "100% 50%", transform: "scale(1.25)",
    });
    expect(previewForegroundStyle(0, 1).objectPosition).toBe("50% 50%");
  });
});
