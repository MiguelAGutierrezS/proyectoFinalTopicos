"use client";

import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Sparkles,
  Zap,
  BookOpen,
  CheckCircle2,
  Volume2,
  Square,
  Loader2,
} from "lucide-react";
import { CandidateChoice, Message } from "@/lib/api";

export interface ABComparisonSelectorProps {
  message: Message;
  onSelectCandidate: (messageId: string, choice: CandidateChoice) => Promise<void>;
  onSpeakText?: (text: string, key: string) => void;
  speakingKey?: string | null;
}

export default function ABComparisonSelector({
  message,
  onSelectCandidate,
  onSpeakText,
  speakingKey,
}: ABComparisonSelectorProps) {
  const [submittingChoice, setSubmittingChoice] = useState<CandidateChoice | null>(
    null
  );

  const candidateA =
    message.candidate_a ||
    message.content ||
    "Respuesta concisa no disponible.";
  const candidateB =
    message.candidate_b ||
    message.content ||
    "Respuesta detallada no disponible.";

  const handleChoose = async (choice: CandidateChoice) => {
    if (submittingChoice) return;
    setSubmittingChoice(choice);
    try {
      await onSelectCandidate(message.id, choice);
    } finally {
      setSubmittingChoice(null);
    }
  };

  const keyA = `${message.id}-candidate-A`;
  const keyB = `${message.id}-candidate-B`;

  return (
    <div className="w-full my-3 rounded-2xl border border-purple-500/40 bg-gradient-to-b from-[#1e1f20] to-[#17181a] p-4 sm:p-5 shadow-xl shadow-black/30">
      {/* Encabezado llamativo */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-4 mb-4 border-b border-[#333537]">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-gradient-to-tr from-[#4b90ff]/25 to-[#a855f7]/25 border border-purple-400/30">
            <Sparkles className="w-5 h-5 text-purple-300" />
          </div>
          <div>
            <h3 className="text-sm sm:text-base font-semibold text-white">
              ¿Cuál de estas dos respuestas prefieres para continuar?
            </h3>
            <p className="text-xs text-[#9aa0a6]">
              Modo de Satisfacción A/B • Tu elección entrena el estilo de tus próximas respuestas
            </p>
          </div>
        </div>
        <span className="inline-flex items-center self-start sm:self-auto text-[11px] font-medium px-2.5 py-1 rounded-full bg-purple-500/15 text-purple-300 border border-purple-500/30">
          Comparación A/B Activa
        </span>
      </div>

      {/* Dos tarjetas lado a lado */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Tarjeta A (Enfoque Directo) */}
        <div className="flex flex-col justify-between rounded-2xl bg-[#131314] border border-[#333537] hover:border-[#4b90ff]/70 p-4 transition-all duration-200 shadow-md">
          <div>
            <div className="flex items-center justify-between gap-2 pb-3 mb-3 border-b border-[#333537]/80">
              <div className="flex items-center gap-2">
                <span className="flex items-center justify-center w-6 h-6 rounded-lg bg-[#4b90ff]/20 text-[#4b90ff] font-bold text-xs border border-[#4b90ff]/40">
                  A
                </span>
                <div>
                  <h4 className="text-xs sm:text-sm font-semibold text-white flex items-center gap-1.5">
                    <Zap className="w-3.5 h-3.5 text-[#4b90ff]" />
                    <span>Tarjeta A (Enfoque Directo)</span>
                  </h4>
                  <span className="text-[11px] text-[#9aa0a6]">
                    Concisa, ejecutiva y al grano
                  </span>
                </div>
              </div>

              {onSpeakText && (
                <button
                  type="button"
                  onClick={() => onSpeakText(candidateA, keyA)}
                  title={
                    speakingKey === keyA
                      ? "Detener lectura en voz alta"
                      : "Escuchar Respuesta A en voz alta"
                  }
                  className={`p-1.5 rounded-lg border text-xs transition-colors ${
                    speakingKey === keyA
                      ? "bg-red-500/20 border-red-500/40 text-red-300"
                      : "bg-[#1e1f20] border-[#333537] text-[#9aa0a6] hover:text-white"
                  }`}
                >
                  {speakingKey === keyA ? (
                    <Square className="w-3.5 h-3.5 fill-current" />
                  ) : (
                    <Volume2 className="w-3.5 h-3.5" />
                  )}
                </button>
              )}
            </div>

            <div className="gemini-markdown text-sm text-[#e3e3e3] max-h-[380px] overflow-y-auto pr-1">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {candidateA}
              </ReactMarkdown>
            </div>
          </div>

          <div className="pt-4 mt-4 border-t border-[#333537]/60">
            <button
              type="button"
              disabled={submittingChoice !== null}
              onClick={() => handleChoose("A")}
              className="w-full py-2.5 px-4 rounded-xl font-medium text-xs sm:text-sm text-white bg-gradient-to-r from-[#4b90ff] to-blue-600 hover:from-[#5c9dff] hover:to-blue-500 disabled:opacity-50 flex items-center justify-center gap-2 shadow-md shadow-blue-600/20 transition-all"
            >
              {submittingChoice === "A" ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Guardando preferencia...</span>
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-4 h-4" />
                  <span>Elegir Respuesta A</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Tarjeta B (Enfoque Detallado) */}
        <div className="flex flex-col justify-between rounded-2xl bg-[#131314] border border-[#333537] hover:border-[#a855f7]/70 p-4 transition-all duration-200 shadow-md">
          <div>
            <div className="flex items-center justify-between gap-2 pb-3 mb-3 border-b border-[#333537]/80">
              <div className="flex items-center gap-2">
                <span className="flex items-center justify-center w-6 h-6 rounded-lg bg-[#a855f7]/20 text-purple-300 font-bold text-xs border border-[#a855f7]/40">
                  B
                </span>
                <div>
                  <h4 className="text-xs sm:text-sm font-semibold text-white flex items-center gap-1.5">
                    <BookOpen className="w-3.5 h-3.5 text-purple-400" />
                    <span>Tarjeta B (Enfoque Detallado)</span>
                  </h4>
                  <span className="text-[11px] text-[#9aa0a6]">
                    Profunda, explicativa y con ejemplos
                  </span>
                </div>
              </div>

              {onSpeakText && (
                <button
                  type="button"
                  onClick={() => onSpeakText(candidateB, keyB)}
                  title={
                    speakingKey === keyB
                      ? "Detener lectura en voz alta"
                      : "Escuchar Respuesta B en voz alta"
                  }
                  className={`p-1.5 rounded-lg border text-xs transition-colors ${
                    speakingKey === keyB
                      ? "bg-red-500/20 border-red-500/40 text-red-300"
                      : "bg-[#1e1f20] border-[#333537] text-[#9aa0a6] hover:text-white"
                  }`}
                >
                  {speakingKey === keyB ? (
                    <Square className="w-3.5 h-3.5 fill-current" />
                  ) : (
                    <Volume2 className="w-3.5 h-3.5" />
                  )}
                </button>
              )}
            </div>

            <div className="gemini-markdown text-sm text-[#e3e3e3] max-h-[380px] overflow-y-auto pr-1">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {candidateB}
              </ReactMarkdown>
            </div>
          </div>

          <div className="pt-4 mt-4 border-t border-[#333537]/60">
            <button
              type="button"
              disabled={submittingChoice !== null}
              onClick={() => handleChoose("B")}
              className="w-full py-2.5 px-4 rounded-xl font-medium text-xs sm:text-sm text-white bg-gradient-to-r from-[#a855f7] to-indigo-600 hover:from-purple-500 hover:to-indigo-500 disabled:opacity-50 flex items-center justify-center gap-2 shadow-md shadow-purple-600/20 transition-all"
            >
              {submittingChoice === "B" ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Guardando preferencia...</span>
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-4 h-4" />
                  <span>Elegir Respuesta B</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
