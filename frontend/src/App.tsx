import { useEffect, useState } from "react";

import ChatPanel from "./chat/ChatPanel";
import ConfirmDialog from "./components/ConfirmDialog";
import StatusReadout from "./components/StatusReadout";
import ViewerOverlay from "./components/ViewerOverlay";
import { controller } from "./state/controller";
import { useStore } from "./state/store";
import ViewerCanvas from "./viewer/ViewerCanvas";

export default function App() {
  const pendingConfirmId = useStore((s) => s.pendingConfirmModelId);
  const models = useStore((s) => s.models);
  const activeModel = useStore((s) => s.activeModel);
  const hasMessages = useStore((s) => s.messages.length > 0);
  const [resetOpen, setResetOpen] = useState(false);

  useEffect(() => {
    void controller.bootstrap();
  }, []);

  const pendingModel = models.find((m) => m.source_model_id === pendingConfirmId) ?? null;
  const isSwitch = activeModel !== null && activeModel.source_model_id !== pendingConfirmId;

  const onResetApp = () => {
    if (hasMessages || activeModel) setResetOpen(true);
    else void controller.resetApp();
  };

  return (
    <div className="app">
      <ViewerCanvas />
      <ViewerOverlay />
      <StatusReadout />
      <ChatPanel onResetApp={onResetApp} />

      {pendingModel && (
        <ConfirmDialog
          title={isSwitch ? "Switch model?" : "Load model?"}
          body={
            isSwitch
              ? `Switching to “${pendingModel.display_name}” clears current results and selection, then loads the new model.`
              : `Load “${pendingModel.display_name}” into the viewer? This downloads the prepared 3D artifact.`
          }
          confirmLabel={isSwitch ? "Switch" : "Load"}
          onCancel={() => useStore.getState().setPendingConfirm(null)}
          onConfirm={() => {
            useStore.getState().setPendingConfirm(null);
            void controller.confirmAndLoadModel(pendingModel);
          }}
        />
      )}

      {resetOpen && (
        <ConfirmDialog
          title="Reset the app?"
          body="This clears the conversation, selection, and current model, and returns to the starting screen. The model cache is kept."
          confirmLabel="Reset"
          tone="danger"
          onCancel={() => setResetOpen(false)}
          onConfirm={() => {
            setResetOpen(false);
            void controller.resetApp();
          }}
        />
      )}
    </div>
  );
}
