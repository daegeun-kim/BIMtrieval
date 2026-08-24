// Demo entry point (spec_v013 §3). A separate entry is what lets the demo skip
// model confirmation without editing `src/main.tsx` — it mounts `DemoApp`
// instead of `App`, and everything else about the application is identical.
import React from "react";
import ReactDOM from "react-dom/client";

// Self-hosted fonts, matching src/main.tsx. No runtime external calls: the demo
// makes no network request to any host but its own origin.
import "@fontsource/space-grotesk/500.css";
import "@fontsource/space-grotesk/600.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";

import DemoApp from "./DemoApp";
import "../../src/styles/global.css";
import "../../src/App.css";
import "./demo.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <DemoApp />
  </React.StrictMode>,
);
