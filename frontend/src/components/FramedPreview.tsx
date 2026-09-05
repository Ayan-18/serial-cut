import type { RefObject } from "react";

import type { Candidate, CandidateEdit, Subtitle } from "../types";
import { previewCropOffset, previewForegroundStyle } from "../utils";

type FramedPreviewProps = {
  candidate: Candidate;
  edit: CandidateEdit;
  videoTime: number;
  subtitle?: Subtitle;
  videoRef: RefObject<HTMLVideoElement | null>;
  backgroundRef: RefObject<HTMLVideoElement | null>;
  onTimeUpdate: () => void;
};

export function FramedPreview({ candidate, edit, videoTime, subtitle, videoRef, backgroundRef, onTimeUpdate }: FramedPreviewProps) {
  const source = `/api/episodes/${candidate.episode_id}/proxy`;
  const syncBackground = () => {
    const player = videoRef.current;
    const background = backgroundRef.current;
    if (!player || !background) return;
    background.currentTime = player.currentTime;
    background.playbackRate = player.playbackRate;
  };
  return (
    <div className="preview-frame">
      <video className="preview-background" ref={backgroundRef} muted playsInline aria-hidden="true" src={source} />
      <div className="preview-window">
        <video
          className="preview-foreground"
          ref={videoRef}
          controls
          playsInline
          src={source}
          onTimeUpdate={onTimeUpdate}
          onSeeked={syncBackground}
          onRateChange={syncBackground}
          onPlay={() => { syncBackground(); backgroundRef.current?.play().catch(() => undefined); }}
          onPause={() => backgroundRef.current?.pause()}
          style={previewForegroundStyle(previewCropOffset(candidate, edit, videoTime), edit.scale)}
        />
      </div>
      {subtitle && <div className="subtitle-preview"><small>{subtitle.speaker_label}</small>{subtitle.text}</div>}
    </div>
  );
}
