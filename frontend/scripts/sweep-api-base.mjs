/**
 * Codemod: replace copy-pasted API_BASE/CRM_BASE declarations with
 * imports from @/lib/api across the entire frontend/src tree.
 *
 * Run: node frontend/scripts/sweep-api-base.mjs
 */

import { readFileSync, writeFileSync, readdirSync, statSync } from "fs";
import { join, extname } from "path";
import { fileURLToPath } from "url";

const ROOT = join(fileURLToPath(import.meta.url), "../../src");

const API_BASE_DECL =
  `const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? \`\${window.location.protocol}//\${window.location.host}\` : \`\${window.location.protocol}//127.0.0.1:6060\`) : "http://127.0.0.1:6060");`;

const CRM_BASE_DECL = `const CRM_BASE = \`\${API_BASE}/crm\`;`;

const EXISTING_IMPORT_RE = /^import\s+\{([^}]+)\}\s+from\s+"@\/lib\/api";/m;

function walk(dir, files = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      walk(full, files);
    } else if ([".ts", ".tsx"].includes(extname(entry))) {
      files.push(full);
    }
  }
  return files;
}

let changed = 0;
let skipped = 0;

for (const file of walk(ROOT)) {
  let src = readFileSync(file, "utf8");

  if (!src.includes(API_BASE_DECL)) { skipped++; continue; }

  const usesCRM = src.includes("CRM_BASE");
  const usesAPI = src.includes("API_BASE");

  src = src.replace(API_BASE_DECL + "\n", "").replace(API_BASE_DECL, "");
  src = src.replace(CRM_BASE_DECL + "\n", "").replace(CRM_BASE_DECL, "");
  src = src.replace(/\n{3,}/g, "\n\n");

  const names = [];
  if (usesAPI) names.push("API_BASE");
  if (usesCRM) names.push("CRM_BASE");

  if (names.length === 0) {
    writeFileSync(file, src);
    changed++;
    console.log("✓ (decl removed, no usage)", file.replace(ROOT, "").replace(/\\/g, "/"));
    continue;
  }

  const importLine = `import { ${names.join(", ")} } from "@/lib/api";`;
  const existingMatch = EXISTING_IMPORT_RE.exec(src);

  if (existingMatch) {
    const existingNames = existingMatch[1]
      .split(",")
      .map(s => s.trim())
      .filter(Boolean);
    const merged = [...new Set([...existingNames, ...names])].sort();
    src = src.replace(existingMatch[0], `import { ${merged.join(", ")} } from "@/lib/api";`);
  } else {
    const allImports = [...src.matchAll(/^import\s+.+$/gm)];
    const lastImport = allImports.at(-1);
    if (lastImport) {
      const insertAt = lastImport.index + lastImport[0].length;
      src = src.slice(0, insertAt) + "\n" + importLine + src.slice(insertAt);
    } else {
      src = importLine + "\n" + src;
    }
  }

  writeFileSync(file, src);
  changed++;
  console.log("✓", file.replace(ROOT, "").replace(/\\/g, "/"));
}

console.log(`\nDone: ${changed} files updated, ${skipped} skipped.`);
