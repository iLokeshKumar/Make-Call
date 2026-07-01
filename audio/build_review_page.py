"""
Build a self-contained local review page for the extracted Aswini clips.

Usage:
  python audio/build_review_page.py

Open the generated HTML in a browser, listen through clips, mark keep/reject,
fix transcripts, then export JSONL/CSV from the page.
"""

from __future__ import annotations

import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INPUT_JSONL = ROOT / "aswini_dataset.local.jsonl"
OUTPUT_HTML = ROOT / "aswini_clip_review.html"


BAD_TEXT_MARKERS = [
    " yes, yes",
    " no, ",
    "no, i",
    "madam, you call",
    "please do send me",
    "pardon",
]


def load_rows() -> list[dict]:
    rows: list[dict] = []
    with INPUT_JSONL.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            path = Path(item["audio_path"])
            try:
                rel_audio = path.resolve().relative_to(ROOT.resolve()).as_posix()
            except ValueError:
                rel_audio = path.as_posix()

            text = item.get("text", "").strip()
            flags = []
            lower_text = text.lower()
            if item.get("duration", 0) < 3:
                flags.append("short")
            if any(marker in lower_text for marker in BAD_TEXT_MARKERS):
                flags.append("check text")
            if len(text.split()) < 4:
                flags.append("few words")

            rows.append(
                {
                    "id": len(rows),
                    "audio_path": item["audio_path"],
                    "audio_src": rel_audio,
                    "source": item.get("source", ""),
                    "start": item.get("start"),
                    "end": item.get("end"),
                    "duration": round(float(item.get("duration", 0)), 3),
                    "text": text,
                    "flags": flags,
                }
            )
    return rows


def build_html(rows: list[dict]) -> str:
    data = json.dumps(rows, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Aswini Clip Review</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f8;
      --panel: #ffffff;
      --text: #182026;
      --muted: #68747f;
      --line: #d8dee4;
      --keep: #0f7b45;
      --reject: #b42318;
      --warn: #8a5a00;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 14px;
      line-height: 1.45;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 2;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 16px;
      align-items: center;
      padding: 14px 18px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.94);
      backdrop-filter: blur(8px);
    }}
    h1 {{
      margin: 0;
      font-size: 18px;
      font-weight: 650;
      letter-spacing: 0;
    }}
    .summary {{
      color: var(--muted);
      margin-top: 2px;
      font-size: 13px;
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 8px;
    }}
    button, select {{
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--text);
      padding: 0 10px;
      font: inherit;
    }}
    button {{
      cursor: pointer;
    }}
    button.primary {{
      border-color: #1f6feb;
      background: #1f6feb;
      color: white;
    }}
    main {{
      display: grid;
      gap: 10px;
      max-width: 1180px;
      margin: 0 auto;
      padding: 14px;
    }}
    .clip {{
      display: grid;
      grid-template-columns: minmax(260px, 360px) 1fr auto;
      gap: 12px;
      align-items: center;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }}
    .clip[data-status="keep"] {{
      border-left: 5px solid var(--keep);
    }}
    .clip[data-status="reject"] {{
      border-left: 5px solid var(--reject);
      opacity: 0.68;
    }}
    .meta {{
      display: flex;
      flex-direction: column;
      gap: 7px;
      min-width: 0;
    }}
    audio {{
      width: 100%;
      height: 34px;
    }}
    .source {{
      color: var(--muted);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 13px;
    }}
    .badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .badge {{
      border-radius: 999px;
      background: #eef2f6;
      color: #43515c;
      padding: 2px 8px;
      font-size: 12px;
    }}
    .badge.warn {{
      background: #fff4d6;
      color: var(--warn);
    }}
    textarea {{
      width: 100%;
      min-height: 58px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      color: var(--text);
      font: inherit;
    }}
    .decision {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      width: 158px;
    }}
    .decision button {{
      padding: 0 8px;
    }}
    .decision .keep.active {{
      border-color: var(--keep);
      background: var(--keep);
      color: white;
    }}
    .decision .reject.active {{
      border-color: var(--reject);
      background: var(--reject);
      color: white;
    }}
    .notes {{
      grid-column: span 2;
    }}
    @media (max-width: 840px) {{
      header {{
        grid-template-columns: 1fr;
      }}
      .actions {{
        justify-content: flex-start;
      }}
      .clip {{
        grid-template-columns: 1fr;
      }}
      .decision {{
        width: 100%;
      }}
      .notes {{
        grid-column: auto;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Aswini Clip Review</h1>
      <div class="summary" id="summary"></div>
    </div>
    <div class="actions">
      <select id="filter">
        <option value="all">All clips</option>
        <option value="unreviewed">Unreviewed</option>
        <option value="keep">Kept</option>
        <option value="reject">Rejected</option>
        <option value="flagged">Flagged</option>
      </select>
      <button type="button" id="exportJsonl" class="primary">Export JSONL</button>
      <button type="button" id="exportCsv">Export CSV</button>
    </div>
  </header>
  <main id="clips"></main>
  <script>
    const rows = {data};
    const storageKey = "aswini-review-v1";
    const state = JSON.parse(localStorage.getItem(storageKey) || "{{}}");
    const clipsEl = document.getElementById("clips");
    const filterEl = document.getElementById("filter");
    const summaryEl = document.getElementById("summary");

    function getReview(id) {{
      return state[id] || {{ status: "unreviewed", text: rows[id].text, notes: "" }};
    }}

    function saveReview(id, patch) {{
      state[id] = {{ ...getReview(id), ...patch }};
      localStorage.setItem(storageKey, JSON.stringify(state));
      render();
    }}

    function escapeCsv(value) {{
      return '"' + String(value ?? "").replaceAll('"', '""') + '"';
    }}

    function keptRows() {{
      return rows
        .map(row => ({{ ...row, review: getReview(row.id) }}))
        .filter(row => row.review.status === "keep")
        .map(row => ({{
          audio_path: row.audio_path,
          text: row.review.text.trim(),
          source: row.source,
          start: row.start,
          end: row.end,
          duration: row.duration,
          notes: row.review.notes || ""
        }}));
    }}

    function download(filename, mime, text) {{
      const blob = new Blob([text], {{ type: mime }});
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    }}

    function render() {{
      const filter = filterEl.value;
      const counts = {{ keep: 0, reject: 0, unreviewed: 0 }};
      rows.forEach(row => counts[getReview(row.id).status]++);
      summaryEl.textContent = `${{rows.length}} clips | ${{counts.keep}} kept | ${{counts.reject}} rejected | ${{counts.unreviewed}} unreviewed`;

      clipsEl.innerHTML = "";
      rows.forEach(row => {{
        const review = getReview(row.id);
        if (filter !== "all") {{
          if (filter === "flagged" && row.flags.length === 0) return;
          if (filter !== "flagged" && review.status !== filter) return;
        }}

        const card = document.createElement("section");
        card.className = "clip";
        card.dataset.status = review.status;
        card.innerHTML = `
          <div class="meta">
            <audio controls preload="none" src="${{row.audio_src}}"></audio>
            <div class="source">#${{String(row.id).padStart(3, "0")}} | ${{row.source}} | ${{row.duration}}s</div>
            <div class="badges">
              ${{row.flags.map(flag => `<span class="badge warn">${{flag}}</span>`).join("")}}
              ${{row.flags.length ? "" : '<span class="badge">no auto flags</span>'}}
            </div>
          </div>
          <textarea aria-label="Transcript">${{review.text}}</textarea>
          <div class="decision">
            <button type="button" class="keep ${{review.status === "keep" ? "active" : ""}}">Keep</button>
            <button type="button" class="reject ${{review.status === "reject" ? "active" : ""}}">Reject</button>
            <textarea class="notes" aria-label="Notes" placeholder="Notes">${{review.notes || ""}}</textarea>
          </div>
        `;

        const transcript = card.querySelector("textarea");
        transcript.addEventListener("change", event => saveReview(row.id, {{ text: event.target.value }}));
        card.querySelector(".notes").addEventListener("change", event => saveReview(row.id, {{ notes: event.target.value }}));
        card.querySelector(".keep").addEventListener("click", () => saveReview(row.id, {{ status: "keep", text: transcript.value }}));
        card.querySelector(".reject").addEventListener("click", () => saveReview(row.id, {{ status: "reject", text: transcript.value }}));
        clipsEl.appendChild(card);
      }});
    }}

    filterEl.addEventListener("change", render);
    document.getElementById("exportJsonl").addEventListener("click", () => {{
      const body = keptRows().map(row => JSON.stringify(row)).join("\\n") + "\\n";
      download("aswini_gold_dataset.jsonl", "application/jsonl", body);
    }});
    document.getElementById("exportCsv").addEventListener("click", () => {{
      const header = ["audio_file", "text", "source", "start", "end", "duration", "notes"];
      const body = keptRows().map(row => [
        row.audio_path, row.text, row.source, row.start, row.end, row.duration, row.notes
      ].map(escapeCsv).join(","));
      download("aswini_gold_metadata.csv", "text/csv", [header.join(","), ...body].join("\\n"));
    }});

    render();
  </script>
</body>
</html>
"""


def main() -> None:
    rows = load_rows()
    OUTPUT_HTML.write_text(build_html(rows), encoding="utf-8")
    flagged = sum(1 for row in rows if row["flags"])
    total_seconds = sum(row["duration"] for row in rows)
    print(f"Wrote {OUTPUT_HTML}")
    print(f"Clips: {len(rows)}")
    print(f"Flagged: {flagged}")
    print(f"Duration: {total_seconds / 60:.2f} minutes")


if __name__ == "__main__":
    main()
