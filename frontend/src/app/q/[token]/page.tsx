"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  BadgePercent,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  FileText,
  Loader2,
  MessageSquare,
  Package,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

type QuoteInfo = {
  id: number;
  quote_number: string;
  status: string;
  currency: string;
  total_amount: string;
  valid_until: string | null;
  tracking_token: string;
  notes: string | null;
  lead_name: string | null;
  lead_email: string | null;
  lead_phone: string | null;
};

type QuoteItem = {
  id: number;
  product_name: string;
  sku: string | null;
  quantity: number;
  unit_price: string;
  discount_percent: string;
  line_total: string;
  notes: string | null;
};

type TimelineEntry = { label: string; timestamp: string };

type QuotePayload = { quote: QuoteInfo; items: QuoteItem[]; timeline: TimelineEntry[] };

const fmt = (v: string, currency: string) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 2 }).format(Number(v));

const fmtDate = (v: string | null) =>
  v ? new Date(v).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—";

const STATUS_META: Record<string, { label: string; tone: "default" | "secondary" | "destructive" | "outline" }> = {
  draft:       { label: "Draft",       tone: "secondary" },
  pending:     { label: "Pending",     tone: "outline" },
  sent:        { label: "Sent",        tone: "default" },
  accepted:    { label: "Accepted",    tone: "default" },
  rejected:    { label: "Declined",    tone: "destructive" },
  negotiation: { label: "In Review",   tone: "secondary" },
  expired:     { label: "Expired",     tone: "outline" },
};

export default function PublicQuotePage() {
  const params = useParams();
  const token = params?.token as string;
  const qc = useQueryClient();

  const [acting, setActing] = useState<"accept" | "reject" | "negotiate" | null>(null);
  const [done, setDone] = useState<"accepted" | "rejected" | "negotiation" | null>(null);

  const [showNegotiate, setShowNegotiate] = useState(false);
  const [negMessage, setNegMessage] = useState("");
  const [negDiscount, setNegDiscount] = useState("");
  const [showTimeline, setShowTimeline] = useState(false);

  const query = useQuery<QuotePayload>({
    queryKey: ["public-quote", token],
    enabled: !!token,
    retry: false,
    queryFn: async () => {
      const r = await fetch(`${API_BASE}/tracking/quote/info/${token}`);
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || "Could not load quote");
      }
      return r.json();
    },
  });

  const acceptMut = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${API_BASE}/tracking/quote/accept/${token}`, { method: "POST" });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "Failed");
      return r.json();
    },
    onSuccess: () => {
      toast.success("Quote accepted");
      setDone("accepted");
      qc.invalidateQueries({ queryKey: ["public-quote", token] });
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Failed"),
  });

  const rejectMut = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${API_BASE}/tracking/quote/reject/${token}`, { method: "POST" });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "Failed");
      return r.json();
    },
    onSuccess: () => {
      toast.success("Quote declined");
      setDone("rejected");
      qc.invalidateQueries({ queryKey: ["public-quote", token] });
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Failed"),
  });

  const negotiateMut = useMutation({
    mutationFn: async () => {
      if (!negMessage.trim()) throw new Error("Please describe what you'd like changed.");
      const r = await fetch(`${API_BASE}/tracking/quote/negotiate/${token}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: negMessage.trim(),
          requested_discount: negDiscount ? Number(negDiscount) : null,
        }),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "Failed");
      return r.json();
    },
    onSuccess: () => {
      toast.success("Request sent");
      setDone("negotiation");
      qc.invalidateQueries({ queryKey: ["public-quote", token] });
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Failed"),
  });

  const quote = query.data?.quote;
  const items = query.data?.items ?? [];
  const timeline = query.data?.timeline ?? [];
  const statusMeta = quote ? (STATUS_META[quote.status] ?? STATUS_META.pending) : null;
  const isClosed = !!done || (quote && ["accepted", "rejected", "negotiation"].includes(quote.status));

  if (query.isLoading) {
    return (
      <div className="flex min-h-screen w-full items-center justify-center bg-slate-50 dark:bg-slate-950">
        <Loader2 className="h-8 w-8 animate-spin text-violet-500" />
      </div>
    );
  }

  if (query.error && !quote) {
    return (
      <div className="flex min-h-screen w-full items-center justify-center bg-slate-50 p-4 dark:bg-slate-950">
        <Card className="w-full max-w-sm text-center">
          <CardContent className="space-y-3 pt-8">
            <AlertCircle className="mx-auto h-10 w-10 text-red-400" />
            <p className="font-medium text-slate-700 dark:text-slate-200">
              {query.error instanceof Error ? query.error.message : "Could not load quote"}
            </p>
            <p className="text-sm text-slate-500 dark:text-slate-400">This quote link may have expired or is invalid.</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!quote) return null;

  if (done === "accepted") {
    return (
      <DoneScreen
        icon={<CheckCircle2 className="h-16 w-16 text-emerald-500" />}
        title="Quote Accepted!"
        message={`Thank you, ${quote.lead_name ?? "there"}. We've received your acceptance of ${quote.quote_number}. Our team will be in touch shortly.`}
      />
    );
  }
  if (done === "rejected") {
    return (
      <DoneScreen
        icon={<XCircle className="h-16 w-16 text-red-400" />}
        title="Quote Declined"
        message="We understand. If you'd like to revisit this or discuss alternatives, please reach out to us directly."
      />
    );
  }
  if (done === "negotiation") {
    return (
      <DoneScreen
        icon={<MessageSquare className="h-16 w-16 text-violet-500" />}
        title="Request Sent!"
        message="Your message has been sent to our team. We'll review your request and get back to you soon."
      />
    );
  }

  return (
    <div className="min-h-screen w-full bg-slate-50 px-4 py-10 dark:bg-slate-950">
      <div className="mx-auto max-w-2xl space-y-5">
        <Card className="overflow-hidden border-slate-200 dark:border-white/10">
          <div className="bg-gradient-to-r from-slate-800 to-slate-700 px-6 py-5 text-white dark:from-slate-900 dark:to-slate-800">
            <p className="mb-1 text-xs font-semibold uppercase tracking-widest text-slate-400">Quotation</p>
            <h1 className="text-2xl font-bold">{quote.quote_number}</h1>
            {quote.lead_name && <p className="mt-0.5 text-sm text-slate-300">Prepared for {quote.lead_name}</p>}
          </div>
          <CardContent className="flex flex-wrap gap-6 pt-4 text-sm">
            <div>
              <p className="mb-0.5 text-[10px] uppercase tracking-widest text-slate-500 dark:text-slate-400">Status</p>
              <Badge variant={statusMeta?.tone ?? "secondary"}>{statusMeta?.label}</Badge>
            </div>
            <div>
              <p className="mb-0.5 text-[10px] uppercase tracking-widest text-slate-500 dark:text-slate-400">Total</p>
              <p className="text-lg font-bold text-slate-900 dark:text-white">{fmt(quote.total_amount, quote.currency)}</p>
            </div>
            {quote.valid_until && (
              <div>
                <p className="mb-0.5 text-[10px] uppercase tracking-widest text-slate-500 dark:text-slate-400">Valid Until</p>
                <p className="flex items-center gap-1 font-medium text-slate-700 dark:text-slate-200">
                  <Clock className="h-3.5 w-3.5 text-amber-500" />
                  {fmtDate(quote.valid_until)}
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        {items.length > 0 && (
          <Card className="overflow-hidden border-slate-200 dark:border-white/10">
            <div className="flex items-center gap-2 border-b border-slate-200 px-6 py-4 dark:border-white/10">
              <Package className="h-4 w-4 text-violet-500" />
              <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">Items</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-50 text-[10px] uppercase tracking-widest text-slate-500 dark:bg-white/5 dark:text-slate-400">
                    <th className="px-5 py-2.5 text-left">Product</th>
                    <th className="px-4 py-2.5 text-right">Qty</th>
                    <th className="px-4 py-2.5 text-right">Unit Price</th>
                    <th className="px-4 py-2.5 text-right">Discount</th>
                    <th className="px-5 py-2.5 text-right">Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-white/10">
                  {items.map((it) => (
                    <tr key={it.id} className="hover:bg-slate-50 dark:hover:bg-white/5">
                      <td className="px-5 py-3">
                        <p className="font-medium text-slate-800 dark:text-slate-100">{it.product_name}</p>
                        {it.sku && <p className="mt-0.5 text-[10px] text-slate-500 dark:text-slate-400">SKU: {it.sku}</p>}
                        {it.notes && <p className="mt-0.5 text-xs italic text-slate-500 dark:text-slate-400">{it.notes}</p>}
                      </td>
                      <td className="px-4 py-3 text-right text-slate-600 dark:text-slate-300">{it.quantity}</td>
                      <td className="px-4 py-3 text-right text-slate-600 dark:text-slate-300">{fmt(it.unit_price, quote.currency)}</td>
                      <td className="px-4 py-3 text-right">
                        {Number(it.discount_percent) > 0 ? (
                          <span className="inline-flex items-center gap-1 font-medium text-emerald-600 dark:text-emerald-400">
                            <BadgePercent className="h-3 w-3" />
                            {it.discount_percent}%
                          </span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                      <td className="px-5 py-3 text-right font-semibold text-slate-900 dark:text-slate-100">
                        {fmt(it.line_total, quote.currency)}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t border-slate-200 bg-slate-50 dark:border-white/10 dark:bg-white/5">
                    <td colSpan={4} className="px-5 py-3 text-right text-sm font-semibold text-slate-600 dark:text-slate-300">
                      Total
                    </td>
                    <td className="px-5 py-3 text-right text-base font-bold text-slate-900 dark:text-white">
                      {fmt(quote.total_amount, quote.currency)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </Card>
        )}

        {quote.notes && (
          <Card className="border-slate-200 dark:border-white/10">
            <CardContent className="pt-4">
              <div className="mb-2 flex items-center gap-2">
                <FileText className="h-4 w-4 text-slate-500 dark:text-slate-400" />
                <p className="text-sm font-semibold text-slate-600 dark:text-slate-300">Notes</p>
              </div>
              <p className="whitespace-pre-wrap text-sm text-slate-600 dark:text-slate-300">{quote.notes}</p>
            </CardContent>
          </Card>
        )}

        {quote.status === "accepted" && !done && (
          <StatusBanner
            tone="emerald"
            icon={<CheckCircle2 className="h-6 w-6 text-emerald-500" />}
            text="You've already accepted this quote. Our team will be in touch."
          />
        )}
        {quote.status === "rejected" && !done && (
          <StatusBanner
            tone="red"
            icon={<XCircle className="h-6 w-6 text-red-400" />}
            text="This quote was declined. Contact us if you'd like to discuss further."
          />
        )}
        {quote.status === "negotiation" && !done && (
          <StatusBanner
            tone="violet"
            icon={<MessageSquare className="h-6 w-6 text-violet-500" />}
            text="Your change request is being reviewed. We'll update you soon."
          />
        )}

        {!isClosed && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Button
                onClick={() => { setActing("accept"); acceptMut.mutate(undefined, { onSettled: () => setActing(null) }); }}
                disabled={!!acting}
                className="h-14 rounded-2xl bg-emerald-500 text-sm font-semibold hover:bg-emerald-600"
              >
                {acting === "accept" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
                Accept Quote
              </Button>
              <Button
                variant="outline"
                onClick={() => { setActing("reject"); rejectMut.mutate(undefined, { onSettled: () => setActing(null) }); }}
                disabled={!!acting}
                className="h-14 rounded-2xl border-red-200 text-sm font-semibold text-red-600 hover:bg-red-50 dark:border-red-500/30 dark:text-red-300 dark:hover:bg-red-500/10"
              >
                {acting === "reject" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <XCircle className="mr-2 h-4 w-4" />}
                Decline
              </Button>
            </div>

            <Button
              variant="outline"
              onClick={() => setShowNegotiate((v) => !v)}
              className="h-14 w-full justify-between rounded-2xl border-violet-200 text-sm font-semibold text-violet-700 hover:bg-violet-50 dark:border-violet-500/30 dark:text-violet-300 dark:hover:bg-violet-500/10"
            >
              <span className="flex items-center gap-2">
                <MessageSquare className="h-4 w-4" />
                Request Changes or Discount
              </span>
              {showNegotiate ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </Button>

            {showNegotiate && (
              <Card className="border-violet-200 dark:border-violet-500/30">
                <CardContent className="space-y-4 pt-5">
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    Tell us what you&apos;d like changed — a discount, removal of an item, a revised quantity, or anything else. Our team will review and send a revised quote.
                  </p>

                  <div className="space-y-1.5">
                    <Label htmlFor="neg-message" className="text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
                      Your message <span className="text-red-400">*</span>
                    </Label>
                    <Textarea
                      id="neg-message"
                      value={negMessage}
                      onChange={(e) => setNegMessage(e.target.value)}
                      placeholder="e.g. Can you offer a 10% discount on the total? Or remove item 2 from the list."
                      rows={4}
                    />
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="neg-discount" className="text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
                      Requested discount % <span className="font-normal normal-case text-slate-400">(optional)</span>
                    </Label>
                    <div className="relative max-w-[160px]">
                      <Input
                        id="neg-discount"
                        type="number"
                        min="0"
                        max="100"
                        step="0.5"
                        value={negDiscount}
                        onChange={(e) => setNegDiscount(e.target.value)}
                        placeholder="e.g. 15"
                        className="pr-8"
                      />
                      <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-slate-400">%</span>
                    </div>
                  </div>

                  <Button
                    onClick={() => { setActing("negotiate"); negotiateMut.mutate(undefined, { onSettled: () => setActing(null) }); }}
                    disabled={!!acting}
                    className="bg-violet-600 hover:bg-violet-700"
                  >
                    {acting === "negotiate" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <MessageSquare className="mr-2 h-4 w-4" />}
                    Send Request
                  </Button>
                </CardContent>
              </Card>
            )}
          </div>
        )}

        {timeline.length > 0 && (
          <Card className="overflow-hidden border-slate-200 dark:border-white/10">
            <button
              onClick={() => setShowTimeline((v) => !v)}
              className="flex w-full items-center justify-between px-6 py-4 text-sm font-semibold text-slate-600 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-white/5"
              type="button"
            >
              <span>Quote Timeline</span>
              {showTimeline ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>
            {showTimeline && (
              <div className="space-y-3 border-t border-slate-200 px-6 pb-5 pt-4 dark:border-white/10">
                {timeline.map((t, i) => (
                  <div key={i} className="flex items-start gap-3">
                    <span className="mt-1.5 h-2 w-2 flex-shrink-0 rounded-full bg-violet-400" />
                    <div>
                      <p className="text-sm font-medium text-slate-700 dark:text-slate-200">{t.label}</p>
                      <p className="text-[11px] text-slate-500 dark:text-slate-400">{new Date(t.timestamp).toLocaleString("en-IN")}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        )}

        <p className="pb-4 text-center text-[11px] text-slate-500 dark:text-slate-500">
          Powered by Rio CRM · This quote was prepared specifically for {quote.lead_name ?? "you"}
        </p>
      </div>
    </div>
  );
}

function DoneScreen({ icon, title, message }: { icon: React.ReactNode; title: string; message: string }) {
  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-slate-50 p-4 dark:bg-slate-950">
      <div className="w-full max-w-sm space-y-4 p-8 text-center">
        <div className="mx-auto">{icon}</div>
        <h2 className="text-2xl font-bold text-slate-800 dark:text-white">{title}</h2>
        <p className="text-slate-600 dark:text-slate-300">{message}</p>
      </div>
    </div>
  );
}

function StatusBanner({ tone, icon, text }: { tone: "emerald" | "red" | "violet"; icon: React.ReactNode; text: string }) {
  const cls =
    tone === "emerald"
      ? "bg-emerald-50 border-emerald-200 text-emerald-800 dark:bg-emerald-500/10 dark:border-emerald-500/30 dark:text-emerald-200"
      : tone === "red"
      ? "bg-red-50 border-red-200 text-red-800 dark:bg-red-500/10 dark:border-red-500/30 dark:text-red-200"
      : "bg-violet-50 border-violet-200 text-violet-800 dark:bg-violet-500/10 dark:border-violet-500/30 dark:text-violet-200";
  return (
    <div className={`flex items-center gap-3 rounded-2xl border px-6 py-5 ${cls}`}>
      {icon}
      <p className="text-sm font-medium">{text}</p>
    </div>
  );
}
