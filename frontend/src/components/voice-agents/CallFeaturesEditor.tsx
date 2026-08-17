"use client";

import { useState } from "react";
import clsx from "clsx";

/* ─── Types ─── */

export type VoicemailConfig = {
  enabled: boolean;
  detection_duration: number;
  check_interval: number;
  min_transcript_length: number;
};

export type DTMFConfig = {
  enabled: boolean;
  menu: Record<string, { action: string; value?: string; label?: string }>;
};

export type LanguageDetectionConfig = {
  enabled: boolean;
  provider: string;
  detection_turns: number;
  supported_languages?: string[];
};

export type AmbientNoiseConfig = {
  enabled: boolean;
  preset: string;
  volume: number;
};

export type FillerConfig = {
  use_fillers: boolean;
  backchanneling: boolean;
  backchanneling_message_gap: number;
};

export type CallingGuardrailsConfig = {
  enabled: boolean;
  start_hour: number;
  end_hour: number;
  sunday_blocked: boolean;
  bypass_urgent: boolean;
};

export type RetryConfig = {
  max_retries: number;
  retry_delay_minutes: number;
  retry_backoff_multiplier: number;
};

export type CallFeaturesConfig = {
  voicemail: VoicemailConfig;
  dtmf: DTMFConfig;
  language_detection: LanguageDetectionConfig;
  ambient_noise: AmbientNoiseConfig;
  filler: FillerConfig;
  calling_guardrails?: CallingGuardrailsConfig;
  retry?: RetryConfig;
  final_call_message?: Record<string, string>;
};

const DEFAULT_VOICEMAIL: VoicemailConfig = {
  enabled: false,
  detection_duration: 30,
  check_interval: 7,
  min_transcript_length: 7,
};

const DEFAULT_DTMF: DTMFConfig = {
  enabled: false,
  menu: {},
};

const DEFAULT_LANG_DETECT: LanguageDetectionConfig = {
  enabled: false,
  provider: "llm",
  detection_turns: 3,
};

const DEFAULT_AMBIENT_NOISE: AmbientNoiseConfig = {
  enabled: false,
  preset: "call-center",
  volume: 0.15,
};

const DEFAULT_FILLER: FillerConfig = {
  use_fillers: false,
  backchanneling: false,
  backchanneling_message_gap: 5.0,
};

const DEFAULT_GUARDRAILS: CallingGuardrailsConfig = {
  enabled: false,
  start_hour: 9,
  end_hour: 22,
  sunday_blocked: true,
  bypass_urgent: false,
};

const DEFAULT_RETRY: RetryConfig = {
  max_retries: 3,
  retry_delay_minutes: 60,
  retry_backoff_multiplier: 1.0,
};

/* ─── Props ─── */

type Props = {
  value: CallFeaturesConfig;
  onChange: (config: CallFeaturesConfig) => void;
};

export default function CallFeaturesEditor({ value, onChange }: Props) {
  const vm = value.voicemail || DEFAULT_VOICEMAIL;
  const dtmf = value.dtmf || DEFAULT_DTMF;
  const langDetect = value.language_detection || DEFAULT_LANG_DETECT;
  const noise = value.ambient_noise || DEFAULT_AMBIENT_NOISE;
  const filler = value.filler || DEFAULT_FILLER;
  const guardrails = value.calling_guardrails || DEFAULT_GUARDRAILS;
  const retryCfg = value.retry || DEFAULT_RETRY;
  const [dtmfDigit, setDtmfDigit] = useState("1");
  const [dtmfAction, setDtmfAction] = useState("agent");
  const [dtmfValue, setDtmfValue] = useState("");

  const updateVM = (patch: Partial<VoicemailConfig>) => {
    onChange({ ...value, voicemail: { ...vm, ...patch } });
  };

  const updateDTMF = (patch: Partial<DTMFConfig>) => {
    onChange({ ...value, dtmf: { ...dtmf, ...patch } });
  };

  const addDtmfOption = () => {
    updateDTMF({
      menu: { ...dtmf.menu, [dtmfDigit]: { action: dtmfAction, value: dtmfValue } },
    });
    setDtmfDigit(String(Number(dtmfDigit) + 1));
  };

  const removeDtmfOption = (digit: string) => {
    const { [digit]: _, ...rest } = dtmf.menu;
    updateDTMF({ menu: rest });
  };

  return (
    <div className="space-y-6">
      {/* ── Voicemail Detection ── */}
      <div className="rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 transition-all duration-300 hover:shadow-md hover:border-violet-500/10">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-bold bg-gradient-to-r from-slate-800 to-slate-600 dark:from-slate-200 dark:to-slate-400 bg-clip-text text-transparent">Voicemail Detection</h3>
            <p className="text-xs text-slate-400 mt-1 font-medium">
              Detect answering machines and hang up to avoid leaving awkward messages
            </p>
          </div>
          <button
            onClick={() => updateVM({ enabled: !vm.enabled })}
            className={clsx(
              "relative h-6 w-11 rounded-full transition-colors cursor-pointer",
              vm.enabled ? "bg-violet-600 shadow-md shadow-violet-500/20" : "bg-slate-300 dark:bg-slate-700",
            )}
          >
            <span
              className={clsx(
                "absolute left-0 top-1 h-4 w-4 rounded-full bg-white transition-transform",
                vm.enabled ? "translate-x-6" : "translate-x-1",
              )}
            />
          </button>
        </div>

        {vm.enabled && (
          <div className="mt-5 grid grid-cols-1 gap-5 md:grid-cols-3">
            <label className="block">
              <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Detection Window (seconds)</span>
              <input
                className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
                type="number"
                min={5}
                max={120}
                value={vm.detection_duration}
                onChange={(e) => updateVM({ detection_duration: Number(e.target.value) })}
              />
            </label>
            <label className="block">
              <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Check Interval (seconds)</span>
              <input
                className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
                type="number"
                min={1}
                max={30}
                value={vm.check_interval}
                onChange={(e) => updateVM({ check_interval: Number(e.target.value) })}
              />
            </label>
            <label className="block">
              <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Min Transcript Length (words)</span>
              <input
                className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
                type="number"
                min={1}
                max={50}
                value={vm.min_transcript_length}
                onChange={(e) => updateVM({ min_transcript_length: Number(e.target.value) })}
              />
            </label>
          </div>
        )}
      </div>

      {/* ── DTMF Keypad Input ── */}
      <div className="rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 transition-all duration-300 hover:shadow-md hover:border-violet-500/10">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-bold bg-gradient-to-r from-slate-800 to-slate-600 dark:from-slate-200 dark:to-slate-400 bg-clip-text text-transparent">DTMF Keypad Input</h3>
            <p className="text-xs text-slate-400 mt-1 font-medium">
              Let callers press digits on their phone keypad to interact with your agent
            </p>
          </div>
          <button
            onClick={() => updateDTMF({ enabled: !dtmf.enabled })}
            className={clsx(
              "relative h-6 w-11 rounded-full transition-colors cursor-pointer",
              dtmf.enabled ? "bg-violet-600 shadow-md shadow-violet-500/20" : "bg-slate-300 dark:bg-slate-700",
            )}
          >
            <span
              className={clsx(
                "absolute left-0 top-1 h-4 w-4 rounded-full bg-white transition-transform",
                dtmf.enabled ? "translate-x-6" : "translate-x-1",
              )}
            />
          </button>
        </div>

        {dtmf.enabled && (
          <div className="mt-5 space-y-4">
            <div className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">DTMF Menu Options</div>

            {Object.entries(dtmf.menu).length > 0 && (
              <div className="space-y-2 mb-4">
                {Object.entries(dtmf.menu).map(([digit, opt]) => (
                  <div
                    key={digit}
                    className="flex items-center justify-between rounded-xl border border-slate-200 bg-white/40 px-4 py-3 text-sm dark:border-slate-800 dark:bg-slate-900/40 backdrop-blur-sm"
                  >
                    <div className="flex items-center gap-3">
                      <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-violet-100 to-indigo-100 text-xs font-extrabold text-violet-750 dark:from-violet-950/60 dark:to-indigo-950/60 dark:text-violet-300">
                        {digit}
                      </span>
                      <span className="font-bold text-slate-800 dark:text-slate-200">{opt.label || opt.action}</span>
                      <span className="text-xs text-slate-400">({opt.action}{opt.value ? ` → ${opt.value}` : ""})</span>
                    </div>
                    <button
                      onClick={() => removeDtmfOption(digit)}
                      className="text-slate-400 hover:text-red-500 dark:text-slate-500 dark:hover:text-red-400 transition-colors p-1 cursor-pointer"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="flex flex-wrap items-end gap-3.5 bg-slate-50/50 dark:bg-slate-850/50 p-4 rounded-2xl border border-slate-100 dark:border-slate-800/40">
              <label className="block w-24">
                <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Digit</span>
                <select
                  className="w-full rounded-xl border border-slate-200 bg-white/50 px-3 py-2 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500 cursor-pointer"
                  value={dtmfDigit}
                  onChange={(e) => setDtmfDigit(e.target.value)}
                >
                  {["0","1","2","3","4","5","6","7","8","9","*","#"].map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>
              </label>
              <label className="block w-44">
                <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Action</span>
                <select
                  className="w-full rounded-xl border border-slate-200 bg-white/50 px-3 py-2 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500 cursor-pointer"
                  value={dtmfAction}
                  onChange={(e) => setDtmfAction(e.target.value)}
                >
                  <option value="agent">Connect to AI</option>
                  <option value="transfer">Transfer</option>
                  <option value="repeat">Repeat menu</option>
                  <option value="hangup">Hang up</option>
                </select>
              </label>
              <label className="block flex-1 min-w-[200px]">
                <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">
                  Value (for transfer, e.g. phone number)
                </span>
                <input
                  className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-955/40 dark:text-slate-100 dark:focus:border-violet-500"
                  value={dtmfValue}
                  onChange={(e) => setDtmfValue(e.target.value)}
                  placeholder="+919876543210"
                />
              </label>
              <button
                onClick={addDtmfOption}
                className="inline-flex items-center gap-1.5 justify-center rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-md shadow-violet-500/10 hover:from-violet-500 hover:to-indigo-500 hover:shadow-violet-500/25 active:scale-95 transition-all cursor-pointer h-[38px]"
              >
                + Add
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── Final Call Message ── */}
      <div className="rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 transition-all duration-300 hover:shadow-md hover:border-violet-500/10">
        <h3 className="mb-4 text-sm font-bold bg-gradient-to-r from-slate-800 to-slate-600 dark:from-slate-200 dark:to-slate-400 bg-clip-text text-transparent">Final Call Message</h3>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <label className="block">
            <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">English</span>
            <input
              className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
              value={(value.final_call_message?.en || "") as string}
              onChange={(e) =>
                onChange({
                  ...value,
                  final_call_message: { ...(value.final_call_message || {}), en: e.target.value },
                })
              }
              placeholder="Thank you for your time. Goodbye!"
            />
          </label>
          <label className="block">
            <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Hindi</span>
            <input
              className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
              value={(value.final_call_message?.hi || "") as string}
              onChange={(e) =>
                onChange({
                  ...value,
                  final_call_message: { ...(value.final_call_message || {}), hi: e.target.value },
                })
              }
              placeholder="आपके समय के लिए धन्यवाद। नमस्ते!"
            />
          </label>
        </div>
      </div>

      {/* ── Language Detection ── */}
      <div className="rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 transition-all duration-300 hover:shadow-md hover:border-violet-500/10">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-bold bg-gradient-to-r from-slate-800 to-slate-600 dark:from-slate-200 dark:to-slate-400 bg-clip-text text-transparent">Language Detection & Auto-Switch</h3>
            <p className="text-xs text-slate-400 mt-1 font-medium">
              Detect caller language after N turns and switch agent responses + TTS dynamically
            </p>
          </div>
          <button
            onClick={() => onChange({
              ...value,
              language_detection: { ...langDetect, enabled: !langDetect.enabled },
            })}
            className={clsx(
              "relative h-6 w-11 rounded-full transition-colors cursor-pointer",
              langDetect.enabled ? "bg-violet-600 shadow-md shadow-violet-500/20" : "bg-slate-300 dark:bg-slate-700",
            )}
          >
            <span className={clsx(
              "absolute left-0 top-1 h-4 w-4 rounded-full bg-white transition-transform",
              langDetect.enabled ? "translate-x-6" : "translate-x-1",
            )} />
          </button>
        </div>

        {langDetect.enabled && (
          <div className="mt-5 grid grid-cols-1 gap-5 md:grid-cols-3">
            <label className="block">
              <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Provider</span>
              <select
                className="w-full rounded-xl border border-slate-200 bg-white/50 px-3 py-2 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-955/40 dark:text-slate-100 dark:focus:border-violet-500 cursor-pointer"
                value={langDetect.provider}
                onChange={(e) => onChange({
                  ...value,
                  language_detection: { ...langDetect, provider: e.target.value },
                })}
              >
                <option value="llm">LLM</option>
                <option value="azure">Azure Cognitive</option>
                <option value="sarvam">Sarvam AI</option>
              </select>
            </label>
            <label className="block">
              <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Detection Turns</span>
              <input
                className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
                type="number"
                min={1}
                max={20}
                value={langDetect.detection_turns}
                onChange={(e) => onChange({
                  ...value,
                  language_detection: { ...langDetect, detection_turns: Number(e.target.value) },
                })}
              />
            </label>
          </div>
        )}
      </div>

      {/* ── Ambient Noise ── */}
      <div className="rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 transition-all duration-300 hover:shadow-md hover:border-violet-500/10">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-bold bg-gradient-to-r from-slate-800 to-slate-600 dark:from-slate-200 dark:to-slate-400 bg-clip-text text-transparent">Ambient Background Noise</h3>
            <p className="text-xs text-slate-400 mt-1 font-medium">
              Mix background ambiance into audio (Plivo/Vobiz only)
            </p>
          </div>
          <button
            onClick={() => onChange({
              ...value,
              ambient_noise: { ...noise, enabled: !noise.enabled },
            })}
            className={clsx(
              "relative h-6 w-11 rounded-full transition-colors cursor-pointer",
              noise.enabled ? "bg-violet-600 shadow-md shadow-violet-500/20" : "bg-slate-300 dark:bg-slate-700",
            )}
          >
            <span className={clsx(
              "absolute left-0 top-1 h-4 w-4 rounded-full bg-white transition-transform",
              noise.enabled ? "translate-x-6" : "translate-x-1",
            )} />
          </button>
        </div>

        {noise.enabled && (
          <div className="mt-5 grid grid-cols-1 gap-5 md:grid-cols-2">
            <label className="block">
              <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Preset</span>
              <select
                className="w-full rounded-xl border border-slate-200 bg-white/50 px-3 py-2 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-955/40 dark:text-slate-100 dark:focus:border-violet-500 cursor-pointer"
                value={noise.preset}
                onChange={(e) => onChange({
                  ...value,
                  ambient_noise: { ...noise, preset: e.target.value },
                })}
              >
                <option value="coffee-shop">Coffee Shop</option>
                <option value="office-ambience">Office Ambience</option>
                <option value="call-center">Call Center</option>
              </select>
            </label>
            <label className="block">
              <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Volume ({Math.round(noise.volume * 100)}%)</span>
              <input
                className="w-full accent-violet-600 cursor-pointer"
                type="range"
                min={0}
                max={50}
                value={Math.round(noise.volume * 100)}
                onChange={(e) => onChange({
                  ...value,
                  ambient_noise: { ...noise, volume: Number(e.target.value) / 100 },
                })}
              />
            </label>
          </div>
        )}
      </div>

      {/* ── Calling Guardrails (Time Window) ── */}
      <div className="rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 transition-all duration-300 hover:shadow-md hover:border-violet-500/10">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-bold bg-gradient-to-r from-slate-800 to-slate-600 dark:from-slate-200 dark:to-slate-400 bg-clip-text text-transparent">Calling Guardrails</h3>
            <p className="text-xs text-slate-400 mt-1 font-medium">
              Restrict outbound calls to allowed time windows (per-agent override)
            </p>
          </div>
          <button
            onClick={() => onChange({
              ...value,
              calling_guardrails: { ...guardrails, enabled: !guardrails.enabled },
            })}
            className={clsx(
              "relative h-6 w-11 rounded-full transition-colors cursor-pointer",
              guardrails.enabled ? "bg-violet-600 shadow-md shadow-violet-500/20" : "bg-slate-300 dark:bg-slate-700",
            )}
          >
            <span className={clsx(
              "absolute left-0 top-1 h-4 w-4 rounded-full bg-white transition-transform",
              guardrails.enabled ? "translate-x-6" : "translate-x-1",
            )} />
          </button>
        </div>

        {guardrails.enabled && (
          <div className="mt-5 space-y-4">
            <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
              <label className="block">
                <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Start Hour (0-23)</span>
                <input
                  className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-955/40 dark:text-slate-100 dark:focus:border-violet-500"
                  type="number" min={0} max={23}
                  value={guardrails.start_hour}
                  onChange={(e) => onChange({
                    ...value,
                    calling_guardrails: { ...guardrails, start_hour: Number(e.target.value) },
                  })}
                />
              </label>
              <label className="block">
                <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">End Hour (0-23)</span>
                <input
                  className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-955/40 dark:text-slate-100 dark:focus:border-violet-500"
                  type="number" min={0} max={23}
                  value={guardrails.end_hour}
                  onChange={(e) => onChange({
                    ...value,
                    calling_guardrails: { ...guardrails, end_hour: Number(e.target.value) },
                  })}
                />
              </label>
            </div>
            <div className="flex items-center justify-between py-2 border-b border-slate-100/50 dark:border-slate-800/40">
              <div>
                <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">Block Sundays</p>
                <p className="text-xs text-slate-400 mt-0.5 font-medium">Disallow calls on Sundays</p>
              </div>
              <button
                onClick={() => onChange({
                  ...value,
                  calling_guardrails: { ...guardrails, sunday_blocked: !guardrails.sunday_blocked },
                })}
                className={clsx(
                  "relative h-6 w-11 rounded-full transition-colors cursor-pointer",
                  guardrails.sunday_blocked ? "bg-violet-600 shadow-md shadow-violet-500/20" : "bg-slate-300 dark:bg-slate-700",
                )}
              >
                <span className={clsx(
                  "absolute left-0 top-1 h-4 w-4 rounded-full bg-white transition-transform",
                  guardrails.sunday_blocked ? "translate-x-6" : "translate-x-1",
                )} />
              </button>
            </div>
            <div className="flex items-center justify-between py-2">
              <div>
                <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">Urgent Bypass</p>
                <p className="text-xs text-slate-400 mt-0.5 font-medium">Allow urgent calls outside window</p>
              </div>
              <button
                onClick={() => onChange({
                  ...value,
                  calling_guardrails: { ...guardrails, bypass_urgent: !guardrails.bypass_urgent },
                })}
                className={clsx(
                  "relative h-6 w-11 rounded-full transition-colors cursor-pointer",
                  guardrails.bypass_urgent ? "bg-violet-600 shadow-md shadow-violet-500/20" : "bg-slate-300 dark:bg-slate-700",
                )}
              >
                <span className={clsx(
                  "absolute left-0 top-1 h-4 w-4 rounded-full bg-white transition-transform",
                  guardrails.bypass_urgent ? "translate-x-6" : "translate-x-1",
                )} />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── Auto-Retry Config ── */}
      <div className="rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 transition-all duration-300 hover:shadow-md hover:border-violet-500/10">
        <h3 className="mb-4 text-sm font-bold bg-gradient-to-r from-slate-800 to-slate-600 dark:from-slate-200 dark:to-slate-400 bg-clip-text text-transparent">Auto-Retry Configuration</h3>
        <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
          <label className="block">
            <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Max Retries</span>
            <input
              className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
              type="number" min={0} max={20}
              value={retryCfg.max_retries}
              onChange={(e) => onChange({
                ...value,
                retry: { ...retryCfg, max_retries: Number(e.target.value) },
              })}
            />
          </label>
          <label className="block">
            <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Delay (minutes)</span>
            <input
              className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
              type="number" min={1} max={1440}
              value={retryCfg.retry_delay_minutes}
              onChange={(e) => onChange({
                ...value,
                retry: { ...retryCfg, retry_delay_minutes: Number(e.target.value) },
              })}
            />
          </label>
          <label className="block">
            <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Backoff Multiplier</span>
            <input
              className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
              type="number" min={1} max={10} step={0.5}
              value={retryCfg.retry_backoff_multiplier}
              onChange={(e) => onChange({
                ...value,
                retry: { ...retryCfg, retry_backoff_multiplier: Number(e.target.value) },
              })}
            />
          </label>
        </div>
      </div>

      {/* ── Conversation Flow (Fillers & Backchanneling) ── */}
      <div className="rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 transition-all duration-300 hover:shadow-md hover:border-violet-500/10">
        <h3 className="mb-4 text-sm font-bold bg-gradient-to-r from-slate-800 to-slate-600 dark:from-slate-200 dark:to-slate-400 bg-clip-text text-transparent">Conversation Flow</h3>
        <div className="space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-100/50 dark:border-slate-800/40">
            <div>
              <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">Backchanneling</p>
              <p className="text-xs text-slate-400 mt-0.5 font-medium">Auto "mm-hmm" responses during user pauses</p>
            </div>
            <button
              onClick={() => onChange({
                ...value,
                filler: { ...filler, backchanneling: !filler.backchanneling },
              })}
              className={clsx(
                "relative h-6 w-11 rounded-full transition-colors cursor-pointer",
                filler.backchanneling ? "bg-violet-600 shadow-md shadow-violet-500/20" : "bg-slate-300 dark:bg-slate-700",
              )}
            >
              <span className={clsx(
                "absolute left-0 top-1 h-4 w-4 rounded-full bg-white transition-transform",
                filler.backchanneling ? "translate-x-6" : "translate-x-1",
              )} />
            </button>
          </div>

          {filler.backchanneling && (
            <label className="block">
              <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">Message Gap (seconds)</span>
              <input
                className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
                type="number"
                min={1}
                max={30}
                step={0.5}
                value={filler.backchanneling_message_gap}
                onChange={(e) => onChange({
                  ...value,
                  filler: { ...filler, backchanneling_message_gap: Number(e.target.value) },
                })}
              />
            </label>
          )}

          <div className="flex items-center justify-between py-2">
            <div>
              <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">Use Fillers</p>
              <p className="text-xs text-slate-400 mt-0.5 font-medium">Strip greetings and filler phrases from LLM responses</p>
            </div>
            <button
              onClick={() => onChange({
                ...value,
                filler: { ...filler, use_fillers: !filler.use_fillers },
              })}
              className={clsx(
                "relative h-6 w-11 rounded-full transition-colors cursor-pointer",
                filler.use_fillers ? "bg-violet-600 shadow-md shadow-violet-500/20" : "bg-slate-300 dark:bg-slate-700",
              )}
            >
              <span className={clsx(
                "absolute left-0 top-1 h-4 w-4 rounded-full bg-white transition-transform",
                filler.use_fillers ? "translate-x-6" : "translate-x-1",
              )} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
