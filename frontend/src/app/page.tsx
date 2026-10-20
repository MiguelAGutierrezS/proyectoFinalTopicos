"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Sparkles,
  Volume2,
  Square,
  SplitSquareHorizontal,
  FileText,
  Music,
  User,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Mic,
} from "lucide-react";

import Sidebar from "@/components/Sidebar";
import ABComparisonSelector from "@/components/ABComparisonSelector";
import FollowUpOptions from "@/components/FollowUpOptions";
import MultimodalInputBar from "@/components/MultimodalInputBar";
import {
  CandidateChoice,
  ChatSummary,
  Message,
  OllamaModelInfo,
  PreferenceSummary,
  createChat,
  deleteChat,
  fetchChatById,
  fetchChats,
  fetchHealth,
  fetchModels,
  fetchPreferenceSummary,
  getAttachmentUrl,
  selectABCandidate,
  sendMessage,
} from "@/lib/api";

/**
 * Limpia símbolos de Markdown para que `window.speechSynthesis` lea el texto con naturalidad.
 */
function stripMarkdownForSpeech(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, " Bloque de código. ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[.*?\]\(.*?\)/g, "")
    .replace(/\[([^\]]+)\]\([^\)]+\)/g, "$1")
    .replace(/^[#>*+-]+\s+/gm, "")
    .replace(/[*_~]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export default function HomePage() {
  // Estado de barra lateral y chats
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoadingChats, setIsLoadingChats] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);

  // Estado de Ollama y Modo Comparación A/B
  const [models, setModels] = useState<OllamaModelInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("llama3.2:latest");
  const [ollamaReachable, setOllamaReachable] = useState<boolean>(true);
  const [compareMode, setCompareMode] = useState<boolean>(false);
  const [preferenceSummary, setPreferenceSummary] =
    useState<PreferenceSummary | null>(null);

  // Estado de Lectura en Voz Alta (TTS con window.speechSynthesis)
  const [speakingKey, setSpeakingKey] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, isSending, scrollToBottom]);

  // Detener síntesis de voz al desmontar
  useEffect(() => {
    return () => {
      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  // Carga inicial de modelos, salud de Ollama, preferencias y lista de chats en SQLite
  const loadInitialData = useCallback(async () => {
    setIsLoadingChats(true);
    try {
      const [chatsData, modelsData, healthData, prefData] = await Promise.allSettled([
        fetchChats(),
        fetchModels(),
        fetchHealth(),
        fetchPreferenceSummary(),
      ]);

      if (chatsData.status === "fulfilled") {
        setChats(chatsData.value);
        if (chatsData.value.length > 0 && !activeChatId) {
          const firstId = chatsData.value[0].id;
          setActiveChatId(firstId);
          const detail = await fetchChatById(firstId);
          setMessages(detail.messages);
        }
      }

      if (modelsData.status === "fulfilled") {
        setModels(modelsData.value.models);
        if (modelsData.value.default_model) {
          setSelectedModel(modelsData.value.default_model);
        }
      }

      if (healthData.status === "fulfilled") {
        setOllamaReachable(healthData.value.ollama_reachable);
      }

      if (prefData.status === "fulfilled") {
        setPreferenceSummary(prefData.value);
      }
    } catch (err) {
      setErrorBanner(
        err instanceof Error
          ? err.message
          : "No se pudo conectar con el backend en http://localhost:8000"
      );
    } finally {
      setIsLoadingChats(false);
    }
  }, [activeChatId]);

  useEffect(() => {
    void loadInitialData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleRefreshModels = async () => {
    try {
      const [modelsData, healthData] = await Promise.all([
        fetchModels(),
        fetchHealth(),
      ]);
      setModels(modelsData.models);
      setOllamaReachable(healthData.ollama_reachable);
      if (modelsData.default_model && !selectedModel) {
        setSelectedModel(modelsData.default_model);
      }
    } catch {
      setOllamaReachable(false);
    }
  };

  // Seleccionar un chat existente de la barra lateral
  const handleSelectChat = async (chatId: string) => {
    setErrorBanner(null);
    setActiveChatId(chatId);
    try {
      const detail = await fetchChatById(chatId);
      setMessages(detail.messages);
    } catch (err) {
      setErrorBanner(
        err instanceof Error ? err.message : "Error al cargar el chat seleccionado."
      );
    }
  };

  // Crear un nuevo chat limpio
  const handleNewChat = async () => {
    setErrorBanner(null);
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      setSpeakingKey(null);
    }

    try {
      const created = await createChat("Nuevo Chat");
      const updatedList = await fetchChats();
      setChats(updatedList);
      setActiveChatId(created.id);
      setMessages([]);
    } catch (err) {
      setErrorBanner(
        err instanceof Error ? err.message : "No se pudo crear un nuevo chat."
      );
    }
  };

  // Eliminar un chat de SQLite
  const handleDeleteChat = async (chatId: string) => {
    setErrorBanner(null);
    try {
      await deleteChat(chatId);
      const updatedList = await fetchChats();
      setChats(updatedList);

      if (activeChatId === chatId) {
        if (updatedList.length > 0) {
          const nextChatId = updatedList[0].id;
          setActiveChatId(nextChatId);
          const detail = await fetchChatById(nextChatId);
          setMessages(detail.messages);
        } else {
          setActiveChatId(null);
          setMessages([]);
        }
      }
    } catch (err) {
      setErrorBanner(
        err instanceof Error ? err.message : "No se pudo eliminar el chat."
      );
    }
  };

  // Enviar mensaje (desde barra inferior, clic en opción de seguimiento o botón regenerar A/B)
  const handleSendUserMessage = async ({
    content,
    files = [],
    forceCompare = false,
  }: {
    content: string;
    files?: File[];
    forceCompare?: boolean;
  }) => {
    if (isSending) return;
    setErrorBanner(null);
    setIsSending(true);

    try {
      let targetChatId = activeChatId;
      if (!targetChatId) {
        const created = await createChat("Nuevo Chat");
        targetChatId = created.id;
        setActiveChatId(targetChatId);
      }

      // Mensaje optimista temporal mientras responde Ollama
      const tempUserMsg: Message = {
        id: `temp-user-${Date.now()}`,
        chat_id: targetChatId,
        role: "user",
        content:
          content ||
          (files.length > 0
            ? `[Adjuntos: ${files.map((f) => f.name).join(", ")}]`
            : ""),
        follow_up_options: [],
        is_ab_test: false,
        candidate_a: null,
        candidate_b: null,
        selected_candidate: null,
        created_at: new Date().toISOString(),
        attachments: [],
      };
      setMessages((prev) => [...prev, tempUserMsg]);

      const response = await sendMessage({
        chatId: targetChatId,
        content,
        model: selectedModel,
        compareMode: forceCompare || compareMode,
        files,
      });

      // Reemplazar el mensaje optimista con los mensajes reales persistidos en SQLite
      setMessages((prev) => [
        ...prev.filter((m) => m.id !== tempUserMsg.id),
        response.user_message,
        response.assistant_message,
      ]);

      // Refrescar lista de chats en el sidebar para mostrar el nuevo título o fecha actualizada
      const updatedChats = await fetchChats();
      setChats(updatedChats);
    } catch (err) {
      setErrorBanner(
        err instanceof Error
          ? err.message
          : "Ocurrió un error al procesar tu mensaje."
      );
      // Limpiar mensaje temporal si falló
      setMessages((prev) => prev.filter((m) => !m.id.startsWith("temp-user-")));
    } finally {
      setIsSending(false);
    }
  };

  // Elegir Respuesta A o Respuesta B en el selector de comparación A/B
  const handleSelectABCandidate = async (
    messageId: string,
    choice: CandidateChoice
  ) => {
    setErrorBanner(null);
    try {
      const result = await selectABCandidate(messageId, choice);
      setMessages((prev) =>
        prev.map((m) => (m.id === messageId ? result.message : m))
      );
      const updatedPref = await fetchPreferenceSummary();
      setPreferenceSummary(updatedPref);
    } catch (err) {
      setErrorBanner(
        err instanceof Error
          ? err.message
          : "No se pudo guardar tu selección de respuesta A/B."
      );
    }
  };

  // Regenerar una respuesta de la IA activando la comparación de 2 opciones (A y B)
  const handleRegenerateWithComparison = (assistantMsgIndex: number) => {
    if (isSending) return;
    // Buscar el mensaje del usuario inmediatamente anterior
    let promptToRepeat = "Profundiza en el tema anterior y compara 2 enfoques";
    for (let i = assistantMsgIndex - 1; i >= 0; i--) {
      if (messages[i]?.role === "user" && messages[i].content.trim()) {
        promptToRepeat = messages[i].content;
        break;
      }
    }
    void handleSendUserMessage({
      content: promptToRepeat,
      files: [],
      forceCompare: true,
    });
  };

  // Lectura en voz alta gratuita (TTS con window.speechSynthesis)
  const handleSpeakText = (rawText: string, key: string) => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) {
      setErrorBanner("Tu navegador no soporta síntesis de voz (speechSynthesis).");
      return;
    }

    if (speakingKey === key) {
      window.speechSynthesis.cancel();
      setSpeakingKey(null);
      return;
    }

    window.speechSynthesis.cancel();
    const cleanText = stripMarkdownForSpeech(rawText);
    if (!cleanText) return;

    const utterance = new SpeechSynthesisUtterance(cleanText);
    utterance.lang = "es-ES";
    utterance.rate = 1.02;

    const voices = window.speechSynthesis.getVoices();
    const spanishVoice = voices.find((v) =>
      v.lang.toLowerCase().startsWith("es")
    );
    if (spanishVoice) {
      utterance.voice = spanishVoice;
    }

    utterance.onend = () => setSpeakingKey(null);
    utterance.onerror = () => setSpeakingKey(null);

    setSpeakingKey(key);
    window.speechSynthesis.speak(utterance);
  };

  const userTurnCount = messages.filter((m) => m.role === "user").length;
  const turnsUntilAutoAB = 3 - (userTurnCount % 3);

  return (
    <div className="flex h-screen w-screen bg-[#131314] text-[#e3e3e3] overflow-hidden">
      {/* Barra lateral izquierda */}
      <Sidebar
        chats={chats}
        activeChatId={activeChatId}
        onSelectChat={handleSelectChat}
        onNewChat={handleNewChat}
        onDeleteChat={handleDeleteChat}
        models={models}
        selectedModel={selectedModel}
        onSelectModel={setSelectedModel}
        onRefreshModels={handleRefreshModels}
        ollamaReachable={ollamaReachable}
        compareMode={compareMode}
        onToggleCompareMode={setCompareMode}
        isOpen={sidebarOpen}
        onToggleSidebar={() => setSidebarOpen((prev) => !prev)}
        isLoadingChats={isLoadingChats}
      />

      {/* Área principal */}
      <div className="flex-1 flex flex-col h-screen min-w-0 bg-[#131314]">
        {/* Barra superior de estado */}
        <header className="flex items-center justify-between px-4 sm:px-6 py-3 border-b border-[#333537]/60 bg-[#131314]/90 backdrop-blur-md z-10">
          <div className="flex items-center gap-3 min-w-0">
            <h1 className="text-sm sm:text-base font-semibold truncate text-white">
              {chats.find((c) => c.id === activeChatId)?.title || "LocalGem Chat"}
            </h1>
            <span className="hidden sm:inline-flex items-center gap-1.5 text-[11px] px-2.5 py-0.5 rounded-full bg-[#1e1f20] border border-[#333537] text-[#9aa0a6]">
              Modelo: <strong className="text-[#e3e3e3]">{selectedModel}</strong>
            </span>
          </div>

          <div className="flex items-center gap-2 text-xs">
            {preferenceSummary && preferenceSummary.total_ab_selections > 0 && (
              <span
                title="Preferencia de estilo aprendida a partir de tus elecciones A/B"
                className="hidden md:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-blue-500/10 border border-blue-500/30 text-blue-300 text-[11px]"
              >
                <Sparkles className="w-3 h-3" />
                Estilo preferido:{" "}
                <strong>
                  {preferenceSummary.dominant_style === "concise"
                    ? "Conciso (A)"
                    : preferenceSummary.dominant_style === "detailed"
                    ? "Detallado (B)"
                    : "Equilibrado"}
                </strong>
              </span>
            )}

            <span className="text-[11px] px-2.5 py-1 rounded-full bg-[#1e1f20] border border-[#333537] text-[#9aa0a6]">
              {compareMode
                ? "Modo A/B Manual Activo"
                : `Próximo test A/B auto en ${turnsUntilAutoAB} ${
                    turnsUntilAutoAB === 1 ? "mensaje" : "mensajes"
                  }`}
            </span>
          </div>
        </header>

        {/* Banner de error si existe */}
        {errorBanner && (
          <div className="mx-4 sm:mx-8 mt-3 px-4 py-2.5 rounded-xl bg-red-500/15 border border-red-500/40 text-red-200 text-xs flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
              <span>{errorBanner}</span>
            </div>
            <button
              type="button"
              onClick={() => setErrorBanner(null)}
              className="text-xs underline hover:text-white"
            >
              Cerrar
            </button>
          </div>
        )}

        {/* Lienzo central de conversación */}
        <main className="flex-1 overflow-y-auto px-3 sm:px-6 py-6">
          <div className="max-w-4xl mx-auto space-y-6">
            {messages.length === 0 ? (
              /* Pantalla de bienvenida estilo Google Gemini */
              <div className="flex flex-col items-center justify-center text-center py-12 sm:py-20 px-4">
                <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-[#4b90ff] via-indigo-500 to-[#a855f7] flex items-center justify-center shadow-xl shadow-blue-500/20 mb-5">
                  <Sparkles className="w-7 h-7 text-white" />
                </div>

                <h2 className="text-2xl sm:text-4xl font-bold tracking-tight bg-gradient-to-r from-[#4b90ff] via-indigo-300 to-[#a855f7] bg-clip-text text-transparent mb-3">
                  Hola, soy LocalGem
                </h2>
                <p className="text-sm sm:text-base text-[#9aa0a6] max-w-xl mb-8">
                  Tu clon de Google Gemini 100% local y gratuito. Sube fotos, PDFs,
                  archivos CSV o audios, habla con el micrófono en tiempo real y
                  compara respuestas A/B.
                </p>

                {/* Tarjetas de sugerencias iniciales */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 w-full max-w-3xl text-left">
                  {[
                    {
                      title: "Explicación técnica",
                      prompt:
                        "Explícame cómo funciona la arquitectura de microservicios con Python y FastAPI",
                      icon: Sparkles,
                    },
                    {
                      title: "Comparar 2 respuestas (A/B)",
                      prompt:
                        "Compara las ventajas de SQLite frente a PostgreSQL para aplicaciones locales",
                      icon: SplitSquareHorizontal,
                      forceCompare: true,
                    },
                    {
                      title: "Análisis multimodal y voz",
                      prompt:
                        "Dame una plantilla en CSV para control de gastos mensuales y explícame cómo analizarla",
                      icon: Mic,
                    },
                  ].map((card, i) => {
                    const IconComponent = card.icon;
                    return (
                      <button
                        key={i}
                        type="button"
                        onClick={() =>
                          void handleSendUserMessage({
                            content: card.prompt,
                            files: [],
                            forceCompare: Boolean(card.forceCompare),
                          })
                        }
                        className="group flex flex-col justify-between p-4 rounded-2xl bg-[#1e1f20] hover:bg-[#282a2c] border border-[#333537] hover:border-[#4b90ff]/50 transition-all text-left"
                      >
                        <div>
                          <div className="w-8 h-8 rounded-xl bg-[#131314] flex items-center justify-center mb-3 text-[#4b90ff] group-hover:text-purple-400 transition-colors">
                            <IconComponent className="w-4 h-4" />
                          </div>
                          <h3 className="text-xs font-semibold text-white mb-1">
                            {card.title}
                          </h3>
                          <p className="text-xs text-[#9aa0a6] line-clamp-3">
                            {card.prompt}
                          </p>
                        </div>
                        <span className="text-[11px] text-[#4b90ff] mt-3 inline-block group-hover:underline">
                          Probar ahora →
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : (
              messages.map((msg, idx) => {
                const isUser = msg.role === "user";
                const showABSelector =
                  !isUser && msg.is_ab_test && !msg.selected_candidate;
                const speechId = `msg-tts-${msg.id}`;

                return (
                  <div
                    key={msg.id}
                    className={`flex flex-col ${
                      isUser ? "items-end" : "items-start"
                    }`}
                  >
                    <div
                      className={`flex items-start gap-3 max-w-full ${
                        isUser ? "flex-row-reverse" : "flex-row w-full"
                      }`}
                    >
                      {/* Avatar */}
                      <div
                        className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-0.5 ${
                          isUser
                            ? "bg-[#282a2c] text-[#e3e3e3]"
                            : "bg-gradient-to-tr from-[#4b90ff] to-[#a855f7] text-white shadow-md shadow-blue-500/20"
                        }`}
                      >
                        {isUser ? (
                          <User className="w-4 h-4" />
                        ) : (
                          <Sparkles className="w-4 h-4" />
                        )}
                      </div>

                      {/* Cuerpo del mensaje */}
                      <div
                        className={`min-w-0 ${
                          isUser
                            ? "max-w-[85%] sm:max-w-[75%] rounded-3xl rounded-tr-md bg-[#1e1f20] border border-[#333537] px-4 py-3 text-[#e3e3e3]"
                            : "flex-1"
                        }`}
                      >
                        {/* Archivos multimodales adjuntos en el mensaje del usuario */}
                        {msg.attachments && msg.attachments.length > 0 && (
                          <div className="flex flex-wrap gap-2.5 mb-3">
                            {msg.attachments.map((att) => {
                              const fileUrl = getAttachmentUrl(att.local_path);
                              if (att.file_type === "image") {
                                return (
                                  <a
                                    key={att.id}
                                    href={fileUrl}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="block rounded-xl overflow-hidden border border-[#333537] hover:border-[#4b90ff] transition-colors"
                                  >
                                    {/* eslint-disable-next-line @next/next/no-img-element */}
                                    <img
                                      src={fileUrl}
                                      alt={att.file_name}
                                      className="max-h-48 max-w-xs object-cover"
                                    />
                                  </a>
                                );
                              }
                              if (att.file_type === "audio") {
                                return (
                                  <div
                                    key={att.id}
                                    className="flex flex-col gap-1.5 p-2.5 rounded-xl bg-[#131314] border border-[#333537]"
                                  >
                                    <div className="flex items-center gap-2 text-xs text-purple-300">
                                      <Music className="w-3.5 h-3.5" />
                                      <span className="truncate max-w-[200px]">
                                        {att.file_name}
                                      </span>
                                    </div>
                                    <audio
                                      controls
                                      src={fileUrl}
                                      className="h-8 max-w-[240px]"
                                    />
                                  </div>
                                );
                              }
                              return (
                                <a
                                  key={att.id}
                                  href={fileUrl}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="flex items-center gap-2 px-3 py-2 rounded-xl bg-[#131314] border border-[#333537] hover:border-[#4b90ff] text-xs text-blue-300"
                                >
                                  <FileText className="w-4 h-4 shrink-0" />
                                  <span className="truncate max-w-[200px]">
                                    {att.file_name}
                                  </span>
                                </a>
                              );
                            })}
                          </div>
                        )}

                        {/* Si es mensaje IA en modo A/B pendiente de selección -> mostrar ABComparisonSelector */}
                        {showABSelector ? (
                          <ABComparisonSelector
                            message={msg}
                            onSelectCandidate={handleSelectABCandidate}
                            onSpeakText={handleSpeakText}
                            speakingKey={speakingKey}
                          />
                        ) : (
                          <>
                            {/* Insignia si esta respuesta provino de una elección A/B */}
                            {!isUser && msg.is_ab_test && msg.selected_candidate && (
                              <div className="mb-2 inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-[11px]">
                                <CheckCircle2 className="w-3 h-3" />
                                <span>
                                  Elegiste Respuesta {msg.selected_candidate} (
                                  {msg.selected_candidate === "A"
                                    ? "Enfoque Directo"
                                    : "Enfoque Detallado"}
                                  )
                                </span>
                              </div>
                            )}

                            {/* Contenido Markdown */}
                            <div className="gemini-markdown text-sm sm:text-[15px] text-[#e3e3e3]">
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                {msg.content}
                              </ReactMarkdown>
                            </div>

                            {/* Barra de acciones debajo de cada respuesta de la IA: Altavoz TTS + Regenerar comparando 2 opciones */}
                            {!isUser && (
                              <div className="flex flex-wrap items-center gap-2 mt-3 pt-2">
                                <button
                                  type="button"
                                  onClick={() =>
                                    handleSpeakText(msg.content, speechId)
                                  }
                                  title={
                                    speakingKey === speechId
                                      ? "Detener lectura en voz alta"
                                      : "Escuchar respuesta en voz alta"
                                  }
                                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium border transition-colors ${
                                    speakingKey === speechId
                                      ? "bg-red-500/20 border-red-500/40 text-red-300"
                                      : "bg-[#1e1f20] hover:bg-[#282a2c] border-[#333537] text-[#9aa0a6] hover:text-white"
                                  }`}
                                >
                                  {speakingKey === speechId ? (
                                    <>
                                      <Square className="w-3.5 h-3.5 fill-current" />
                                      <span>Detener voz</span>
                                    </>
                                  ) : (
                                    <>
                                      <Volume2 className="w-3.5 h-3.5" />
                                      <span>Escuchar en voz alta</span>
                                    </>
                                  )}
                                </button>

                                <button
                                  type="button"
                                  disabled={isSending}
                                  onClick={() => handleRegenerateWithComparison(idx)}
                                  title="Generar 2 respuestas candidatas (A concisa vs B detallada) para esta consulta"
                                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium bg-[#1e1f20] hover:bg-[#282a2c] border border-[#333537] hover:border-purple-500/50 text-[#9aa0a6] hover:text-purple-200 disabled:opacity-50 transition-colors"
                                >
                                  <SplitSquareHorizontal className="w-3.5 h-3.5 text-purple-400" />
                                  <span>Regenerar comparando 2 opciones</span>
                                </button>
                              </div>
                            )}

                            {/* Opciones de seguimiento clicables (2 o 3 opciones al final de cada respuesta IA) */}
                            {!isUser &&
                              msg.follow_up_options &&
                              msg.follow_up_options.length > 0 && (
                                <FollowUpOptions
                                  options={msg.follow_up_options}
                                  disabled={isSending}
                                  onSelectOption={(optionText) =>
                                    void handleSendUserMessage({
                                      content: optionText,
                                      files: [],
                                      forceCompare: false,
                                    })
                                  }
                                />
                              )}
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })
            )}

            {/* Indicador de carga mientras Ollama procesa */}
            {isSending && (
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-[#4b90ff] to-[#a855f7] flex items-center justify-center shrink-0 animate-pulse">
                  <Sparkles className="w-4 h-4 text-white" />
                </div>
                <div className="rounded-2xl bg-[#1e1f20] border border-[#333537] px-4 py-3 text-xs sm:text-sm text-[#9aa0a6] flex items-center gap-2.5">
                  <Loader2 className="w-4 h-4 animate-spin text-[#4b90ff]" />
                  <span>
                    {compareMode || (userTurnCount > 0 && userTurnCount % 3 === 0)
                      ? "Generando 2 respuestas candidatas (A concisa y B detallada) con Ollama..."
                      : "LocalGem está pensando y preparando opciones de seguimiento..."}
                  </span>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </main>

        {/* Barra inferior Multimodal con Archivos, Voz en vivo y botón Comparar 2 respuestas */}
        <MultimodalInputBar
          onSendMessage={handleSendUserMessage}
          isLoading={isSending}
          compareMode={compareMode}
          onToggleCompareMode={setCompareMode}
        />
      </div>
    </div>
  );
}
