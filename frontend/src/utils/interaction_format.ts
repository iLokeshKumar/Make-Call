type Recommendations = {
  next_action?: string;
  suggested_product?: string;
  follow_up_days?: number;
};

type Insights = {
  pain_points?: string[];
  buying_signals?: string[];
  objections_raised?: string[];
  questions_asked?: string[];
  [key: string]: unknown;
};

type Bant = {
  budget?: string;
  authority?: string;
  need?: string;
  timeline?: string;
  [key: string]: unknown;
};

export type ParsedInteractionContent = {
  metadata?: {
    lead_id?: number;
    call_type?: string;
    call_date?: string;
    transcript_preview?: string;
    interaction_id?: number;
    [key: string]: unknown;
  };
  qualification?: {
    icp_score?: number;
    sentiment?: string;
    qualified?: boolean;
    confidence?: string;
    pain_points?: string[];
    buying_signals?: string[];
    objections_raised?: string[];
    questions_asked?: string[];
    insights?: Insights;
    recommendations?: Recommendations;
    [key: string]: unknown;
  };
  bant?: Bant;
  insights?: Insights;
  recommendations?: Recommendations;
  [key: string]: unknown;
};

type InteractionLike = {
  id?: number;
  type?: string | null;
  content?: string | null;
  started_at?: string | null;
  created_at?: string | null;
};

export function tryParseInteractionContent(
  content: string | null | undefined,
): ParsedInteractionContent | null {
  if (!content) return null;
  const trimmed = content.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return null;
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as ParsedInteractionContent;
    }
    return null;
  } catch {
    return null;
  }
}

function humanizeAction(raw: string): string {
  return raw.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function pickInsights(parsed: ParsedInteractionContent): Insights {
  const top = parsed.insights ?? {};
  const nested = parsed.qualification?.insights ?? {};
  const legacy = parsed.qualification ?? {};
  return {
    pain_points: (top.pain_points ?? nested.pain_points ?? legacy.pain_points ?? []) as string[],
    buying_signals: (top.buying_signals ?? nested.buying_signals ?? legacy.buying_signals ?? []) as string[],
    objections_raised: (top.objections_raised ?? nested.objections_raised ?? legacy.objections_raised ?? []) as string[],
    questions_asked: (top.questions_asked ?? nested.questions_asked ?? legacy.questions_asked ?? []) as string[],
  };
}

function pickRecommendations(parsed: ParsedInteractionContent): Recommendations | null {
  const rec = parsed.recommendations ?? parsed.qualification?.recommendations;
  if (!rec || !rec.next_action) return null;
  return rec;
}

export function formatInteractionSubtitle(
  type: string | null | undefined,
  content: string | null | undefined,
): string | null {
  if (!content) return null;
  const parsed = tryParseInteractionContent(content);
  if (!parsed) return content;

  const parts: string[] = [];
  const preview = parsed.metadata?.transcript_preview;
  if (preview && typeof preview === "string" && preview.trim()) {
    const cleaned = preview.trim();
    parts.push(cleaned.length > 220 ? `${cleaned.slice(0, 220)}…` : cleaned);
  }

  const qual = parsed.qualification;
  if (qual) {
    const tags: string[] = [];
    if (typeof qual.qualified === "boolean") {
      tags.push(qual.qualified ? "Qualified" : "Not qualified");
    }
    if (qual.sentiment) tags.push(`sentiment: ${qual.sentiment}`);
    if (qual.confidence) tags.push(`confidence: ${qual.confidence}`);
    if (typeof qual.icp_score === "number") {
      tags.push(`ICP: ${Math.round(qual.icp_score * 100)}`);
    }
    if (tags.length) parts.push(tags.join("  •  "));
  }

  const insights = pickInsights(parsed);
  const pain = (insights.pain_points ?? []).filter(Boolean);
  const signals = (insights.buying_signals ?? []).filter(Boolean);
  const objections = (insights.objections_raised ?? []).filter(Boolean);
  if (pain.length) parts.push(`Pain: ${pain.join(", ")}`);
  if (signals.length) parts.push(`Buying signals: ${signals.join(", ")}`);
  if (objections.length) parts.push(`Objections: ${objections.join(", ")}`);

  const rec = pickRecommendations(parsed);
  if (rec) {
    const bits = [`Next: ${humanizeAction(rec.next_action!)}`];
    if (rec.suggested_product) bits.push(`→ ${rec.suggested_product}`);
    if (typeof rec.follow_up_days === "number" && rec.follow_up_days > 0) {
      bits.push(`in ${rec.follow_up_days}d`);
    }
    parts.push(bits.join(" "));
  }

  if (!parts.length) return content;
  return parts.join("\n");
}

export function humanizeInteractionTitle(
  type: string | null | undefined,
  status: string | null | undefined,
): string {
  const t = (type || "Interaction").replace(/_/g, " ");
  const s = (status || "logged").toLowerCase();
  return `${t.replace(/\b\w/g, (c) => c.toUpperCase())} ${s}`;
}

export type ExtractedQualification = {
  pain_points: string[];
  buying_signals: string[];
  objections_raised: string[];
  questions_asked: string[];
  icp_score?: number;
  sentiment?: string;
  qualified?: boolean;
  confidence?: string;
  bant?: Bant;
  recommendations?: Recommendations;
};

export function extractLatestQualification(
  interactions: InteractionLike[],
): ExtractedQualification | null {
  const scored = interactions
    .filter((i) => (i.type || "").toLowerCase().includes("call_summary") && i.content)
    .map((i) => ({
      when: new Date(i.started_at || i.created_at || 0).getTime(),
      parsed: tryParseInteractionContent(i.content),
    }))
    .filter((x) => x.parsed)
    .sort((a, b) => b.when - a.when);
  const latest = scored[0]?.parsed;
  if (!latest) return null;
  const insights = pickInsights(latest);
  const rec = pickRecommendations(latest);
  const q = latest.qualification ?? {};
  return {
    pain_points: (insights.pain_points ?? []) as string[],
    buying_signals: (insights.buying_signals ?? []) as string[],
    objections_raised: (insights.objections_raised ?? []) as string[],
    questions_asked: (insights.questions_asked ?? []) as string[],
    icp_score: q.icp_score,
    sentiment: q.sentiment,
    qualified: q.qualified,
    confidence: q.confidence,
    bant: latest.bant,
    recommendations: rec ?? undefined,
  };
}

export function extractLatestRecommendation(
  interactions: InteractionLike[],
): { next_action?: string; suggested_product?: string; follow_up_days?: number } | null {
  const qual = extractLatestQualification(interactions);
  const rec = qual?.recommendations;
  if (!rec || !rec.next_action) return null;
  return {
    next_action: rec.next_action,
    suggested_product: rec.suggested_product,
    follow_up_days: rec.follow_up_days,
  };
}

export function formatNextActionLabel(action: string): string {
  return humanizeAction(action);
}
