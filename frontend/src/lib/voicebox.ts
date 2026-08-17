const VOICEBOX_URL =
  process.env.NEXT_PUBLIC_VOICEBOX_URL || "http://127.0.0.1:17493";

const VOICEBOX_CLIENT_ID = "rio-crm-web";

type VoiceboxRequest = {
  text: string;
  profile?: string;
};

async function voiceboxFetch(path: string, init?: RequestInit) {
  return fetch(`${VOICEBOX_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Voicebox-Client-Id": VOICEBOX_CLIENT_ID,
      ...(init?.headers || {}),
    },
  });
}

export async function isVoiceboxAvailable(): Promise<boolean> {
  try {
    const response = await voiceboxFetch("/health", { method: "GET" });
    return response.ok;
  } catch {
    return false;
  }
}

export async function speakWithVoicebox(request: VoiceboxRequest): Promise<void> {
  const response = await voiceboxFetch("/speak", {
    method: "POST",
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(`Voicebox returned HTTP ${response.status}`);
  }
}
