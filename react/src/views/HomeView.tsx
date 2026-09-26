interface WorkspaceOption {
  id: string;
  name: string;
}

interface WorkspaceStatus {
  activeWorkspace: string;
  workspaces: WorkspaceOption[];
  exists: boolean;
}

interface StudySet {
  id: string;
  key: string;
  name: string;
}

interface UploadedWorkspace {
  id: string;
  name: string;
  originalFilename: string;
  uploadedAt: string;
  workspaceCount: number;
  studySets: StudySet[];
}

interface HomeViewProps {
  workspace: WorkspaceStatus | null;
  uploads: UploadedWorkspace[];
  loadingUploads: boolean;
  busy: boolean;
  error: string;
  onChooseCurrent: (workspaceId: string) => void;
  onChooseSaved: (uploadId: string, workspaceId: string) => void;
  onDeleteSaved: (uploadId: string, studySet: StudySet) => void;
  onDeleteLibrary: (upload: UploadedWorkspace) => void;
  onUpload: () => void;
}

function StudySetCard({
  name,
  detail,
  active = false,
  disabled,
  onClick,
  onDelete,
}: {
  name: string;
  detail: string;
  active?: boolean;
  disabled: boolean;
  onClick: () => void;
  onDelete?: () => void;
}) {
  return (
    <div className={onDelete ? "study-set-card deletable" : "study-set-card"}>
      <button className="study-set-open" type="button" disabled={disabled} onClick={onClick}>
        <span className="study-set-mark" aria-hidden="true">
          {name.trim().slice(0, 1).toUpperCase() || "S"}
        </span>
        <span className="study-set-copy">
          <strong>{name}</strong>
          <span>{detail}</span>
        </span>
        <span className="study-set-action">{active ? "Continue" : "Study"} →</span>
      </button>
      {onDelete ? (
        <button
          className="study-set-delete"
          type="button"
          disabled={disabled}
          aria-label={`Delete ${name}`}
          onClick={onDelete}
        >
          Delete
        </button>
      ) : null}
    </div>
  );
}

export function HomeView({
  workspace,
  uploads,
  loadingUploads,
  busy,
  error,
  onChooseCurrent,
  onChooseSaved,
  onDeleteSaved,
  onDeleteLibrary,
  onUpload,
}: HomeViewProps) {
  const hasSavedSets = uploads.some((upload) => (upload.studySets ?? []).length > 0);

  return (
    <main className="home-view scroll">
      <section className="home-hero">
        <p className="home-eyebrow">Your learning library</p>
        <h2>Choose a study set</h2>
        <p>
          Pick up where you left off, open a saved set, or import a new workspace ZIP.
        </p>
        <button className="primary big" type="button" disabled={busy} onClick={onUpload}>
          {busy ? "Working…" : "Upload a workspace ZIP"}
        </button>
        {error ? <p className="home-error error-text" role="alert">{error}</p> : null}
      </section>

      {workspace?.exists ? (
        <section className="study-section" aria-labelledby="current-study-sets">
          <div className="study-section-heading">
            <div>
              <p className="home-eyebrow">Open now</p>
              <h3 id="current-study-sets">Current study sets</h3>
            </div>
            <span>{workspace.workspaces.length} available</span>
          </div>
          <div className="study-set-grid">
            {workspace.workspaces.map((option) => (
              <StudySetCard
                key={option.id}
                name={option.name}
                detail={option.id === workspace.activeWorkspace ? "Active study set" : "Current library"}
                active={option.id === workspace.activeWorkspace}
                disabled={busy}
                onClick={() => onChooseCurrent(option.id)}
              />
            ))}
          </div>
        </section>
      ) : null}

      <section className="study-section" aria-labelledby="saved-study-sets">
        <div className="study-section-heading">
          <div>
            <p className="home-eyebrow">Saved locally</p>
            <h3 id="saved-study-sets">Study libraries</h3>
          </div>
          {hasSavedSets ? <span>{uploads.length} {uploads.length === 1 ? "library" : "libraries"}</span> : null}
        </div>

        {loadingUploads ? (
          <div className="home-empty muted">Loading saved study sets…</div>
        ) : hasSavedSets ? (
          <div className="saved-libraries">
            {uploads.map((upload) => (
              <article className="saved-library" key={upload.id}>
                <header>
                  <div>
                    <h4>{upload.name}</h4>
                    <p>{upload.originalFilename}</p>
                  </div>
                  <div className="saved-library-actions">
                    <span>{upload.workspaceCount} {upload.workspaceCount === 1 ? "set" : "sets"}</span>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onDeleteLibrary(upload)}
                    >
                      Delete ZIP
                    </button>
                  </div>
                </header>
                <div className="study-set-grid">
                  {(upload.studySets ?? []).map((studySet) => (
                    <StudySetCard
                      key={studySet.id}
                      name={studySet.name}
                      detail={`From ${upload.name}`}
                      disabled={busy}
                      onClick={() => onChooseSaved(upload.id, studySet.key)}
                      onDelete={() => onDeleteSaved(upload.id, studySet)}
                    />
                  ))}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="home-empty">
            <strong>No saved study sets yet</strong>
            <p className="muted">Upload a ZIP containing an output folder to add one.</p>
          </div>
        )}
      </section>
    </main>
  );
}
