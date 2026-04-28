/**
 * Cookie-aware fetch wrapper with automatic CSRF handling.
 *
 * Use this in place of the raw `fetch()` for any request that should be
 * authenticated by the session cookie. On state-changing methods (POST / PUT /
 * PATCH / DELETE), it reads the `rio_csrf` cookie and echoes it back in the
 * `X-CSRF-Token` header — the double-submit pattern the backend middleware
 * enforces.
 *
 * The backend sets `rio_csrf` alongside the session cookie on every successful
 * login / register, so once a user is authenticated the CSRF cookie is always
 * present. If it's missing (e.g. session expired mid-flight) the request will
 * still go through with no header — the backend returns 403 and the UI can
 * treat that as "reauthenticate."
 *
 * Bearer-header clients (legacy fetches that don't send credentials) are not
 * affected: the backend's CSRF middleware only enforces when a session cookie
 * is present on the request.
 */

const CSRF_COOKIE = "rio_csrf";
const CSRF_HEADER = "X-CSRF-Token";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

/** Read a cookie by name. Returns null in SSR / if not present. */
export function readCookie(name: string): string | null {
    if (typeof document === "undefined") return null;
    // Escape regex special chars in the cookie name just in case
    const safe = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = document.cookie.match(new RegExp("(^|;\\s*)" + safe + "=([^;]+)"));
    return match ? decodeURIComponent(match[2]) : null;
}

export function getCsrfToken(): string | null {
    return readCookie(CSRF_COOKIE);
}

/**
 * Fetch wrapper that:
 *   1. Always sends cookies (`credentials: "include"`).
 *   2. Adds the CSRF header on state-changing methods when a CSRF cookie is present.
 *   3. Preserves any headers / body the caller passes through `init`.
 *
 * Identical signature to the global `fetch` so it's a drop-in replacement.
 */
export async function apiFetch(
    input: RequestInfo | URL,
    init: RequestInit = {},
): Promise<Response> {
    const method = (init.method || "GET").toUpperCase();
    const headers = new Headers(init.headers);

    if (!SAFE_METHODS.has(method)) {
        const csrf = getCsrfToken();
        if (csrf && !headers.has(CSRF_HEADER)) {
            headers.set(CSRF_HEADER, csrf);
        }
    }

    // Auto-set Content-Type: application/json when the body is a string and no
    // Content-Type is already set. FormData / Blob / URLSearchParams bodies are
    // not strings, so they pass through with the browser's defaults.
    if (typeof init.body === "string" && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
    }

    return fetch(input, {
        ...init,
        credentials: "include",
        headers,
    });
}
