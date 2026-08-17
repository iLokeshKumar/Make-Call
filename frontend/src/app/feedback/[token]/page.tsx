"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle, Clock, Loader2, Send, Star, XCircle } from "lucide-react";
import clsx from "clsx";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { API_BASE } from "@/lib/api";



type CsatInfo = {
  status: "pending" | "already_submitted";
  company_name?: string;
  company_logo?: string | null;
  lead_name?: string;
  rep_name?: string;
  expires_at?: string | null;
};

const STAR_LABELS = ["", "Poor", "Fair", "Good", "Very good", "Excellent"];
const STAR_COLORS = ["", "#f87171", "#fb923c", "#fbbf24", "#34d399", "#34d399"];

export default function CsatPublicPage() {
  const params = useParams();
  const token = params?.token as string;

  const [rating, setRating] = useState(0);
  const [hover, setHover] = useState(0);
  const [comment, setComment] = useState("");
  const [localDone, setLocalDone] = useState(false);

  const infoQuery = useQuery<CsatInfo>({
    queryKey: ["csat-info", token],
    enabled: !!token,
    retry: false,
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/feedback/csat/${token}`);
      if (res.status === 404) throw new Error("This feedback link is invalid or has been removed.");
      if (res.status === 410) throw new Error("This feedback link has expired.");
      if (!res.ok) throw new Error("Unable to load feedback form.");
      return res.json();
    },
  });

  const submit = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE}/feedback/csat/${token}/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating, comment: comment.trim() || null }),
      });
      if (res.status === 409) return { already: true };
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Submission failed.");
      }
      return res.json();
    },
    onSuccess: () => {
      toast.success("Feedback submitted — thank you!");
      setLocalDone(true);
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Submission failed");
    },
  });

  const info = infoQuery.data;
  const done = localDone || info?.status === "already_submitted";

  if (infoQuery.isLoading) {
    return (
      <div className="flex min-h-screen w-full items-center justify-center bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
        <Loader2 className="h-8 w-8 animate-spin text-violet-400" />
      </div>
    );
  }

  if (infoQuery.error) {
    return (
      <div className="flex min-h-screen w-full items-center justify-center bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 p-4">
        <Card className="w-full max-w-sm border-red-500/20 bg-white/5 text-center backdrop-blur-sm">
          <CardContent className="space-y-4 pt-8">
            <XCircle className="mx-auto h-12 w-12 text-red-400" />
            <p className="text-base font-semibold text-white">
              {infoQuery.error instanceof Error ? infoQuery.error.message : "Unable to load feedback form."}
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (done) {
    return (
      <div className="flex min-h-screen w-full items-center justify-center bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 p-4">
        <Card className="w-full max-w-sm border-white/10 bg-white/5 text-center backdrop-blur-sm">
          <CardContent className="space-y-5 pt-10">
            <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-emerald-500/15">
              <CheckCircle className="h-10 w-10 text-emerald-400" />
            </div>
            <div>
              <h2 className="text-2xl font-bold text-white">Thank you!</h2>
              <p className="mt-2 text-sm text-slate-400">
                Your feedback has been received. We truly appreciate you taking the time.
              </p>
            </div>
            {info?.company_name && (
              <p className="text-xs text-slate-500">— {info.company_name} Team</p>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 p-4">
      <div className="w-full max-w-md space-y-6">
        <div className="space-y-3 text-center">
          {info?.company_logo ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img src={info.company_logo} alt={info.company_name} className="mx-auto h-12 object-contain" />
          ) : (
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-violet-600 to-blue-600">
              <span className="text-xl font-bold text-white">{info?.company_name?.[0] ?? "R"}</span>
            </div>
          )}
          <p className="text-sm font-medium text-slate-400">{info?.company_name}</p>
        </div>

        <Card className="border-white/10 bg-white/5 backdrop-blur-sm">
          <CardHeader className="space-y-2 text-center">
            <CardTitle className="text-2xl leading-snug text-white">
              How was your experience with{" "}
              <span className="text-violet-400">{info?.rep_name}</span>?
            </CardTitle>
            <p className="text-sm text-slate-400">
              Hi {info?.lead_name}, your feedback helps us improve.
            </p>
          </CardHeader>

          <CardContent className="space-y-7">
            <div className="space-y-3 text-center">
              <div className="flex justify-center gap-2">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setRating(n)}
                    onMouseEnter={() => setHover(n)}
                    onMouseLeave={() => setHover(0)}
                    className="transition-transform hover:scale-125 active:scale-110"
                    aria-label={`${n} star${n === 1 ? "" : "s"}`}
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
                <p
                  className="text-sm font-semibold transition-all"
                  style={{ color: STAR_COLORS[hover || rating] }}
                >
                  {STAR_LABELS[hover || rating]}
                </p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="csat-comment" className="text-xs font-semibold uppercase tracking-widest text-slate-400">
                Additional comments <span className="font-normal normal-case text-slate-500">(optional)</span>
              </Label>
              <Textarea
                id="csat-comment"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                rows={3}
                placeholder="Tell us more about your experience…"
                className="border-white/10 bg-white/5 text-slate-200 placeholder:text-slate-500 focus-visible:ring-violet-500"
              />
            </div>

            <Button
              onClick={() => {
                if (!rating) {
                  toast.error("Please select a rating.");
                  return;
                }
                submit.mutate();
              }}
              disabled={submit.isPending || !rating}
              className={clsx(
                "h-12 w-full rounded-xl text-base font-bold text-white transition-all",
                rating
                  ? "bg-gradient-to-r from-violet-600 to-blue-600 shadow-lg shadow-violet-500/30 hover:from-violet-500 hover:to-blue-500 hover:shadow-xl"
                  : "cursor-not-allowed bg-white/5",
              )}
            >
              {submit.isPending ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <>
                  <Send className="mr-2 h-4 w-4" /> Submit feedback
                </>
              )}
            </Button>
          </CardContent>
        </Card>

        {info?.expires_at && (
          <p className="flex items-center justify-center gap-1 text-center text-xs text-slate-500">
            <Clock className="h-3 w-3" />
            Link expires{" "}
            {new Date(info.expires_at).toLocaleDateString("en-IN", {
              day: "2-digit",
              month: "short",
              year: "numeric",
            })}
          </p>
        )}
      </div>
    </div>
  );
}
