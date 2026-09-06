import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { App } from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* Hash routing keeps every view on the backend's single index page. */}
    <HashRouter>
      <App />
    </HashRouter>
  </StrictMode>,
);
