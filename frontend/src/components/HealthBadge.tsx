import type { HealthResponse } from "../api";
import type { TKey } from "../i18n";

interface Props {
  health: HealthResponse | null;
  offline: boolean;
  checking: boolean;
  t: (key: TKey) => string;
  onRetry: () => void;
}

export default function HealthBadge({ health, offline, checking, t, onRetry }: Props) {
  let tone = "warn";
  let label: TKey = "health_checking";
  if (offline) {
    tone = "bad";
    label = "health_offline";
  } else if (health) {
    label = `health_${health.status}` as TKey;
    tone = health.status === "ready" ? "ok" : health.status === "unavailable" ? "bad" : "warn";
  }
  const detail = !offline && health?.status === "unavailable" ? health.model.detail : null;
  return (
    <div className="health" data-tone={tone}>
      <span className="dot" aria-hidden="true" />
      <span role="status">{t(label)}</span>
      {health?.status === "ready" && health.model.device && <span className="muted">· {health.model.device}</span>}
      <button type="button" className="link" onClick={onRetry} disabled={checking}>
        {t("retry")}
      </button>
      {detail && <p className="health-detail">{detail}</p>}
    </div>
  );
}
