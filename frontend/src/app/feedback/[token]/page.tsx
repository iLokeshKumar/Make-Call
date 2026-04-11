"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Star, Send, CheckCircle, XCircle, Clock } from "lucide-react";
import clsx from "clsx";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

type CsatInfo = {
  status: "pending" | "already_submitted";
  company_name?: string;
  company_logo?: string | null;
  lead_name?: string;
  rep_name?: string;
  expires_at?: string | null;
};

export default function CsatPublicPage() {
  const params = useParams();
  const token = params?.token as string;

  const [info, setInfo] = useState<CsatInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [rating, setRating] = useState(0);
  const [hover, setHover] = useState(0);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [submitError, setSubmitError] = useState("");

  useEffect(() => {
    if (!token) return;
    fetch(`${API_BASE}/feedback/csat/${token}`)
      .then(async res => {
        if (res.status === 404) throw new Error("This feedback link is invalid or has been removed.");
        if (res.status === 410) throw new Error("This feedback link has expired.");
        if (!res.ok) throw new Error("Unable to load feedback form.");
        return res.json();
      })
      .then(setInfo)
      .catch(e => setLoadError(e.message));
  }, [token]);

  async function handleSubmit() {
    if (!rating) { setSubmitError("Please select a rating."); return; }
    setSubmitting(true); setSubmitError("");
    try {
      const res = await fetch(`${API_BASE}/feedback/csat/${token}/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating, comment: comment.trim() || null }),
      });
      if (res.status === 409) { setDone(true); return; }
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Submission failed.");
      setDone(true);
    } catch (e) { setSubmitError(e instanceof Error ? e.message : "Failed"); }
    finally { setSubmitting(false); }
  }

  const STAR_LABELS = ["", "Poor", "Fair", "Good", "Very Good", "Excellent"];
  const STAR_COLORS = ["", "#f87171", "#fb923c", "#fbbf24", "#34d399", "#34d399"];

  // Loading
  if (!info && !loadError) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-950">
        <div className="h-8 w-8 rounded-full border-2 border-violet-500 border-t-transparent animate-spin" />
      </div>
    );
  }

  // Error
  if (loadError) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-950 p-4">
        <div className="w-full max-w-sm text-center space-y-4">
          <XCircle className="h-12 w-12 text-red-400 mx-auto" />
          <p className="text-white font-semibold">{loadError}</p>
        </div>
      </div>
    );
  }

  // Already submitted
  if (info?.status === "already_submitted" || done) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 p-4">
        <div className="w-full max-w-sm text-center space-y-6">
          <div className="flex h-20 w-20 mx-auto items-center justify-center rounded-full bg-emerald-500/15">
            <CheckCircle className="h-10 w-10 text-emerald-400" />
          </div>
          <div>
            <h2 className="text-2xl font-bold text-white">Thank you!</h2>
            <p className="text-slate-400 mt-2">Your feedback has been received. We truly appreciate you taking the time.</p>
          </div>
          {info?.company_name && (
            <p className="text-xs text-slate-600">— {info.company_name} Team</p>
          )}
        </div>
      </div>
    );
  }

  // Form
  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 p-4">
      <div className="w-full max-w-md space-y-6">
        {/* Company branding */}
        <div className="text-center space-y-3">
          {info?.company_logo ? (
            <img src={info.company_logo} alt={info.company_name} className="h-12 mx-auto object-contain" />
          ) : (
            <div className="h-12 w-12 mx-auto rounded-xl bg-gradient-to-br from-violet-600 to-blue-600 flex items-center justify-center">
              <span className="text-white font-bold text-xl">{info?.company_name?.[0] ?? "R"}</span>
            </div>
          )}
          <p className="text-sm text-slate-500 font-medium">{info?.company_name}</p>
        </div>

        {/* Card */}
        <div className="rounded-3xl bg-white/5 border border-white/10 backdrop-blur-sm p-8 space-y-7">
          <div className="text-center">
            <h1 className="text-2xl font-bold text-white leading-snug">
              How was your experience with <span className="text-violet-400">{info?.rep_name}</span>?
            </h1>
            <p className="text-slate-500 text-sm mt-2">Hi {info?.lead_name}, your feedback helps us improve.</p>
          </div>

          {/* Star rating */}
          <div className="text-center space-y-3">
            <div className="flex justify-center gap-2">
              {[1,2,3,4,5].map(n => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setRating(n)}
                  onMouseEnter={() => setHover(n)}
                  onMouseLeave={() => setHover(0)}
                  className="transition-transform hover:scale-125 active:scale-110"
                >
                  <Star
                    className="h-10 w-10 transition-colors duration-150"
                    style={{
                      color: n <= (hover || rating) ? STAR_COLORS[hover || rating] : "#334155",
                      fill: n <= (hover || rating) ? STAR_COLORS[hover || rating] : "transparent",
                    }}
                  />
                </button>
              ))}
            </div>
            {(hover || rating) > 0 && (
              <p className="text-sm font-semibold transition-all" style={{ color: STAR_COLORS[hover || rating] }}>
                {STAR_LABELS[hover || rating]}
              </p>
            )}
          </div>

          {/* Comment */}
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-widest text-slate-500">
              Additional comments <span className="normal-case font-normal">(optional)</span>
            </label>
            <textarea
              value={comment}
              onChange={e => setComment(e.target.value)}
              rows={3}
              placeholder="Tell us more about your experience…"
              className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-violet-500 resize-none"
            />
          </div>

          {submitError && <p className="text-xs text-red-400 text-center">{submitError}</p>}

          <button
            onClick={handleSubmit}
            disabled={submitting || !rating}
            className={clsx(
              "w-full rounded-xl py-3.5 font-bold text-white transition-all flex items-center justify-center gap-2",
              rating
                ? "bg-gradient-to-r from-violet-600 to-blue-600 shadow-lg shadow-violet-500/30 hover:shadow-xl"
                : "bg-white/5 cursor-not-allowed",
              submitting && "opacity-60"
            )}
          >
            {submitting ? (
              <div className="h-5 w-5 rounded-full border-2 border-white border-t-transparent animate-spin" />
            ) : (
              <><Send className="h-4 w-4" /> Submit Feedback</>
            )}
          </button>
        </div>

        {/* Expiry notice */}
        {info?.expires_at && (
          <p className="text-center text-xs text-slate-600 flex items-center justify-center gap-1">
            <Clock className="h-3 w-3" />
            Link expires {new Date(info.expires_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })}
          </p>
        )}
      </div>
    </div>
  );
}
