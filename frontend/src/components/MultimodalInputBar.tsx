"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  Plus,
  Mic,
  MicOff,
  Send,
  X,
  FileText,
  Music,
  Image as ImageIcon,
  SplitSquareHorizontal,
  Loader2,
  AlertCircle,
} from "lucide-react";

export interface MultimodalInputBarProps {
  onSendMessage: (params: {
    content: string;
    files: File[];
    forceCompare: boolean;
  }) => Promise<void> | void;
  isLoading: boolean;
  compareMode: boolean;
  onToggleCompareMode: (enabled: boolean) => void;
}

interface PreviewFileItem {
  id: string;
  file: File;
  category: "image" | "document" | "audio";
  previewUrl?: string;
}

// Tipado seguro para Web Speech API en navegadores basados en Chromium/Edge/Safari
interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: {
    length: number;
    [index: number]: {
      isFinal: boolean;
      0: { transcript: string };
    };
  };
}

interface SpeechRecognitionInstance {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onend: (() => void) | null;
}

const ACCEPTED_EXTENSIONS =
  ".png,.jpg,.jpeg,.webp,.pdf,.txt,.csv,.md,.mp3,.wav,.m4a,.ogg";

function getFileCategory(file: File): "image" | "document" | "audio" {
  const ext = file.name.split(".").pop()?.toLowerCase() || "";
  if (["png", "jpg", "jpeg", "webp"].includes(ext) || file.type.startsWith("image/")) {
    return "image";
  }
  if (["mp3", "wav", "m4a", "ogg"].includes(ext) || file.type.startsWith("audio/")) {
    return "audio";
  }
  return "document";
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

export default function MultimodalInputBar({
  onSendMessage,
  isLoading,
  compareMode,
  onToggleCompareMode,
}: MultimodalInputBarProps) {
  const [text, setText] = useState("");
  const [attachedItems, setAttachedItems] = useState<PreviewFileItem[]>([]);
  const [isListening, setIsListening] = useState(false);
  const [interimTranscript, setInterimTranscript] = useState("");
  const [voiceWarning, setVoiceWarning] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null);

  // Limpiar URLs de previsualización al desmontar
  useEffect(() => {
    return () => {
      attachedItems.forEach((item) => {
        if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
      });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-ajuste de altura del textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [text, interimTranscript]);

  const handleFilesSelected = (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return;
    setVoiceWarning(null);

    const newItems: PreviewFileItem[] = [];
    Array.from(fileList).forEach((file) => {
      if (file.size > 25 * 1024 * 1024) {
        setVoiceWarning(`El archivo "${file.name}" supera el límite de 25 MB.`);
        return;
      }
      const category = getFileCategory(file);
      const previewUrl =
        category === "image" ? URL.createObjectURL(file) : undefined;
      newItems.push({
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        file,
        category,
        previewUrl,
      });
    });

    setAttachedItems((prev) => [...prev, ...newItems]);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleRemoveAttachment = (id: string) => {
    setAttachedItems((prev) => {
      const target = prev.find((item) => item.id === id);
      if (target?.previewUrl) {
        URL.revokeObjectURL(target.previewUrl);
      }
      return prev.filter((item) => item.id !== id);
    });
  };

  const toggleVoiceDictation = () => {
    setVoiceWarning(null);

    if (isListening) {
      recognitionRef.current?.stop();
      setIsListening(false);
      setInterimTranscript("");
      return;
    }

    if (typeof window === "undefined") return;
    const SpeechRecognitionConstructor =
      (window as unknown as Record<string, unknown>).SpeechRecognition ||
      (window as unknown as Record<string, unknown>).webkitSpeechRecognition;

    if (!SpeechRecognitionConstructor) {
      setVoiceWarning(
        "Tu navegador no soporta dictado por voz en vivo (Web Speech API). Usa Chrome o Edge."
      );
      return;
    }

    try {
      const recognition = new (SpeechRecognitionConstructor as new () => SpeechRecognitionInstance)();
      recognition.lang = "es-ES";
      recognition.continuous = true;
      recognition.interimResults = true;

      recognition.onresult = (event: SpeechRecognitionEventLike) => {
        let finalChunk = "";
        let interimChunk = "";

        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i];
          const transcriptPiece = result[0]?.transcript || "";
          if (result.isFinal) {
            finalChunk += transcriptPiece + " ";
          } else {
            interimChunk += transcriptPiece;
          }
        }

        if (finalChunk.trim()) {
          setText((prev) => {
            const prefix = prev.trim() ? `${prev.trim()} ` : "";
            return `${prefix}${finalChunk.trim()}`;
          });
        }
        setInterimTranscript(interimChunk);
      };

      recognition.onerror = (event) => {
        if (event.error === "not-allowed") {
          setVoiceWarning(
            "Permiso de micrófono denegado. Habilita el micrófono en la barra de direcciones."
          );
        } else if (event.error && event.error !== "aborted") {
          setVoiceWarning(`Aviso de micrófono: ${event.error}`);
        }
        setIsListening(false);
        setInterimTranscript("");
      };

      recognition.onend = () => {
        setIsListening(false);
        setInterimTranscript("");
      };

      recognitionRef.current = recognition;
      recognition.start();
      setIsListening(true);
    } catch {
      setVoiceWarning("No se pudo iniciar la captura de voz en el navegador.");
      setIsListening(false);
    }
  };

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (isLoading) return;

    const combinedText = [text.trim(), interimTranscript.trim()]
      .filter(Boolean)
      .join(" ")
      .trim();

    if (!combinedText && attachedItems.length === 0) return;

    if (isListening) {
      recognitionRef.current?.stop();
      setIsListening(false);
      setInterimTranscript("");
    }

    const filesToSend = attachedItems.map((item) => item.file);
    const currentForceCompare = compareMode;

    setText("");
    setInterimTranscript("");
    setAttachedItems([]);

    await onSendMessage({
      content: combinedText,
      files: filesToSend,
      forceCompare: currentForceCompare,
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSubmit();
    }
  };

  const displayedText = interimTranscript
    ? `${text}${text && !text.endsWith(" ") ? " " : ""}${interimTranscript}`
    : text;

  const canSend =
    !isLoading && (displayedText.trim().length > 0 || attachedItems.length > 0);

  return (
    <div className="w-full max-w-4xl mx-auto px-3 sm:px-6 pb-4 pt-2">
      {/* Aviso de voz o validación de archivos */}
      {voiceWarning && (
        <div className="mb-2 flex items-center justify-between gap-2 px-3.5 py-2 rounded-xl bg-amber-500/15 border border-amber-500/40 text-amber-200 text-xs">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0 text-amber-400" />
            <span>{voiceWarning}</span>
          </div>
          <button
            type="button"
            onClick={() => setVoiceWarning(null)}
            className="text-amber-300 hover:text-white"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Contenedor estilo cápsula de Google Gemini (#1e1f20) */}
      <form
        onSubmit={handleSubmit}
        className={`rounded-3xl bg-[#1e1f20] border transition-all shadow-lg ${
          isListening
            ? "border-red-500/70 shadow-red-500/10"
            : compareMode
            ? "border-purple-500/60 shadow-purple-500/10"
            : "border-[#333537] focus-within:border-[#4b90ff]/70"
        }`}
      >
        {/* Previsualización de archivos adjuntos (chips arriba del input antes de enviar) */}
        {attachedItems.length > 0 && (
          <div className="flex flex-wrap gap-2 px-4 pt-3.5 pb-1">
            {attachedItems.map((item) => (
              <div
                key={item.id}
                className="group relative flex items-center gap-2.5 pl-2.5 pr-2 py-1.5 rounded-2xl bg-[#131314] border border-[#333537] text-xs text-[#e3e3e3]"
              >
                {item.category === "image" && item.previewUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={item.previewUrl}
                    alt={item.file.name}
                    className="w-8 h-8 rounded-lg object-cover border border-[#333537]"
                  />
                ) : item.category === "audio" ? (
                  <div className="w-8 h-8 rounded-lg bg-purple-500/20 text-purple-300 flex items-center justify-center shrink-0">
                    <Music className="w-4 h-4" />
                  </div>
                ) : (
                  <div className="w-8 h-8 rounded-lg bg-blue-500/20 text-blue-300 flex items-center justify-center shrink-0">
                    <FileText className="w-4 h-4" />
                  </div>
                )}

                <div className="max-w-[160px] min-w-0">
                  <p className="truncate font-medium text-xs" title={item.file.name}>
                    {item.file.name}
                  </p>
                  <p className="text-[10px] text-[#9aa0a6]">
                    {item.category.toUpperCase()} • {formatFileSize(item.file.size)}
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => handleRemoveAttachment(item.id)}
                  title="Quitar archivo"
                  className="p-1 rounded-full text-[#9aa0a6] hover:text-white hover:bg-[#282a2c] transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Fila principal del input */}
        <div className="flex items-end gap-2 px-3 sm:px-4 py-2.5">
          {/* Input oculto para subida multimodal */}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPTED_EXTENSIONS}
            onChange={(e) => handleFilesSelected(e.target.files)}
            className="hidden"
          />

          {/* Botón '+' para adjuntar fotos, documentos y audios */}
          <button
            type="button"
            disabled={isLoading}
            onClick={() => fileInputRef.current?.click()}
            title="Adjuntar fotos (.png, .jpg, .webp), documentos (.pdf, .txt, .csv, .md) o audios (.mp3, .wav, .m4a)"
            className="p-2.5 rounded-full bg-[#282a2c] hover:bg-[#333537] text-[#e3e3e3] disabled:opacity-50 transition-colors shrink-0"
          >
            <Plus className="w-5 h-5" />
          </button>

          {/* Área de texto auto-expandible */}
          <textarea
            ref={textareaRef}
            rows={1}
            value={displayedText}
            onChange={(e) => {
              setInterimTranscript("");
              setText(e.target.value);
            }}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            placeholder={
              isListening
                ? "Escuchando en vivo (es-ES)... habla ahora"
                : "Escribe un mensaje a LocalGem o adjunta fotos, PDFs, CSV o audios..."
            }
            className="flex-1 bg-transparent text-sm sm:text-base text-[#e3e3e3] placeholder-[#9aa0a6] resize-none focus:outline-none py-1.5 max-h-40 overflow-y-auto"
          />

          {/* Controles derechos: Comparar 2 respuestas, Micrófono en vivo y Enviar */}
          <div className="flex items-center gap-1.5 shrink-0">
            {/* Botón "Comparar 2 respuestas" accesible junto al botón de enviar */}
            <button
              type="button"
              onClick={() => onToggleCompareMode(!compareMode)}
              title="Comparar 2 respuestas (Genera Respuesta A concisa y Respuesta B detallada)"
              className={`flex items-center gap-1.5 px-2.5 py-2 rounded-full text-xs font-medium border transition-all ${
                compareMode
                  ? "bg-gradient-to-r from-[#4b90ff]/25 to-[#a855f7]/25 border-purple-400/60 text-purple-200 shadow-sm"
                  : "bg-[#282a2c]/80 hover:bg-[#333537] border-transparent text-[#9aa0a6] hover:text-white"
              }`}
            >
              <SplitSquareHorizontal className="w-4 h-4" />
              <span className="hidden md:inline">Comparar 2 respuestas</span>
            </button>

            {/* Botón de Micrófono en vivo (Web Speech API es-ES con animación de pulso rojo) */}
            <button
              type="button"
              onClick={toggleVoiceDictation}
              disabled={isLoading}
              title={
                isListening
                  ? "Detener dictado por voz"
                  : "Dictar por voz en tiempo real (es-ES)"
              }
              className={`relative p-2.5 rounded-full transition-all ${
                isListening
                  ? "bg-red-500 text-white shadow-lg shadow-red-500/40 animate-pulse"
                  : "bg-[#282a2c] hover:bg-[#333537] text-[#e3e3e3]"
              }`}
            >
              {isListening ? (
                <MicOff className="w-4 h-4" />
              ) : (
                <Mic className="w-4 h-4" />
              )}
            </button>

            {/* Botón Enviar */}
            <button
              type="submit"
              disabled={!canSend}
              title="Enviar mensaje"
              className={`p-2.5 rounded-full transition-all ${
                canSend
                  ? "bg-gradient-to-r from-[#4b90ff] to-[#a855f7] text-white hover:opacity-95 shadow-md shadow-blue-500/20"
                  : "bg-[#282a2c] text-[#9aa0a6]/40 cursor-not-allowed"
              }`}
            >
              {isLoading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Send className="w-4 h-4" />
              )}
            </button>
          </div>
        </div>

        {/* Barra informativa inferior sutil */}
        <div className="flex items-center justify-between px-4 pb-2 text-[11px] text-[#9aa0a6]/80">
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center gap-1">
              <ImageIcon className="w-3 h-3 text-[#4b90ff]" />
              Fotos, PDF, CSV, TXT, MD y Audio soportados
            </span>
          </div>
          {compareMode && (
            <span className="text-purple-300 font-medium">
              ✦ Se generarán 2 respuestas candidatas (A y B)
            </span>
          )}
        </div>
      </form>
    </div>
  );
}
