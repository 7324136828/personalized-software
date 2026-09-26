import { useEffect, useRef, useState } from "react";
import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { QuizView } from "./views/QuizView";
import { MindmapView } from "./views/MindmapView";
import { FlashcardsView } from "./views/FlashcardsView";
import { ReportsView } from "./views/ReportsView";
import { SlidesView } from "./views/SlidesView";
import { DatatableView } from "./views/DatatableView";
import { InfographicView } from "./views/InfographicView";
import { QandaView } from "./views/QandaView";
import { PodcastView } from "./views/PodcastView";
import { HomeView } from "./views/HomeView";

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
  outputDirectory: string | null;
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
  studySets: { id: string; key: string; name: string }[];
}

interface UploadProgress {
  id: string;
  state: "uploading" | "extracting" | "validating" | "importing" | "finalizing" | "done" | "error";
  percent: number;
  message: string;
  currentWorkspace: string | null;
  completedWorkspaces: number;
  totalWorkspaces: number;
}

type PendingDelete =
  | { kind: "studySet"; id: string; name: string }
  | { kind: "library"; id: string; name: string; workspaceCount: number };

export function App() {
  const navigate = useNavigate();
  const [workspace, setWorkspace] = useState<WorkspaceStatus | null>(null);
  const [workspaceError, setWorkspaceError] = useState("");
  const [workspaceAction, setWorkspaceAction] = useState<string | null>(null);
  const [uploads, setUploads] = useState<UploadedWorkspace[]>([]);
  const [showUploads, setShowUploads] = useState(false);
  const [loadingUploads, setLoadingUploads] = useState(true);
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null);
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);
  const uploadInput = useRef<HTMLInputElement>(null);

  async function refreshUploads() {
    setLoadingUploads(true);
    try {
      const response = await fetch(`${import.meta.env.BASE_URL}api/workspace/uploads`);
      const body = (await response.json()) as { uploads?: UploadedWorkspace[]; error?: string };
      if (!response.ok) throw new Error(body.error ?? `Could not list study sets (${response.status})`);
      setUploads(body.uploads ?? []);
    } finally {
      setLoadingUploads(false);
    }
  }

  useEffect(() => {
    void Promise.all([
      fetch(`${import.meta.env.BASE_URL}api/workspace`).then(async (response) => {
        if (!response.ok) throw new Error(`Workspace status unavailable (${response.status})`);
        setWorkspace((await response.json()) as WorkspaceStatus);
      }),
      refreshUploads(),
    ]).catch((error: Error) => setWorkspaceError(error.message));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function activateWorkspace(workspaceId: string, startStudying = false) {
    if (!workspace) return;
    if (workspaceId === workspace.activeWorkspace) {
      if (startStudying) navigate("/quizzes");
      return;
    }
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
      if (startStudying) navigate("/quizzes");
      else window.location.reload();
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
    if (file.size > 512 * 1024 * 1024) {
      setWorkspaceError("Choose a ZIP smaller than 512 MB.");
      return;
    }
    setWorkspaceAction("upload");
    setWorkspaceError("");
    const progressId = crypto.randomUUID().replaceAll("-", "");
    setUploadProgress({
      id: progressId,
      state: "uploading",
      percent: 0,
      message: "Preparing upload",
      currentWorkspace: null,
      completedWorkspaces: 0,
      totalWorkspaces: 0,
    });
    let polling = true;
    const pollProgress = async () => {
      try {
        const response = await fetch(
          `${import.meta.env.BASE_URL}api/workspace/uploads/progress/${progressId}`,
        );
        if (response.ok && polling) {
          setUploadProgress((await response.json()) as UploadProgress);
        }
      } catch {
        // The upload request remains authoritative; a missed progress poll is harmless.
      }
    };
    const progressTimer = window.setInterval(() => void pollProgress(), 250);
    let succeeded = false;
    try {
      const response = await fetch(`${import.meta.env.BASE_URL}api/workspace/upload`, {
        method: "POST",
        headers: {
          "Content-Type": "application/zip",
          "X-File-Name": encodeURIComponent(file.name),
          "X-Upload-ID": progressId,
          "X-File-Size": String(file.size),
        },
        body: file,
      });
      const body = (await response.json()) as WorkspaceStatus & { error?: string };
      if (!response.ok) {
        throw new Error(body.error ?? `Workspace upload failed (${response.status})`);
      }
      await pollProgress();
      succeeded = true;
      setUploadProgress((current) => current ? {
        ...current,
        state: "done",
        percent: 100,
        message: "Study library ready",
      } : current);
      setWorkspace(body);
      navigate("/");
      try {
        await refreshUploads();
      } catch (error) {
        setWorkspaceError(`Workspace uploaded, but the saved list could not refresh: ${(error as Error).message}`);
      }
    } catch (error) {
      const message = (error as Error).message;
      setWorkspaceError(message);
      setUploadProgress((current) => current ? {
        ...current,
        state: "error",
        message,
      } : current);
    } finally {
      polling = false;
      window.clearInterval(progressTimer);
      await new Promise((resolve) => window.setTimeout(resolve, succeeded ? 500 : 1400));
      setUploadProgress(null);
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
      await refreshUploads();
      setShowUploads(true);
    } catch (error) {
      setWorkspaceError((error as Error).message);
    } finally {
      setWorkspaceAction(null);
    }
  }

  async function loadUploadedWorkspace(
    uploadId: string,
    workspaceId?: string,
    startStudying = false,
  ) {
    setWorkspaceAction("load");
    setWorkspaceError("");
    try {
      const response = await fetch(`${import.meta.env.BASE_URL}api/workspace/load`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ uploadId, workspaceId }),
      });
      const body = (await response.json()) as WorkspaceStatus & { error?: string };
      if (!response.ok) {
        throw new Error(body.error ?? `Workspace loading failed (${response.status})`);
      }
      setWorkspace(body);
      setShowUploads(false);
      if (startStudying) navigate("/quizzes");
      else window.location.reload();
    } catch (error) {
      setWorkspaceError((error as Error).message);
    } finally {
      setWorkspaceAction(null);
    }
  }

  async function deletePendingItem() {
    if (!pendingDelete) return;
    setWorkspaceAction("delete");
    setWorkspaceError("");
    try {
      const response = await fetch(
        pendingDelete.kind === "studySet"
          ? `${import.meta.env.BASE_URL}api/workspace/study-sets/${pendingDelete.id}`
          : `${import.meta.env.BASE_URL}api/workspace/uploads/${pendingDelete.id}`,
        { method: "DELETE" },
      );
      const body = (await response.json()) as WorkspaceStatus & { error?: string };
      if (!response.ok) {
        throw new Error(body.error ?? `Deletion failed (${response.status})`);
      }
      setWorkspace(body);
      setPendingDelete(null);
      try {
        await refreshUploads();
      } catch (error) {
        setWorkspaceError(`Deletion succeeded, but the saved list could not refresh: ${(error as Error).message}`);
      }
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
        <h1><NavLink className="brand-link" to="/">Learning Content Viewers</NavLink></h1>
        <nav>
          <NavLink to="/" end className={({ isActive }) => (isActive ? "tab active" : "tab")}>
            Home
          </NavLink>
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
            {loadingUploads || workspaceAction === "list" ? "Loading..." : "Load existing workspace"}
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
        <Route
          path="/"
          element={
            <HomeView
              workspace={workspace}
              uploads={uploads}
              loadingUploads={loadingUploads}
              busy={workspaceBusy}
              error={workspaceError}
              onChooseCurrent={(workspaceId) => void activateWorkspace(workspaceId, true)}
              onChooseSaved={(uploadId, workspaceId) =>
                void loadUploadedWorkspace(uploadId, workspaceId, true)
              }
              onDeleteSaved={(_uploadId, studySet) =>
                setPendingDelete({ kind: "studySet", id: studySet.id, name: studySet.name })
              }
              onDeleteLibrary={(upload) =>
                setPendingDelete({
                  kind: "library",
                  id: upload.id,
                  name: upload.name,
                  workspaceCount: upload.workspaceCount,
                })
              }
              onUpload={() => uploadInput.current?.click()}
            />
          }
        />
        {ROUTES.map((route) => (
          <Route key={route.path} path={`/${route.path}`} element={route.element} />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>

      {uploadProgress ? (
        <div className="processing-overlay" role="dialog" aria-modal="true" aria-labelledby="processing-title">
          <section className="processing-window" aria-live="polite">
            <div className="processing-percent">{uploadProgress.percent}%</div>
            <div>
              <p className="home-eyebrow">Importing workspace</p>
              <h2 id="processing-title">
                {uploadProgress.state === "error" ? "Import failed" : uploadProgress.message}
              </h2>
            </div>
            <progress max="100" value={uploadProgress.percent} />
            {uploadProgress.currentWorkspace ? (
              <p className="processing-current">
                <span>Current study set</span>
                <strong>{uploadProgress.currentWorkspace}</strong>
              </p>
            ) : (
              <p className="processing-current muted">Checking the archive…</p>
            )}
            {uploadProgress.totalWorkspaces > 0 ? (
              <p className="processing-count muted">
                {Math.min(uploadProgress.completedWorkspaces + 1, uploadProgress.totalWorkspaces)} of {uploadProgress.totalWorkspaces} study sets
              </p>
            ) : null}
            {uploadProgress.state === "error" ? (
              <p className="processing-error error-text">{uploadProgress.message}</p>
            ) : null}
          </section>
        </div>
      ) : null}

      {pendingDelete ? (
        <div className="processing-overlay" role="dialog" aria-modal="true" aria-labelledby="delete-title">
          <section className="delete-window">
            <p className="home-eyebrow">
              {pendingDelete.kind === "studySet" ? "Delete study set" : "Delete ZIP library"}
            </p>
            <h2 id="delete-title">Delete “{pendingDelete.name}”?</h2>
            <p>
              {pendingDelete.kind === "studySet"
                ? "Its imported learning content will be permanently removed. This cannot be undone."
                : `All ${pendingDelete.workspaceCount} study sets imported from this ZIP will be permanently removed. This cannot be undone.`}
            </p>
            <div className="delete-actions">
              <button
                type="button"
                disabled={workspaceAction === "delete"}
                onClick={() => setPendingDelete(null)}
              >
                Cancel
              </button>
              <button
                className="danger-button"
                type="button"
                disabled={workspaceAction === "delete"}
                onClick={() => void deletePendingItem()}
              >
                {workspaceAction === "delete"
                  ? "Deleting…"
                  : pendingDelete.kind === "studySet" ? "Delete study set" : "Delete ZIP library"}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
