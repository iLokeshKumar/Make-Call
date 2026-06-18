"use client";
import { useState, useEffect, useRef, useCallback } from "react";

export function useVoiceSearch(onTranscript: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const [supported, setSupported] = useState(false);
  const SRClass = useRef<any>(null);
  const recogRef = useRef<any>(null);
  const callbackRef = useRef(onTranscript);

  callbackRef.current = onTranscript;

  useEffect(() => {
    const SR =
      typeof window !== "undefined"
        ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
        : null;
    SRClass.current = SR;
    setSupported(!!SR);
    return () => {
      recogRef.current?.abort();
      recogRef.current = null;
    };
  }, []);

  const stop = useCallback(() => {
    recogRef.current?.abort();
    recogRef.current = null;
    setListening(false);
  }, []);

  const start = useCallback(() => {
    if (!SRClass.current) return;
    recogRef.current?.abort();
    recogRef.current = null;

    const recog = new SRClass.current();
    recog.continuous = false;
    recog.interimResults = false;
    recog.lang = "en-US";

    recog.onresult = (e: any) => {
      const transcript = e.results[0]?.[0]?.transcript ?? "";
      if (transcript) callbackRef.current(transcript);
    };
    recog.onend = () => {
      recogRef.current = null;
      setListening(false);
    };
    recog.onerror = () => {
      recogRef.current = null;
      setListening(false);
    };

    try {
      recog.start();
      recogRef.current = recog;
      setListening(true);
    } catch {
      setListening(false);
    }
  }, []);

  const toggle = useCallback(() => {
    if (listening) stop();
    else start();
  }, [listening, start, stop]);

  return { listening, supported, toggle, start, stop };
}
