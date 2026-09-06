import { LibraryShell, DetailRow } from "../components/LibraryShell";
import { dataUrl, req, ValidationError } from "../lib/content";
import { useLibrary } from "../lib/useLibrary";
import type { PodcastEpisode } from "../types";

function parsePodcast(raw: Record<string, unknown>, where: string): PodcastEpisode {
  const cast = req<unknown[]>(raw, "cast", "array", where);
  const script = req<unknown[]>(raw, "script", "array", where);
  if (!cast.length) throw new ValidationError(`${where}: cast must not be empty`);
  if (!script.length) throw new ValidationError(`${where}: script must not be empty`);

  const parsedCast = cast.map((item, index) => {
    const member = item as Record<string, unknown>;
    const at = `${where} cast member ${index + 1}`;
    const speakerId = req<string>(member, "speaker_id", "string", at);
    return {
      speaker_id: speakerId,
      host_id: typeof member.host_id === "string" ? member.host_id : "",
      name: typeof member.name === "string" ? member.name : speakerId,
      voice_file: req<string>(member, "voice_file", "string", at),
      style: typeof member.style === "string" ? member.style : "",
    };
  });
  const speakers = new Set(parsedCast.map((member) => member.speaker_id));

  const parsedScript = script.map((item, index) => {
    const segment = item as Record<string, unknown>;
    const at = `${where} segment ${index + 1}`;
    return {
      segment_name: req<string>(segment, "segment_name", "string", at),
      scenes: req<unknown[]>(segment, "scenes", "array", at).map((sceneItem, sceneIndex) => {
        const scene = sceneItem as Record<string, unknown>;
        const sceneAt = `${at} scene ${sceneIndex + 1}`;
        const speakerId = req<string>(scene, "speaker_id", "string", sceneAt);
        if (!speakers.has(speakerId)) {
          throw new ValidationError(`${sceneAt}: unknown speaker '${speakerId}'`);
        }
        return {
          speaker_id: speakerId,
          dialogue: typeof scene.dialogue === "string" ? scene.dialogue : "",
          directions: typeof scene.directions === "string" ? scene.directions : "",
        };
      }),
    };
  });
  if (!parsedScript.some((segment) => segment.scenes.some((scene) => scene.dialogue.trim()))) {
    throw new ValidationError(`${where}: script must contain spoken dialogue`);
  }
  return {
    episode_title: req<string>(raw, "episode_title", "string", where),
    podcast_show: typeof raw.podcast_show === "string" ? raw.podcast_show : "",
    cast: parsedCast,
    script: parsedScript,
  };
}

export function PodcastView() {
  const lib = useLibrary<PodcastEpisode>("podcasts", parsePodcast);
  const episode = lib.selected?.doc ?? null;
  const entry = lib.selected?.entry;
  const audioFile = entry?.sidecars.find((name) => /\.(mp3|wav)$/i.test(name));
  const audioUrl = audioFile ? dataUrl("podcasts", audioFile) : null;
  const names = new Map(episode?.cast.map((member) => [member.speaker_id, member.name]) ?? []);
  const turns =
    episode?.script.reduce(
      (total, segment) => total + segment.scenes.filter((scene) => scene.dialogue.trim()).length,
      0,
    ) ?? 0;

  const details = episode ? (
    <>
      <p className="details-title">{episode.episode_title}</p>
      <DetailRow label="Show" value={episode.podcast_show || "n/a"} />
      <DetailRow label="Cast" value={episode.cast.map((member) => member.name).join(", ")} />
      <DetailRow label="Segments" value={episode.script.length} />
      <DetailRow label="Spoken turns" value={turns} />
      <DetailRow label="Audio" value={audioFile ?? "not generated"} />
      <DetailRow label="Script" value={entry?.file ?? "n/a"} />
    </>
  ) : null;

  const toolbar = (
    <>
      <button type="button" onClick={lib.reload}>Reload</button>
      <span className="divider" />
      {audioUrl && audioFile ? (
        <a className="button" href={audioUrl} download={audioFile}>Download audio</a>
      ) : (
        <button type="button" disabled>Download audio</button>
      )}
      {entry ? (
        <a className="button" href={dataUrl("podcasts", entry.file)} download={entry.file}>
          Download script
        </a>
      ) : null}
    </>
  );

  return (
    <LibraryShell
      documents={lib.documents}
      errors={lib.errors}
      loading={lib.loading}
      selectedIndex={lib.selectedIndex}
      onSelect={lib.select}
      titleOf={(item) => item.episode_title}
      details={details}
      toolbar={toolbar}
      status={episode ? `${episode.script.length} segments · ${turns} spoken turns · ${audioFile ? "audio ready" : "script only"}` : ""}
      hint="Listen in the browser or download the audio and JSON script"
      emptyMessage="No podcasts found in output/podcasts."
    >
      {episode ? (
        <article className="scroll pad podcast">
          <header className="podcast-header">
            <p className="kicker">{episode.podcast_show}</p>
            <h1>{episode.episode_title}</h1>
            {audioUrl ? (
              <audio key={audioUrl} controls preload="metadata" src={audioUrl}>
                Your browser does not support audio playback.
              </audio>
            ) : (
              <p className="panel muted">Audio has not been rendered yet. The transcript is ready below.</p>
            )}
          </header>
          {episode.script.map((segment, segmentIndex) => (
            <section className="podcast-segment" key={`${segment.segment_name}-${segmentIndex}`}>
              <h2>{segment.segment_name}</h2>
              {segment.scenes.filter((scene) => scene.dialogue.trim()).map((scene, sceneIndex) => (
                <div className="podcast-turn" key={`${scene.speaker_id}-${sceneIndex}`}>
                  <h3>{names.get(scene.speaker_id) ?? scene.speaker_id}</h3>
                  <p>{scene.dialogue}</p>
                </div>
              ))}
            </section>
          ))}
        </article>
      ) : (
        <div className="placeholder">Select a podcast.</div>
      )}
    </LibraryShell>
  );
}
