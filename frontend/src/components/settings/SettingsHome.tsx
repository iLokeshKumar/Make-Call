"use client";
import { useRef, useEffect, useState } from "react";
import { Search, Mic, MicOff, Clock, X, Lock } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import SettingsCard, { SectionDef } from "./SettingsCard";
import { RecentItem } from "@/hooks/useRecentlyViewed";
import { useVoiceSearch } from "@/hooks/useVoiceSearch";
import clsx from "clsx";

type Group = { id: string; label: string; adminOnly?: boolean };

const GROUPS: Group[] = [
  { id: "account", label: "Your Account" },
  { id: "company", label: "Company", adminOnly: true },
  { id: "integrations", label: "Integrations", adminOnly: true },
  { id: "operations", label: "Operations", adminOnly: true },
];

type Props = {
  sections: SectionDef[];
  recentItems: RecentItem[];
  pinnedIds: string[];
  hasAdminAccess: boolean;
  onNavigate: (id: string) => void;
  onTogglePin: (id: string) => void;
  onClearRecent: () => void;
};

export default function SettingsHome({
  sections,
  recentItems,
  pinnedIds,
  hasAdminAccess,
  onNavigate,
  onTogglePin,
  onClearRecent,
}: Props) {
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  const { listening, supported, toggle } = useVoiceSearch((text) => {
    setQuery(text);
    searchRef.current?.focus();
  });

  // ⌘K to focus search
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const q = query.toLowerCase().trim();
  const filtered = q
    ? sections.filter(
        (s) =>
          s.label.toLowerCase().includes(q) ||
          s.description.toLowerCase().includes(q)
      )
    : null;

  const pinnedSections = pinnedIds
    .map((id) => sections.find((s) => s.id === id))
    .filter(Boolean) as SectionDef[];

  return (
    <div className="space-y-8">
      {/* Hero Search */}
      <div className="relative">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400 pointer-events-none" />
        <Input
          ref={searchRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search settings…"
          className={clsx(
            "pl-11 pr-24 h-12 text-sm rounded-2xl",
            "bg-white/80 dark:bg-slate-800/60 backdrop-blur-md",
            "border-slate-200/80 dark:border-white/10",
            "focus-visible:ring-violet-500/50 focus-visible:border-violet-400",
            listening && "border-violet-500 ring-2 ring-violet-500/30 animate-pulse"
          )}
        />
        <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-1.5">
          {query && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-slate-400"
              onClick={() => setQuery("")}
            >
              <X size={14} />
            </Button>
          )}
          {supported && (
            <Button
              variant="ghost"
              size="icon"
              onClick={toggle}
              className={clsx(
                "h-7 w-7 transition-colors",
                listening
                  ? "text-violet-600 dark:text-violet-400"
                  : "text-slate-400 hover:text-violet-500"
              )}
              title={listening ? "Stop listening" : "Voice search"}
            >
              {listening ? <MicOff size={15} /> : <Mic size={15} />}
            </Button>
          )}
          {!query && (
            <kbd className="hidden sm:inline-flex h-5 select-none items-center gap-0.5 rounded border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 px-1.5 text-[10px] font-mono font-medium text-slate-500">
              ⌘K
            </kbd>
          )}
        </div>
      </div>

      {/* Search results */}
      {filtered && (
        <div>
          {filtered.length === 0 ? (
            <p className="text-sm text-slate-500 dark:text-slate-400 text-center py-8">
              No settings match &ldquo;{query}&rdquo;
            </p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
              {filtered.map((s) => (
                <SettingsCard
                  key={s.id}
                  section={s}
                  pinned={pinnedIds.includes(s.id)}
                  onClick={() => onNavigate(s.id)}
                  onTogglePin={onTogglePin}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {!filtered && (
        <>
          {/* Recently Viewed */}
          {recentItems.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-3">
                <h2 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
                  <Clock size={12} /> Recently Viewed
                </h2>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 text-[11px] text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 px-2"
                  onClick={onClearRecent}
                >
                  Clear
                </Button>
              </div>
              <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-none">
                {recentItems.map((item) => {
                  const sec = sections.find((s) => s.id === item.id);
                  if (!sec) return null;
                  const Icon = sec.icon;
                  return (
                    <button
                      key={item.id}
                      onClick={() => onNavigate(item.id)}
                      className={clsx(
                        "flex items-center gap-2 shrink-0 px-3 py-2 rounded-xl border text-sm font-medium",
                        "bg-white/70 dark:bg-slate-800/60 backdrop-blur-md",
                        "border-slate-200/70 dark:border-white/10",
                        "hover:border-violet-300/60 dark:hover:border-violet-500/30",
                        "hover:shadow-md hover:shadow-violet-500/10",
                        "transition-all duration-200 text-slate-700 dark:text-slate-300"
                      )}
                    >
                      <div
                        className={clsx(
                          "h-6 w-6 rounded-lg flex items-center justify-center bg-gradient-to-br shrink-0",
                          sec.iconGradient
                        )}
                      >
                        <Icon size={12} className="text-white" />
                      </div>
                      {item.label}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Pinned */}
          {pinnedSections.length > 0 && (
            <div>
              <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400 mb-3">
                Pinned
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                {pinnedSections.map((s) => (
                  <SettingsCard
                    key={s.id}
                    section={s}
                    pinned
                    onClick={() => onNavigate(s.id)}
                    onTogglePin={onTogglePin}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Groups */}
          {GROUPS.map((group) => {
            if (group.adminOnly && !hasAdminAccess) return null;
            const groupSections = sections.filter(
              (s) => s.group === group.id && !pinnedIds.includes(s.id)
            );
            if (groupSections.length === 0) return null;
            return (
              <div key={group.id}>
                <div className="flex items-center gap-2 mb-3">
                  <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
                    {group.label}
                  </h2>
                  {group.adminOnly && (
                    <span className="flex items-center gap-1 text-[10px] text-slate-400 dark:text-slate-500">
                      <Lock size={10} /> Admin only
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                  {groupSections.map((s) => (
                    <SettingsCard
                      key={s.id}
                      section={s}
                      pinned={false}
                      onClick={() => onNavigate(s.id)}
                      onTogglePin={onTogglePin}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}
