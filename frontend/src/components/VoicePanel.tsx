import type { DesignKey, DesignValues, HealthResponse, Mode } from "../api";
import type { TKey } from "../i18n";

export interface VoiceState {
  mode: Mode;
  design: DesignValues;
  speed: number;
  numStep: number;
  file: File | null;
  refText: string;
  consent: boolean;
}

interface Props {
  state: VoiceState;
  onChange: (patch: Partial<VoiceState>) => void;
  health: HealthResponse | null;
  disabled: boolean;
  t: (key: TKey, vars?: Record<string, string | number>) => string;
}

const DESIGN_KEYS: DesignKey[] = ["gender", "age", "pitch", "style", "accent"];

export default function VoicePanel({ state, onChange, health, disabled, t }: Props) {
  const cloning = health?.capabilities.voice_cloning ?? false;
  const modes: { id: Mode; label: TKey }[] = [
    { id: "auto", label: "modeAuto" },
    { id: "design", label: "modeDesign" },
    ...(cloning ? [{ id: "clone" as Mode, label: "modeClone" as TKey }] : []),
  ];
  const minSpeed = health?.limits.min_speed ?? 0.5;
  const maxSpeed = health?.limits.max_speed ?? 2;

  return (
    <fieldset className="panel" disabled={disabled}>
      <legend>{t("voiceSection")}</legend>

      <div className="segmented" role="radiogroup" aria-label={t("voiceSection")}>
        {modes.map((m) => (
          <label key={m.id} className={state.mode === m.id ? "seg active" : "seg"}>
            <input
              type="radio"
              name="mode"
              value={m.id}
              checked={state.mode === m.id}
              onChange={() => onChange({ mode: m.id })}
            />
            {t(m.label)}
          </label>
        ))}
      </div>

      {state.mode === "auto" && <p className="hint">{t("modeAutoHint")}</p>}

      {state.mode === "design" && (
        <>
          <p className="hint">{t("modeDesignHint")}</p>
          <div className="grid">
            {DESIGN_KEYS.map((key) => (
              <label key={key} className="field">
                <span>{t(key)}</span>
                <select
                  value={state.design[key]}
                  onChange={(e) => onChange({ design: { ...state.design, [key]: e.target.value } })}
                >
                  <option value="">{t("optionAuto")}</option>
                  {(health?.design_options[key] ?? []).map((v) => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        </>
      )}

      {state.mode === "clone" && (
        <div className="stack">
          <label className="field">
            <span>{t("cloneFile")}</span>
            <input
              type="file"
              accept=".wav,.mp3,.flac,.ogg,.m4a,audio/*"
              onChange={(e) => onChange({ file: e.target.files?.[0] ?? null })}
            />
          </label>
          <label className="field">
            <span>{t("cloneText")}</span>
            <input
              type="text"
              maxLength={500}
              value={state.refText}
              onChange={(e) => onChange({ refText: e.target.value })}
            />
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={state.consent}
              onChange={(e) => onChange({ consent: e.target.checked })}
            />
            <span>{t("cloneConsent")}</span>
          </label>
          <p className="hint">{t("cloneNote")}</p>
        </div>
      )}

      <div className="grid">
        <label className="field">
          <span>
            {t("speed")}: <strong>{state.speed.toFixed(2)}×</strong>
          </span>
          <input
            type="range"
            min={minSpeed}
            max={maxSpeed}
            step={0.05}
            value={state.speed}
            onChange={(e) => onChange({ speed: Number(e.target.value) })}
          />
        </label>
        <label className="field">
          <span>
            {t("quality")}: <strong>{state.numStep}</strong>
          </span>
          <input
            type="range"
            min={8}
            max={64}
            step={8}
            value={state.numStep}
            onChange={(e) => onChange({ numStep: Number(e.target.value) })}
            aria-describedby="quality-hint"
          />
          <small id="quality-hint" className="muted">
            {t("qualityHint")}
          </small>
        </label>
      </div>
    </fieldset>
  );
}
