import { useEffect } from "react";
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

  // Drive the crop from a 60 fps rAF loop reading video.currentTime directly:
  // the `timeupdate` event only fires ~4x/s, which makes the follow look jerky
  // even when the keyframes are perfectly smooth.
  useEffect(() => {
    const player = videoRef.current;
    if (!player) return;
    let frame = 0;
    const tick = () => {
      const style = previewForegroundStyle(
        previewCropOffset(candidate, edit, player.currentTime),
        edit.scale,
      );
      player.style.objectPosition = style.objectPosition;
      player.style.transformOrigin = style.transformOrigin;
      player.style.transform = style.transform;
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [candidate, edit, videoRef]);

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
