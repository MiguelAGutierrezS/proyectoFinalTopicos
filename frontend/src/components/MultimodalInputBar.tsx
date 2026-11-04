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
  Zap,
  Plug,
  Radio,
  Square,
} from "lucide-react";
import { SkillInfo } from "@/lib/api";

export interface MultimodalInputBarProps {
  onSendMessage: (params: {
    content: string;
    files: File[];
    forceCompare: boolean;
  }) => Promise<void> | void;
  isLoading: boolean;
  compareMode: boolean;
  onToggleCompareMode: (enabled: boolean) => void;
  skills: SkillInfo[];
  selectedSkillId: string;
  onSelectSkillId: (skillId: string) => void;
  enableMcp: boolean;
  onToggleMcp: (enabled: boolean) => void;
  onOpenSkillsMcpModal?: () => void;
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

function getFileCategory(file: File): "image" | "document" | "audio" | null {
  const ext = file.name.split(".").pop()?.toLowerCase() || "";
  if (["png", "jpg", "jpeg", "webp"].includes(ext) || file.type.startsWith("image/")) {
    return "image";
  }
  if (["mp3", "wav", "m4a", "ogg"].includes(ext) || file.type.startsWith("audio/")) {
    return "audio";
  }
  if (
    ["pdf", "txt", "csv", "md"].includes(ext) ||
    ["application/pdf", "text/plain", "text/csv", "text/markdown"].includes(file.type)
  ) {
    return "document";
  }
  return null;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

/**
 * Codifica muestras de audio Float32 en un archivo WAV PCM 16-bit estándar (16 kHz mono)
 * para que `faster-whisper` en el backend lo transcriba sin requerir FFmpeg externo.
 */
function encodeWavFromFloat32(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  const writeString = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  };

  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true); // PCM chunk size
  view.setUint16(20, 1, true); // PCM format
  view.setUint16(22, 1, true); // Mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true); // 16-bit
  writeString(36, "data");
  view.setUint32(40, samples.length * 2, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }

  return new Blob([buffer], { type: "audio/wav" });
}

export default function MultimodalInputBar({
  onSendMessage,
  isLoading,
  compareMode,
  onToggleCompareMode,
  skills,
  selectedSkillId,
  onSelectSkillId,
  enableMcp,
  onToggleMcp,
  onOpenSkillsMcpModal,
}: MultimodalInputBarProps) {
  const [text, setText] = useState("");
  const [attachedItems, setAttachedItems] = useState<PreviewFileItem[]>([]);
  const [isListening, setIsListening] = useState(false);
  const [interimTranscript, setInterimTranscript] = useState("");
  const [voiceWarning, setVoiceWarning] = useState<string | null>(null);
  const [isDraggingOver, setIsDraggingOver] = useState(false);

  // Grabadora de nota de voz .wav para faster-whisper (REQ-MULTI-09)
  const [isRecordingWav, setIsRecordingWav] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const scriptNodeRef = useRef<ScriptProcessorNode | null>(null);
  const recordedChunksRef = useRef<Float32Array[]>([]);
  const recordingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null);

  // Limpiar recursos al desmontar
  useEffect(() => {
    return () => {
      attachedItems.forEach((item) => {
        if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
      });
      if (recordingTimerRef.current) clearInterval(recordingTimerRef.current);
      mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
      void audioContextRef.current?.close();
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

  const handleFilesSelected = (fileList: FileList | File[] | null) => {
    if (!fileList || fileList.length === 0) return;
    setVoiceWarning(null);

    const newItems: PreviewFileItem[] = [];
    Array.from(fileList).forEach((file) => {
      if (file.size > 25 * 1024 * 1024) {
        setVoiceWarning(`El archivo "${file.name}" supera el límite de 25 MB.`);
        return;
      }
      const category = getFileCategory(file);
      if (!category) {
        setVoiceWarning(
          `El formato de "${file.name}" no está permitido. Formatos soportados: fotos (.png, .jpg, .webp), documentos (.pdf, .txt, .csv, .md) o audios (.mp3, .wav, .m4a, .ogg).`
        );
        return;
      }
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

  // Soporte Ctrl+V para pegar capturas de pantalla directamente desde el portapapeles (REQ-MULTI-09)
  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items;
    if (!items) return;

    const pastedFiles: File[] = [];
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.kind === "file") {
        const blob = item.getAsFile();
        if (blob) {
          const ext = blob.type.split("/")[1] || "png";
          const fileName =
            blob.name && blob.name !== "image.png"
              ? blob.name
              : `captura_${new Date().toISOString().slice(11, 19).replace(/:/g, "-")}.${ext}`;
          const namedFile = new File([blob], fileName, { type: blob.type });
          pastedFiles.push(namedFile);
        }
      }
    }

    if (pastedFiles.length > 0) {
      e.preventDefault();
      handleFilesSelected(pastedFiles);
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

  // Grabación de nota de voz .wav nativa (para faster-whisper en el backend)
  const toggleWavRecording = async () => {
    setVoiceWarning(null);

    if (isRecordingWav) {
      if (recordingTimerRef.current) {
        clearInterval(recordingTimerRef.current);
        recordingTimerRef.current = null;
      }
      setIsRecordingWav(false);

      const sampleRate = audioContextRef.current?.sampleRate || 16000;
      scriptNodeRef.current?.disconnect();
      mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
      await audioContextRef.current?.close().catch(() => {});

      const chunks = recordedChunksRef.current;
      const totalLength = chunks.reduce((acc, c) => acc + c.length, 0);
      if (totalLength > 0) {
        const merged = new Float32Array(totalLength);
        let offset = 0;
        for (const chunk of chunks) {
          merged.set(chunk, offset);
          offset += chunk.length;
        }
        const wavBlob = encodeWavFromFloat32(merged, sampleRate);
        const fileName = `nota_voz_${new Date()
          .toISOString()
          .slice(11, 19)
          .replace(/:/g, "-")}.wav`;
        const wavFile = new File([wavBlob], fileName, { type: "audio/wav" });
        handleFilesSelected([wavFile]);
      }
      recordedChunksRef.current = [];
      setRecordingSeconds(0);
      return;
    }

    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setVoiceWarning("Tu navegador no permite grabar audio desde el micrófono.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const AudioCtx =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const audioCtx = new AudioCtx({ sampleRate: 16000 });
      const source = audioCtx.createMediaStreamSource(stream);
      const processor = audioCtx.createScriptProcessor(4096, 1, 1);

      recordedChunksRef.current = [];
      processor.onaudioprocess = (ev) => {
        const inputData = ev.inputBuffer.getChannelData(0);
        recordedChunksRef.current.push(new Float32Array(inputData));
      };

      source.connect(processor);
      processor.connect(audioCtx.destination);

      mediaStreamRef.current = stream;
      audioContextRef.current = audioCtx;
      scriptNodeRef.current = processor;
      setRecordingSeconds(0);
      setIsRecordingWav(true);

      recordingTimerRef.current = setInterval(() => {
        setRecordingSeconds((s) => s + 1);
      }, 1000);
    } catch {
      setVoiceWarning(
        "No se pudo acceder al micrófono para grabar la nota de voz (.wav)."
      );
      setIsRecordingWav(false);
    }
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
        "Tu navegador no soporta dictado en vivo (Web Speech API). Puedes usar el botón de Grabar Audio (.wav) junto al micrófono para transcribir con faster-whisper."
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
    <div className="w-full max-w-4xl mx-auto px-3 sm:px-6 pb-4 pt-1.5">
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

      {/* Barra rápida superior de Skills (`SKILL.md`) y Herramientas MCP Locales */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2 px-1">
        <div className="flex flex-wrap items-center gap-1.5">
          {/* Selector de Skill activa */}
          <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#1e1f20] border border-[#333537] text-xs">
            <Zap className="w-3.5 h-3.5 text-amber-400 shrink-0" />
            <span className="text-[#9aa0a6] hidden sm:inline">Skill:</span>
            <select
              value={selectedSkillId}
              onChange={(e) => onSelectSkillId(e.target.value)}
              aria-label="Seleccionar Skill especializada"
              className="bg-transparent text-[#e3e3e3] font-medium focus:outline-none cursor-pointer text-xs"
            >
              <option value="auto" className="bg-[#1e1f20] text-[#e3e3e3]">
                ✨ Auto-detección (según consulta)
              </option>
              <option value="none" className="bg-[#1e1f20] text-[#9aa0a6]">
                Sin Skill adicional
              </option>
              {skills.map((sk) => (
                <option
                  key={sk.id}
                  value={sk.id}
                  className="bg-[#1e1f20] text-[#e3e3e3]"
                >
                  {sk.name} (/{sk.id})
                </option>
              ))}
            </select>
          </div>

          {/* Toggle MCP Tools */}
          <button
            type="button"
            onClick={() => onToggleMcp(!enableMcp)}
            title="Activar/Desactivar herramientas locales Model Context Protocol (Calculadora, SQLite, Reloj, Archivos, Wikipedia)"
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-all ${
              enableMcp
                ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
                : "bg-[#1e1f20] border-[#333537] text-[#9aa0a6]"
            }`}
          >
            <Plug className="w-3.5 h-3.5" />
            <span>MCP {enableMcp ? "Activo" : "Off"}</span>
          </button>
        </div>

        {onOpenSkillsMcpModal && (
          <button
            type="button"
            onClick={onOpenSkillsMcpModal}
            className="text-[11px] text-[#4b90ff] hover:text-blue-300 hover:underline transition-colors"
          >
            Ver / Probar Skills y Herramientas MCP →
          </button>
        )}
      </div>

      {/* Contenedor estilo cápsula de Google Gemini (#1e1f20) con soporte Drag & Drop y Ctrl+V */}
      <form
        onSubmit={handleSubmit}
        onDragOver={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setIsDraggingOver(true);
        }}
        onDragEnter={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setIsDraggingOver(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          e.stopPropagation();
          if (!e.currentTarget.contains(e.relatedTarget as Node)) {
            setIsDraggingOver(false);
          }
        }}
        onDrop={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setIsDraggingOver(false);
          handleFilesSelected(e.dataTransfer.files);
        }}
        className={`relative rounded-3xl bg-[#1e1f20] border transition-all shadow-lg ${
          isDraggingOver
            ? "border-[#4b90ff] shadow-blue-500/20 ring-2 ring-[#4b90ff]/30"
            : isListening || isRecordingWav
            ? "border-red-500/70 shadow-red-500/10"
            : compareMode
            ? "border-purple-500/60 shadow-purple-500/10"
            : "border-[#333537] focus-within:border-[#4b90ff]/70"
        }`}
      >
        {/* Overlay interactivo al arrastrar archivos (REQ-UI-04) */}
        {isDraggingOver && (
          <div className="absolute inset-0 z-30 flex flex-col items-center justify-center rounded-3xl bg-[#131314]/92 border-2 border-dashed border-[#4b90ff] pointer-events-none backdrop-blur-sm animate-in fade-in duration-150">
            <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-[#4b90ff]/30 to-[#a855f7]/30 flex items-center justify-center mb-2 shadow-lg shadow-blue-500/20">
              <Plus className="w-6 h-6 text-[#4b90ff]" />
            </div>
            <p className="text-sm font-semibold text-white">Suelta aquí tus archivos</p>
            <p className="text-xs text-[#9aa0a6] mt-0.5">
              Fotos, PDF, CSV, TXT, MD o Audios (máx 25 MB)
            </p>
          </div>
        )}

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

          {/* Área de texto auto-expandible con soporte Ctrl+V */}
          <textarea
            ref={textareaRef}
            rows={1}
            value={displayedText}
            onChange={(e) => {
              setInterimTranscript("");
              setText(e.target.value);
            }}
            onPaste={handlePaste}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            placeholder={
              isRecordingWav
                ? `Grabando nota de voz WAV (${recordingSeconds}s)... pulsa detener para adjuntar`
                : isListening
                ? "Escuchando en vivo (es-ES)... habla ahora"
                : "Escribe un mensaje, pega una captura (Ctrl+V) o adjunta fotos, PDFs, CSV o audios..."
            }
            className="flex-1 bg-transparent text-sm sm:text-base text-[#e3e3e3] placeholder-[#9aa0a6] resize-none focus:outline-none py-1.5 max-h-40 overflow-y-auto"
          />

          {/* Controles derechos: Comparar 2 respuestas, Grabar nota de voz WAV, Dictado en vivo y Enviar */}
          <div className="flex items-center gap-1.5 shrink-0">
            {/* Botón "Comparar 2 respuestas" */}
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

            {/* Botón de Grabación de Nota de Voz .WAV (Transcripción local con faster-whisper) */}
            <button
              type="button"
              onClick={() => void toggleWavRecording()}
              disabled={isLoading}
              title={
                isRecordingWav
                  ? `Detener grabación WAV (${recordingSeconds}s) y adjuntar para faster-whisper`
                  : "Grabar nota de voz (.wav) para transcripción local con faster-whisper"
              }
              className={`relative flex items-center gap-1 px-2.5 py-2 rounded-full text-xs font-medium transition-all ${
                isRecordingWav
                  ? "bg-red-500 text-white shadow-lg shadow-red-500/40 animate-pulse"
                  : "bg-[#282a2c] hover:bg-[#333537] text-purple-300"
              }`}
            >
              {isRecordingWav ? (
                <>
                  <Square className="w-3.5 h-3.5 fill-current" />
                  <span>{recordingSeconds}s</span>
                </>
              ) : (
                <>
                  <Radio className="w-4 h-4" />
                  <span className="hidden lg:inline">Audio IA</span>
                </>
              )}
            </button>

            {/* Botón de Micrófono en vivo (Web Speech API es-ES) */}
            <button
              type="button"
              onClick={toggleVoiceDictation}
              disabled={isLoading}
              title={
                isListening
                  ? "Detener dictado por voz"
                  : "Dictar texto por voz en tiempo real (es-ES)"
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
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 pb-2 text-[11px] text-[#9aa0a6]/80">
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center gap-1">
              <ImageIcon className="w-3 h-3 text-[#4b90ff]" />
              Vision Bridge (moondream + llama3.2) • PDF • CSV • Audio Whisper • Ctrl+V
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
