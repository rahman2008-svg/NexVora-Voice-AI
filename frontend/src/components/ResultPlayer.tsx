import type { TKey } from "../i18n";

interface Props {
  url: string;
  durationSeconds: number | null;
  t: (key: TKey, vars?: Record<string, string | number>) => string;
}

export default function ResultPlayer({ url, durationSeconds, t }: Props) {
  return (
    <section className="panel result" aria-labelledby="result-title">
      <h2 id="result-title">{t("result")}</h2>
      <audio controls src={url} preload="metadata" />
      <div className="row">
        {durationSeconds !== null && <span className="muted">{t("duration", { s: durationSeconds.toFixed(1) })}</span>}
        <a className="btn secondary" href={url} download="nexvora-voice.wav">
          {t("download")}
        </a>
      </div>
    </section>
  );
}
