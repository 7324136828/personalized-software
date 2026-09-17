import { useEffect, useRef, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { QuizView } from "./views/QuizView";
import { MindmapView } from "./views/MindmapView";
import { FlashcardsView } from "./views/FlashcardsView";
import { ReportsView } from "./views/ReportsView";
import { SlidesView } from "./views/SlidesView";
import { DatatableView } from "./views/DatatableView";
import { InfographicView } from "./views/InfographicView";
import { QandaView } from "./views/QandaView";
import { PodcastView } from "./views/PodcastView";

/** One route per tkinter launcher. */
const ROUTES = [
  { path: "quizzes", label: "Quizzes", element: <QuizView /> },
  { path: "qanda", label: "Q&A", element: <QandaView /> },
  { path: "flashcards", label: "Flashcards", element: <FlashcardsView /> },
  { path: "mindmaps", label: "Mind maps", element: <MindmapView /> },
  { path: "reports", label: "Reports", element: <ReportsView /> },
  { path: "slides", label: "Slides", element: <SlidesView /> },
  { path: "datatables", label: "Data tables", element: <DatatableView /> },
  { path: "infographics", label: "Infographics", element: <InfographicView /> },
  { path: "podcasts", label: "Podcasts", element: <PodcastView /> },
];

interface WorkspaceOption {
  id: string;
  name: string;
  workspaceDirectory: string | null;
  outputDirectory: string;
}

interface WorkspaceStatus {
  collectionDirectory: string | null;
  activeWorkspace: string;
  workspaces: WorkspaceOption[];
  outputDirectory: string;
  workspace: string | null;
  exists: boolean;
}

interface UploadedWorkspace {
  id: string;
  name: string;
  originalFilename: string;
  uploadedAt: string;
  workspaceCount: number;
}

export function App() {
  const [workspace, setWorkspace] = useState<WorkspaceStatus | null>(null);
  const [workspaceError, setWorkspaceError] = useState("");
  const [workspaceAction, setWorkspaceAction] = useState<string | null>(null);
  const [uploads, setUploads] = useState<UploadedWorkspace[]>([]);
  const [showUploads, setShowUploads] = useState(false);
  const uploadInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void fetch(`${import.meta.env.BASE_URL}api/workspace`)
      .then(async (response) => {
        if (!response.ok) throw new Error(`Workspace status unavailable (${response.status})`);
        setWorkspace((await response.json()) as WorkspaceStatus);
      })
      .catch((error: Error) => setWorkspaceError(error.message));
  }, []);

  async function activateWorkspace(workspaceId: string) {
    if (!workspace || workspaceId === workspace.activeWorkspace) return;
    setWorkspaceAction("switch");
    setWorkspaceError("");
    try {
      const response = await fetch(`${import.meta.env.BASE_URL}api/workspace/activate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspaceId }),
      });
      const body = (await response.json()) as WorkspaceStatus & { error?: string };
      if (!response.ok) {
        throw new Error(body.error ?? `Output selection failed (${response.status})`);
      }
      setWorkspace(body);
      window.location.reload();
    } catch (error) {
      setWorkspaceError((error as Error).message);
    } finally {
      setWorkspaceAction(null);
    }
  }

  async function uploadWorkspace(file: File) {
    if (!file.name.toLowerCase().endsWith(".zip")) {
      setWorkspaceError("Choose a .zip workspace archive.");
      return;
    }
    setWorkspaceAction("upload");
    setWorkspaceError("");
    try {
      const response = await fetch(`${import.meta.env.BASE_URL}api/workspace/upload`, {
        method: "POST",
        headers: {
          "Content-Type": "application/zip",
          "X-File-Name": encodeURIComponent(file.name),
        },
        body: file,
      });
      const body = (await response.json()) as WorkspaceStatus & { error?: string };
      if (!response.ok) {
        throw new Error(body.error ?? `Workspace upload failed (${response.status})`);
      }
      setWorkspace(body);
      window.location.reload();
    } catch (error) {
      setWorkspaceError((error as Error).message);
    } finally {
      setWorkspaceAction(null);
    }
  }

  async function toggleUploadedWorkspaces() {
    if (showUploads) {
      setShowUploads(false);
      return;
    }
    setWorkspaceAction("list");
    setWorkspaceError("");
    try {
      const response = await fetch(`${import.meta.env.BASE_URL}api/workspace/uploads`);
      const body = (await response.json()) as {
        uploads?: UploadedWorkspace[];
        error?: string;
      };
      if (!response.ok) {
        throw new Error(body.error ?? `Could not list uploaded workspaces (${response.status})`);
      }
      setUploads(body.uploads ?? []);
      setShowUploads(true);
    } catch (error) {
      setWorkspaceError((error as Error).message);
    } finally {
      setWorkspaceAction(null);
    }
  }

  async function loadUploadedWorkspace(uploadId: string) {
    setWorkspaceAction("load");
    setWorkspaceError("");
    try {
      const response = await fetch(`${import.meta.env.BASE_URL}api/workspace/load`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ uploadId }),
      });
      const body = (await response.json()) as WorkspaceStatus & { error?: string };
      if (!response.ok) {
        throw new Error(body.error ?? `Workspace loading failed (${response.status})`);
      }
      setWorkspace(body);
      window.location.reload();
    } catch (error) {
      setWorkspaceError((error as Error).message);
    } finally {
      setWorkspaceAction(null);
    }
  }

  const workspaceBusy = workspaceAction !== null;

  return (
    <div className="app">
      <header className="app-header">
        <h1>Learning Content Viewers</h1>
        <nav>
          {ROUTES.map((route) => (
            <NavLink
              key={route.path}
              to={`/${route.path}`}
              className={({ isActive }) => (isActive ? "tab active" : "tab")}
            >
              {route.label}
            </NavLink>
          ))}
        </nav>
        <div className="workspace-picker">
          {workspaceError ? (
            <span className="workspace-message error-text" role="alert" title={workspaceError}>
              {workspaceError}
            </span>
          ) : null}
          <select
            className="workspace-select"
            aria-label="Active output"
            title={workspace?.outputDirectory ?? "Upload or load a workspace ZIP"}
            value={workspace?.activeWorkspace ?? ""}
            disabled={workspaceBusy || !workspace || workspace.workspaces.length === 0}
            onChange={(event) => void activateWorkspace(event.target.value)}
          >
            {!workspace ? <option value="">Checking outputs...</option> : null}
            {workspace?.workspaces.map((option) => (
              <option key={option.id} value={option.id}>
                {option.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void toggleUploadedWorkspaces()}
            disabled={workspaceBusy}
          >
            {workspaceAction === "list" ? "Loading..." : "Load existing workspace"}
          </button>
          <button type="button" onClick={() => uploadInput.current?.click()} disabled={workspaceBusy}>
            {workspaceAction === "upload" ? "Uploading..." : "Upload ZIP"}
          </button>
          <input
            ref={uploadInput}
            className="visually-hidden"
            type="file"
            accept=".zip,application/zip"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void uploadWorkspace(file);
            }}
          />
          {showUploads ? (
            <div className="workspace-upload-menu" role="menu" aria-label="Uploaded workspaces">
              {uploads.length === 0 ? (
                <p className="muted small">No uploaded ZIP workspaces yet.</p>
              ) : (
                uploads.map((upload) => (
                  <button
                    key={upload.id}
                    type="button"
                    role="menuitem"
                    title={`${upload.originalFilename} - ${upload.workspaceCount} outputs`}
                    disabled={workspaceBusy}
                    onClick={() => void loadUploadedWorkspace(upload.id)}
                  >
                    <strong>{upload.name}</strong>
                    <span>
                      {upload.workspaceCount} output{upload.workspaceCount === 1 ? "" : "s"}
                    </span>
                  </button>
                ))
              )}
            </div>
          ) : null}
        </div>
      </header>

      <Routes>
        <Route path="/" element={<Navigate to="/quizzes" replace />} />
        {ROUTES.map((route) => (
          <Route key={route.path} path={`/${route.path}`} element={route.element} />
        ))}
        <Route path="*" element={<Navigate to="/quizzes" replace />} />
      </Routes>
    </div>
  );
}
