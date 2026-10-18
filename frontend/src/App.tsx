import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  fetchHealth,
  generateClone,
  generateSpeech,
  type DesignValues,
  type HealthResponse,
} from "./api";
import { errorText, translate, type Lang, type TKey } from "./i18n";
import HealthBadge from "./components/HealthBadge";
import VoicePanel, { type VoiceState } from "./components/VoicePanel";
import ResultPlayer from "./components/ResultPlayer";

const EMPTY_DESIGN: DesignValues = { gender: "", age: "", pitch: "", style: "", accent: "" };
const INITIAL_VOICE: VoiceState = {
  mode: "auto",
  design: EMPTY_DESIGN,
  speed: 1,
  numStep: 32,
  file: null,
  refText: "",
  consent: false,
};

type UiError = { code: string } | { key: TKey };

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem("nexvora-lang");
    if (saved === "en" || saved === "bn") return saved;
  } catch {
    /* storage unavailable */
  }
  return navigator.language?.toLowerCase().startsWith("bn") ? "bn" : "en";
}

export default function App() {
  const [lang, setLang] = useState<Lang>(initialLang);
  const [text, setText] = useState("");
  const [voice, setVoice] = useState<VoiceState>(INITIAL_VOICE);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [offline, setOffline] = useState(false);
  const [checking, setChecking] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<UiError | null>(null);
  const [result, setResult] = useState<{ url: string; duration: number | null } | null>(null);

  const busyRef = useRef(false); // synchronous guard against double clicks
  const abortRef = useRef<AbortController | null>(null);
  const t = useCallback((key: TKey, vars?: Record<string, string | number>) => translate(lang, key, vars), [lang]);

  // language persistence + <html lang>
  useEffect(() => {
    document.documentElement.lang = lang;
    try {
      localStorage.setItem("nexvora-lang", lang);
    } catch {
      /* ignore */
    }
  }, [lang]);

  // health polling (faster while the model is loading)
  const [healthTick, setHealthTick] = useState(0);
  useEffect(() => {
    const ctrl = new AbortController();
    let timer: number | undefined;
    setChecking(true);
    fetchHealth(ctrl.signal)
      .then((h) => {
        setHealth(h);
        setOffline(false);
        timer = window.setTimeout(() => setHealthTick((n) => n + 1), h.status === "loading" ? 4000 : 20000);
      })
      .catch(() => {
        if (ctrl.signal.aborted) return;
        setOffline(true);
        timer = window.setTimeout(() => setHealthTick((n) => n + 1), 10000);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setChecking(false);
      });
    return () => {
      ctrl.abort();
      window.clearTimeout(timer);
    };
  }, [healthTick]);

  // elapsed-time indicator (real progress is not available from a single blocking request)
  useEffect(() => {
    if (!generating) return;
    setElapsed(0);
    const id = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => window.clearInterval(id);
  }, [generating]);

  // free blob URLs
  useEffect(() => () => {
    if (result) URL.revokeObjectURL(result.url);
  }, [result]);
  useEffect(() => () => abortRef.current?.abort(), []);

  const maxChars = health?.limits.max_text_chars ?? 1000;
  const tooLong = text.length > maxChars;
  const modelBlocked = !offline && (health?.status === "unavailable" || health?.status === "loading");

  const patchVoice = (patch: Partial<VoiceState>) => setVoice((v) => ({ ...v, ...patch }));

  async function onGenerate() {
    if (busyRef.current) return;
    const clean = text.trim();
    if (!clean) return setError({ code: "text_empty" });
    if (clean.length > maxChars) return setError({ code: "text_too_long" });
    if (voice.mode === "clone") {
      if (!voice.file) return setError({ key: "noFile" });
      if (!voice.consent) return setError({ key: "needConsent" });
    }
    busyRef.current = true;
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setError(null);
    setGenerating(true);
    try {
      const common = { text: clean, speed: voice.speed, numStep: voice.numStep };
      const res =
        voice.mode === "clone"
          ? await generateClone(
              { ...common, refAudio: voice.file as File, refText: voice.refText, consent: voice.consent },
              ctrl.signal,
            )
          : await generateSpeech({ ...common, mode: voice.mode, design: voice.design }, ctrl.signal);
      setResult({ url: URL.createObjectURL(res.blob), duration: res.durationSeconds });
    } catch (e) {
      setError({ code: e instanceof ApiError ? e.code : "unknown" });
    } finally {
      busyRef.current = false;
      abortRef.current = null;
      setGenerating(false);
    }
  }

  function onReset() {
    abortRef.current?.abort();
    setText("");
    setVoice(INITIAL_VOICE);
    setError(null);
    setResult(null);
  }

  const errorMessage = useMemo(() => {
    if (!error) return null;
    return "key" in error ? t(error.key) : errorText(lang, error.code);
  }, [error, lang, t]);

  return (
    <div className="shell">
      <header className="top">
        <div className="brand">
          <span className="logo" aria-hidden="true">NV</span>
          <div>
            <h1>{t("appName")}</h1>
            <p className="muted">{t("tagline")}</p>
          </div>
        </div>
        <div className="lang" role="group" aria-label={t("language")}>
          <button type="button" aria-pressed={lang === "en"} onClick={() => setLang("en")}>EN</button>
          <button type="button" aria-pressed={lang === "bn"} onClick={() => setLang("bn")} lang="bn">বাংলা</button>
        </div>
      </header>

      <HealthBadge health={health} offline={offline} checking={checking} t={t} onRetry={() => setHealthTick((n) => n + 1)} />

      <main>
        <section className="panel">
          <label htmlFor="tts-text" className="label">{t("textLabel")}</label>
          <textarea
            id="tts-text"
            rows={7}
            value={text}
            disabled={generating}
            placeholder={t("textPlaceholder")}
            aria-describedby="char-count"
            aria-invalid={tooLong}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="row">
            <span id="char-count" className={tooLong ? "count over" : "count"}>
              {t("charCount", { n: text.length, max: maxChars })}
            </span>
            <button type="button" className="btn ghost" disabled={generating} onClick={() => setText(t("exampleText"))}>
              {t("example")}
            </button>
          </div>
        </section>

        <VoicePanel state={voice} onChange={patchVoice} health={health} disabled={generating} t={t} />

        {errorMessage && (
          <p className="alert" role="alert">{errorMessage}</p>
        )}

        <div className="actions">
          <button type="button" className="btn primary" onClick={onGenerate} disabled={generating || modelBlocked} aria-busy={generating}>
            {generating ? t("generating") : t("generate")}
          </button>
          {generating ? (
            <button type="button" className="btn secondary" onClick={() => abortRef.current?.abort()}>{t("cancel")}</button>
          ) : (
            <button type="button" className="btn secondary" onClick={onReset}>{t("clear")}</button>
          )}
        </div>

        {generating && (
          <div className="progress-wrap">
            <div className="progress" role="progressbar" aria-label={t("generating")}><span /></div>
            <p className="muted" aria-hidden="true">{t("elapsed", { s: elapsed })}</p>
          </div>
        )}
        <p className="sr-only" role="status">{generating ? t("generating") : ""}</p>

        {result && <ResultPlayer url={result.url} durationSeconds={result.duration} t={t} />}
      </main>

      <footer className="muted">{t("footer")}</footer>
    </div>
  );
}
