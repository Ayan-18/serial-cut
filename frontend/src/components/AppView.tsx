import { RefreshCcw } from "lucide-react";

import type { SerialCutsController } from "../hooks/useSerialCutsController";
import { BackendStatusBanner } from "./BackendStatusBanner";
import { CandidateWorkspaceSection } from "./CandidateWorkspaceSection";
import { DashboardSection } from "./DashboardSection";
import { EpisodesSection } from "./EpisodesSection";
import { ExportsPanel } from "./ExportsPanel";
import { LogViewerPanel } from "./LogViewerPanel";
import { ModelCatalogPanel } from "./ModelCatalogPanel";
import { SettingsPanel } from "./SettingsPanel";
import { StoryArcsSection } from "./StoryArcsSection";
import { StoryContextSection } from "./StoryContextSection";
import { SystemPanel } from "./SystemPanel";
import { WorkflowSection } from "./WorkflowSection";

type AppViewProps = {
  controller: SerialCutsController;
};

/**
 * Top-level layout. Each screen section owns its own slice of the
 * `controller` (see ./*Section.tsx) — this component only composes them in
 * order and renders the handful of pieces too small to be worth splitting
 * out (the topbar, the status message, and the settings/diagnostics grids,
 * which are already their own panel components).
 */
export function AppView({ controller }: AppViewProps) {
  const { message, refresh, checks, diagnostics, cacheInfo, runSystemCheck, clearCache, settings, patchSettings, saveSettings, exports } = controller;

  return <main className="app-shell">
    <BackendStatusBanner />
    <section className="topbar"><div><h1>SerialCuts</h1><p>Локальная подготовка вертикальных клипов из серий</p></div><button className="icon-button" title="Обновить всё" onClick={() => refresh()}><RefreshCcw size={20} /></button></section>
    {message && <p className="notice" role="status">{message}</p>}

    <DashboardSection controller={controller} />
    <EpisodesSection controller={controller} />
    <StoryArcsSection controller={controller} />
    <StoryContextSection controller={controller} />
    <CandidateWorkspaceSection controller={controller} />
    <WorkflowSection controller={controller} />

    <ExportsPanel exports={exports} />

    <section className="grid section-gap">
      <SystemPanel checks={checks} diagnostics={diagnostics} cacheInfo={cacheInfo} onRefresh={runSystemCheck} onClearCache={clearCache} />
      <SettingsPanel settings={settings} onPatch={patchSettings} onSave={saveSettings} />
    </section>

    <section className="grid section-gap">
      <ModelCatalogPanel />
      <LogViewerPanel />
    </section>
  </main>;
}
