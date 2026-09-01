import { AppView } from "./components/AppView";
import { useSerialCutsController } from "./hooks/useSerialCutsController";

export function App() {
  const controller = useSerialCutsController();
  return <AppView controller={controller} />;
}
