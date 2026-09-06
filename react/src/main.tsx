import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { App } from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* HashRouter so the built app also works when opened from the file system. */}
    <HashRouter>
      <App />
    </HashRouter>
  </StrictMode>,
);
