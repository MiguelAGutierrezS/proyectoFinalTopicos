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
  Zap,
  Plug,
  ChevronDown,
  ChevronUp,
  Play,
  Plus,
  X,
  GitBranch,
  ArrowDown,
  Copy,
  Check,
} from "lucide-react";

import Sidebar from "@/components/Sidebar";
import ABComparisonSelector from "@/components/ABComparisonSelector";
import FollowUpOptions from "@/components/FollowUpOptions";
import MultimodalInputBar from "@/components/MultimodalInputBar";
import { geminiMarkdownComponents } from "@/lib/markdownComponents";
import {
  CandidateChoice,
  ChatSummary,
  GraphSchemaResponse,
  MCPCallResponse,
  MCPToolDefinition,
  Message,
  OllamaModelInfo,
  PreferenceSummary,
  SkillInfo,
  callMCPTool,
  createChat,
  createSkill,
  deleteChat,
  fetchChatById,
  fetchChats,
  fetchGraphSchema,
  fetchHealth,
  fetchMCPTools,
  fetchModels,
  fetchPreferenceSummary,
  fetchSkills,
  getAttachmentUrl,
  selectABCandidate,
  sendMessage,
  updateChatTitle,
} from "@/lib/api";

const DEFAULT_LANGGRAPH_SCHEMA: GraphSchemaResponse = {
  engine: "LangGraph StateGraph",
  version: "2.1.0",
  state_schema: "LocalGemGraphState",
  nodes: [
    {
      id: "node_load_context",
      label: "Carga de Contexto y Preferencias",
      description:
        "Resuelve el modelo activo en Ollama, carga el estilo preferido del usuario y evalúa la condición de Test A/B.",
    },
    {
      id: "node_skill_router",
      label: "Enrutador de Skills (SKILL.md)",
      description:
        "Detecta e inyecta habilidades especializadas por selección manual, comando slash o triggers léxicos.",
    },
    {
      id: "node_mcp_executor",
      label: "Ejecutor Híbrido MCP",
      description:
        "Invoca herramientas locales del Model Context Protocol (Calculadora, SQLite, Reloj, Workspace, Wikipedia).",
    },
    {
      id: "node_vision_bridge",
      label: "Vision Bridge (2 Etapas)",
      description:
        "Extrae descripciones visuales con moondream:latest y conmuta la síntesis en español a llama3.2.",
    },
    {
      id: "node_context_compactor",
      label: "Compactador de Contexto",
      description:
        "Resume historiales largos (>= 14 mensajes) para proteger la ventana de contexto y la memoria RAM.",
    },
    {
      id: "node_prompt_builder",
      label: "Constructor de Prompt Multimodal",
      description:
        "Ensambla el System Prompt adaptativo, adjuntos multimodales, resultados MCP y anclaje de intención.",
    },
    {
      id: "node_generate_standard",
      label: "Generador Estándar Ollama",
      description:
        "Ejecuta inferencia simple adaptada al estilo histórico del usuario (conciso o detallado).",
    },
    {
      id: "node_generate_ab",
      label: "Generador Dual A/B",
      description:
        "Genera en paralelo controlado Candidata A (concisa, temp 0.3) y Candidata B (detallada, temp 0.8).",
    },
    {
      id: "node_parse_and_fallback",
      label: "Parser Resiliente de Opciones",
      description:
        "Extrae ---FOLLOW_UP_OPTIONS--- con 3 niveles de fallback determinista garantizando 2 a 3 sugerencias.",
    },
  ],
  mermaid: `flowchart TD
    START((START)) --> N1["1. node_load_context\\n(Modelo + Preferencia Estilo + Modo A/B)"]
    N1 --> N2["2. node_skill_router\\n(Resolución SKILL.md Manual / Auto)"]
    N2 --> C_MCP{"¿enable_mcp == True?"}
    C_MCP -- "Sí" --> N3["3. node_mcp_executor\\n(Router Híbrido MCP + tools/call)"]
    C_MCP -- "No" --> C_VIS{"¿Hay imágenes\\nsin Análisis Visual?"}
    N3 --> C_VIS
    C_VIS -- "Sí" --> N4["4. node_vision_bridge\\n(Etapa 1: moondream -> Etapa 2: llama3.2)"]
    C_VIS -- "No" --> C_COMP{"¿Historial >= 14 msgs\\no >= 3200 tokens?"}
    N4 --> C_COMP
    C_COMP -- "Sí" --> N5["5. node_context_compactor\\n(Resumen Ejecutivo de Mensajes Antiguos)"]
    C_COMP -- "No" --> N6["6. node_prompt_builder\\n(Ensamblaje System Prompt + Payload Multimodal + MCP)"]
    N5 --> N6
    N6 --> C_AB{"¿is_ab_test == True?\\n(force_ab o msg_count % 3 == 0)"}
    C_AB -- "No (Estándar)" --> N7A["7A. node_generate_standard\\n(Inferencia Adaptativa con Ollama)"]
    C_AB -- "Sí (Modo A/B)" --> N7B["7B. node_generate_ab\\n(Inferencia Dual: Candidata A temp=0.3 / B temp=0.8)"]
    N7A --> N8["8. node_parse_and_fallback\\n(Parser ---FOLLOW_UP_OPTIONS--- + Fallback Determinista)"]
    N7B --> N8
    N8 --> END((END))`,
};

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

  // Estado de Skills (SKILL.md), MCP (Model Context Protocol Local) y Grafo LangGraph
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [selectedSkillId, setSelectedSkillId] = useState<string>("auto");
  const [mcpTools, setMcpTools] = useState<MCPToolDefinition[]>([]);
  const [enableMcp, setEnableMcp] = useState<boolean>(true);
  const [graphSchema, setGraphSchema] = useState<GraphSchemaResponse>(
    DEFAULT_LANGGRAPH_SCHEMA
  );
  const [copiedMermaid, setCopiedMermaid] = useState<boolean>(false);
  const [showSkillsMcpModal, setShowSkillsMcpModal] = useState<boolean>(false);
  const [activeHubTab, setActiveHubTab] = useState<
    "skills" | "mcp" | "langgraph"
  >("skills");

  // Estado para expandir trazas MCP en los mensajes del chat
  const [expandedMcpTraceKey, setExpandedMcpTraceKey] = useState<string | null>(
    null
  );

  // Estado para probar herramientas MCP en vivo desde el modal
  const [mcpTestOutput, setMcpTestOutput] = useState<MCPCallResponse | null>(
    null
  );
  const [isTestingMcp, setIsTestingMcp] = useState<string | null>(null);

  // Estado para crear una nueva Skill en caliente (SKILL.md)
  const [newSkillId, setNewSkillId] = useState("");
  const [newSkillName, setNewSkillName] = useState("");
  const [newSkillDesc, setNewSkillDesc] = useState("");
  const [newSkillTriggers, setNewSkillTriggers] = useState("");
  const [newSkillInstructions, setNewSkillInstructions] = useState("");
  const [isCreatingSkill, setIsCreatingSkill] = useState(false);

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

  // Carga inicial de modelos, salud de Ollama, preferencias, Skills, MCP y lista de chats en SQLite
  const loadInitialData = useCallback(async () => {
    setIsLoadingChats(true);
    try {
      const [
        chatsData,
        modelsData,
        healthData,
        prefData,
        skillsData,
        mcpData,
        graphData,
      ] = await Promise.allSettled([
        fetchChats(),
        fetchModels(),
        fetchHealth(),
        fetchPreferenceSummary(),
        fetchSkills(),
        fetchMCPTools(),
        fetchGraphSchema(),
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

      if (skillsData.status === "fulfilled") {
        setSkills(skillsData.value.skills);
      }

      if (mcpData.status === "fulfilled") {
        setMcpTools(mcpData.value.tools);
      }

      if (graphData.status === "fulfilled" && graphData.value?.nodes?.length) {
        setGraphSchema(graphData.value);
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

  // Renombrar un chat existente en SQLite (REQ-UI-01)
  const handleRenameChat = async (chatId: string, newTitle: string) => {
    setErrorBanner(null);
    try {
      await updateChatTitle(chatId, newTitle);
      const updatedList = await fetchChats();
      setChats(updatedList);
    } catch (err) {
      setErrorBanner(
        err instanceof Error
          ? err.message
          : "No se pudo actualizar el título del chat."
      );
    }
  };

  // Enviar mensaje (con soporte de Vision Bridge, Skills y MCP)
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
        skillId: selectedSkillId,
        enableMcp,
        files,
      });

      // Reemplazar el mensaje optimista con los mensajes reales persistidos en SQLite
      setMessages((prev) => [
        ...prev.filter((m) => m.id !== tempUserMsg.id),
        response.user_message,
        response.assistant_message,
      ]);

      // Refrescar lista de chats en el sidebar
      const updatedChats = await fetchChats();
      setChats(updatedChats);
    } catch (err) {
      setErrorBanner(
        err instanceof Error
          ? err.message
          : "Ocurrió un error al procesar tu mensaje."
      );
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

  // Ejecutar prueba rápida de una herramienta MCP desde el modal
  const handleTestMcpTool = async (toolName: string) => {
    setIsTestingMcp(toolName);
    try {
      let sampleArgs: Record<string, unknown> = {};
      if (toolName === "mcp_calculator") {
        sampleArgs = { expression: "sqrt(144) * 5 + 28" };
      } else if (toolName === "mcp_sqlite_inspector") {
        sampleArgs = { query_type: "summary" };
      } else if (toolName === "mcp_workspace_reader") {
        sampleArgs = { action: "list", path: "specs" };
      } else if (toolName === "mcp_wikipedia_search") {
        sampleArgs = { query: "Inteligencia artificial", lang: "es" };
      }
      const res = await callMCPTool(toolName, sampleArgs);
      setMcpTestOutput(res);
    } catch (err) {
      setErrorBanner(
        err instanceof Error ? err.message : "Error al ejecutar herramienta MCP"
      );
    } finally {
      setIsTestingMcp(null);
    }
  };

  // Crear nueva Skill SKILL.md en caliente
  const handleCreateCustomSkill = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newSkillId.trim() || !newSkillName.trim() || !newSkillInstructions.trim()) {
      return;
    }
    setIsCreatingSkill(true);
    try {
      const triggersList = newSkillTriggers
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const created = await createSkill({
        id: newSkillId.trim(),
        name: newSkillName.trim(),
        description: newSkillDesc.trim() || "Skill personalizada en SKILL.md",
        icon: "Sparkles",
        triggers: triggersList,
        recommended_tools: ["mcp_workspace_reader"],
        instructions: newSkillInstructions.trim(),
      });
      const updated = await fetchSkills();
      setSkills(updated.skills);
      setSelectedSkillId(created.id);
      setNewSkillId("");
      setNewSkillName("");
      setNewSkillDesc("");
      setNewSkillTriggers("");
      setNewSkillInstructions("");
    } catch (err) {
      setErrorBanner(
        err instanceof Error ? err.message : "No se pudo crear la Skill."
      );
    } finally {
      setIsCreatingSkill(false);
    }
  };

  const userTurnCount = messages.filter((m) => m.role === "user").length;
  const turnsUntilAutoAB = 3 - (userTurnCount % 3);

  const getSkillNameById = (skillId?: string | null) => {
    if (!skillId) return null;
    const found = skills.find((s) => s.id === skillId);
    return found ? found.name : skillId;
  };

  return (
    <div className="flex h-screen w-screen bg-[#131314] text-[#e3e3e3] overflow-hidden">
      {/* Barra lateral izquierda */}
      <Sidebar
        chats={chats}
        activeChatId={activeChatId}
        onSelectChat={handleSelectChat}
        onNewChat={handleNewChat}
        onDeleteChat={handleDeleteChat}
        onRenameChat={handleRenameChat}
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
        skillsCount={skills.length}
        mcpToolsCount={mcpTools.length}
        onOpenSkillsMcpModal={() => setShowSkillsMcpModal(true)}
      />

      {/* Área principal */}
      <div className="flex-1 flex flex-col h-screen min-w-0 bg-[#131314]">
        {/* Barra superior de estado */}
        <header className="flex items-center justify-between px-4 sm:px-6 py-3 border-b border-[#333537]/60 bg-[#131314]/90 backdrop-blur-md z-10">
          <div className="flex items-center gap-3 min-w-0">
            <h1 className="text-sm sm:text-base font-semibold truncate text-white">
              {chats.find((c) => c.id === activeChatId)?.title || "LocalGem Chat"}
            </h1>
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
              <div className="flex flex-col items-center justify-center text-center py-10 sm:py-16 px-4">
                <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-[#4b90ff] via-indigo-500 to-[#a855f7] flex items-center justify-center shadow-xl shadow-blue-500/20 mb-5">
                  <Sparkles className="w-7 h-7 text-white" />
                </div>

                <h2 className="text-2xl sm:text-4xl font-bold tracking-tight bg-gradient-to-r from-[#4b90ff] via-indigo-300 to-[#a855f7] bg-clip-text text-transparent mb-3">
                  Hola, soy LocalGem 2.0
                </h2>
                <p className="text-sm sm:text-base text-[#9aa0a6] max-w-xl mb-8">
                  Tu clon de Google Gemini 100% local con{" "}
                  <strong className="text-[#e3e3e3]">Vision Bridge</strong>{" "}
                  (moondream + llama3.2),{" "}
                  <strong className="text-amber-300">Skills (SKILL.md)</strong> y{" "}
                  <strong className="text-emerald-300">Herramientas MCP</strong>.
                </p>

                {/* Tarjetas de sugerencias iniciales que demuestran Skills, MCP y Multimodal */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 w-full max-w-3xl text-left">
                  {[
                    {
                      title: "Herramientas MCP en vivo",
                      prompt:
                        "¿Qué hora exacta es en mi sistema, cuánto es sqrt(144) * 25 y cuántos chats hay guardados en SQLite?",
                      icon: Plug,
                    },
                    {
                      title: "Skill: Arquitecto de Código",
                      prompt:
                        "/code-architect Diseña un endpoint en FastAPI con SQLAlchemy y explica su flujo",
                      icon: Zap,
                    },
                    {
                      title: "Comparar 2 respuestas (A/B)",
                      prompt:
                        "Compara las ventajas de SQLite frente a PostgreSQL para aplicaciones locales con IA",
                      icon: SplitSquareHorizontal,
                      forceCompare: true,
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
                const activeSkillLabel = getSkillNameById(msg.active_skill);
                const mcpTraces = msg.mcp_tool_calls || [];
                // Solo mostrar opciones de seguimiento en la última respuesta del asistente y cuando no se esté procesando una nueva pregunta
                const isLatestAssistantMessage =
                  !isUser && idx === messages.length - 1 && !isSending;

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
                        {/* Badges superiores del asistente: Skill activa (`REQ-SKILL-04`) y Herramientas MCP (`REQ-MCP-05`) */}
                        {!isUser &&
                          (activeSkillLabel || mcpTraces.length > 0) && (
                            <div className="flex flex-wrap items-center gap-1.5 mb-2.5">
                              {activeSkillLabel && (
                                <span
                                  title={`Skill modular aplicada: ${msg.active_skill}`}
                                  className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/35 text-amber-300 text-[11px] font-medium"
                                >
                                  <Zap className="w-3 h-3" />
                                  Skill: {activeSkillLabel}
                                </span>
                              )}

                              {mcpTraces.map((trace, tIdx) => {
                                const traceKey = `${msg.id}-mcp-${tIdx}`;
                                const isExpanded =
                                  expandedMcpTraceKey === traceKey;
                                return (
                                  <div key={traceKey} className="inline-block">
                                    <button
                                      type="button"
                                      onClick={() =>
                                        setExpandedMcpTraceKey(
                                          isExpanded ? null : traceKey
                                        )
                                      }
                                      className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-500/35 text-emerald-300 text-[11px] font-medium transition-colors"
                                    >
                                      <Plug className="w-3 h-3" />
                                      <span>
                                        MCP: {trace.tool_name} (
                                        {trace.duration_ms}ms)
                                      </span>
                                      {isExpanded ? (
                                        <ChevronUp className="w-3 h-3" />
                                      ) : (
                                        <ChevronDown className="w-3 h-3" />
                                      )}
                                    </button>
                                  </div>
                                );
                              })}
                            </div>
                          )}

                        {/* Panel desplegable con el detalle de la herramienta MCP ejecutada */}
                        {!isUser &&
                          mcpTraces.map((trace, tIdx) => {
                            const traceKey = `${msg.id}-mcp-${tIdx}`;
                            if (expandedMcpTraceKey !== traceKey) return null;
                            return (
                              <div
                                key={`${traceKey}-detail`}
                                className="mb-3 p-3 rounded-xl bg-[#1a1b1e] border border-emerald-500/30 text-xs space-y-1.5 font-mono"
                              >
                                <div className="flex items-center justify-between text-emerald-300">
                                  <strong>
                                    🔌 Herramienta MCP Local: {trace.tool_name}
                                  </strong>
                                  <span>
                                    Estado: {trace.status.toUpperCase()} •{" "}
                                    {trace.duration_ms} ms
                                  </span>
                                </div>
                                <div className="text-[#9aa0a6]">
                                  Argumentos:{" "}
                                  <code className="text-blue-300">
                                    {JSON.stringify(trace.arguments)}
                                  </code>
                                </div>
                                <pre className="p-2 rounded-lg bg-[#131314] text-[#e3e3e3] whitespace-pre-wrap overflow-x-auto max-h-40">
                                  {trace.result_preview}
                                </pre>
                              </div>
                            );
                          })}

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

                            {/* Contenido Markdown con Syntax Highlighting (REQ-UI-05) */}
                            <div className="gemini-markdown text-sm sm:text-[15px] text-[#e3e3e3]">
                              <ReactMarkdown
                                remarkPlugins={[remarkGfm]}
                                components={geminiMarkdownComponents}
                              >
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

                            {/* Opciones de seguimiento clicables (solo en la última respuesta del asistente) */}
                            {isLatestAssistantMessage &&
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
                      : "LocalGem está procesando (Vision Bridge / Skills / MCP) y preparando opciones de seguimiento..."}
                  </span>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </main>

        {/* Barra inferior Multimodal con Archivos, Voz en vivo, Grabadora WAV, Selector Skills y Toggle MCP */}
        <MultimodalInputBar
          onSendMessage={handleSendUserMessage}
          isLoading={isSending}
          compareMode={compareMode}
          onToggleCompareMode={setCompareMode}
          skills={skills}
          selectedSkillId={selectedSkillId}
          onSelectSkillId={setSelectedSkillId}
          enableMcp={enableMcp}
          onToggleMcp={setEnableMcp}
          onOpenSkillsMcpModal={() => setShowSkillsMcpModal(true)}
        />
      </div>

      {/* Modal Interactivo de Skills (SKILL.md), Herramientas MCP Locales y Arquitectura LangGraph */}
      {showSkillsMcpModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4">
          <div className="w-full max-w-4xl max-h-[90vh] flex flex-col rounded-3xl bg-[#1e1f20] border border-[#333537] shadow-2xl overflow-hidden">
            {/* Cabecera del Modal */}
            <div className="flex flex-wrap items-center justify-between gap-2 px-6 py-4 border-b border-[#333537]">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => setActiveHubTab("skills")}
                  className={`flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-semibold cursor-pointer transition-all ${
                    activeHubTab === "skills"
                      ? "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                      : "text-[#9aa0a6] hover:text-white"
                  }`}
                >
                  <Zap className="w-4 h-4" />
                  <span>Skills (SKILL.md) ({skills.length})</span>
                </button>

                <button
                  type="button"
                  onClick={() => setActiveHubTab("mcp")}
                  className={`flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-semibold cursor-pointer transition-all ${
                    activeHubTab === "mcp"
                      ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                      : "text-[#9aa0a6] hover:text-white"
                  }`}
                >
                  <Plug className="w-4 h-4" />
                  <span>Herramientas MCP ({mcpTools.length})</span>
                </button>

                <button
                  type="button"
                  onClick={() => setActiveHubTab("langgraph")}
                  className={`flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-semibold cursor-pointer transition-all ${
                    activeHubTab === "langgraph"
                      ? "bg-purple-500/20 text-purple-300 border border-purple-500/40 shadow-sm"
                      : "text-[#9aa0a6] hover:text-white"
                  }`}
                >
                  <GitBranch className="w-4 h-4" />
                  <span>
                    Grafo LangGraph ({graphSchema.nodes.length} Nodos)
                  </span>
                </button>
              </div>

              <button
                type="button"
                onClick={() => setShowSkillsMcpModal(false)}
                className="p-1.5 rounded-full text-[#9aa0a6] hover:text-white hover:bg-[#282a2c] cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Contenido del Modal */}
            <div className="flex-1 overflow-y-auto p-6 space-y-5">
              {activeHubTab === "skills" ? (
                <>
                  <p className="text-xs text-[#9aa0a6]">
                    Las <strong className="text-white">Skills</strong> son paquetes de conocimiento
                    definidos en archivos <code className="text-amber-300">backend/skills/*/SKILL.md</code> con
                    YAML Frontmatter. Puedes activarlas manualmente, usar comandos como{" "}
                    <code className="text-blue-300">/code-architect</code> o dejarlas en{" "}
                    <strong className="text-white">Auto-detección</strong>.
                  </p>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {skills.map((sk) => {
                      const isSelected = selectedSkillId === sk.id;
                      return (
                        <div
                          key={sk.id}
                          className={`p-4 rounded-2xl border transition-all flex flex-col justify-between ${
                            isSelected
                              ? "bg-amber-500/10 border-amber-500/50"
                              : "bg-[#131314] border-[#333537]"
                          }`}
                        >
                          <div>
                            <div className="flex items-center justify-between gap-2 mb-1.5">
                              <span className="font-semibold text-sm text-white flex items-center gap-1.5">
                                <Zap className="w-4 h-4 text-amber-400" />
                                {sk.name}
                              </span>
                              <code className="text-[11px] px-2 py-0.5 rounded bg-[#1e1f20] text-amber-300">
                                /{sk.id}
                              </code>
                            </div>
                            <p className="text-xs text-[#9aa0a6] mb-2">
                              {sk.description}
                            </p>
                            <div className="flex flex-wrap gap-1 mb-3">
                              {sk.triggers.slice(0, 5).map((trig) => (
                                <span
                                  key={trig}
                                  className="text-[10px] px-2 py-0.5 rounded-full bg-[#1e1f20] text-[#9aa0a6]"
                                >
                                  {trig}
                                </span>
                              ))}
                            </div>
                          </div>

                          <button
                            type="button"
                            onClick={() => {
                              setSelectedSkillId(isSelected ? "auto" : sk.id);
                              setShowSkillsMcpModal(false);
                            }}
                            className={`w-full py-1.5 px-3 rounded-xl text-xs font-medium cursor-pointer transition-colors ${
                              isSelected
                                ? "bg-amber-500 text-black font-semibold"
                                : "bg-[#282a2c] hover:bg-[#333537] text-white"
                            }`}
                          >
                            {isSelected
                              ? "✓ Skill Fijada (Clic para volver a Auto)"
                              : "Usar esta Skill"}
                          </button>
                        </div>
                      );
                    })}
                  </div>

                  {/* Formulario rápido para crear una nueva Skill SKILL.md en caliente */}
                  <form
                    onSubmit={handleCreateCustomSkill}
                    className="p-4 rounded-2xl bg-[#131314] border border-[#333537] space-y-3"
                  >
                    <h4 className="text-xs font-semibold text-amber-300 flex items-center gap-1.5">
                      <Plus className="w-4 h-4" />
                      Crear nueva Skill en caliente (crea backend/skills/id/SKILL.md)
                    </h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                      <input
                        type="text"
                        placeholder="ID (ej. cybersecurity-auditor)"
                        value={newSkillId}
                        onChange={(e) => setNewSkillId(e.target.value)}
                        className="px-3 py-2 rounded-xl bg-[#1e1f20] border border-[#333537] text-xs text-white"
                      />
                      <input
                        type="text"
                        placeholder="Nombre visible (ej. Auditor de Seguridad)"
                        value={newSkillName}
                        onChange={(e) => setNewSkillName(e.target.value)}
                        className="px-3 py-2 rounded-xl bg-[#1e1f20] border border-[#333537] text-xs text-white"
                      />
                    </div>
                    <input
                      type="text"
                      placeholder="Descripción corta y palabras clave separadas por coma (ej. seguridad, owasp, vulnerabilidad)"
                      value={newSkillTriggers}
                      onChange={(e) => {
                        setNewSkillTriggers(e.target.value);
                        setNewSkillDesc(e.target.value);
                      }}
                      className="w-full px-3 py-2 rounded-xl bg-[#1e1f20] border border-[#333537] text-xs text-white"
                    />
                    <textarea
                      rows={3}
                      placeholder="Instrucciones Markdown de la Skill (Directivas de rol, reglas y estructura de salida)..."
                      value={newSkillInstructions}
                      onChange={(e) => setNewSkillInstructions(e.target.value)}
                      className="w-full px-3 py-2 rounded-xl bg-[#1e1f20] border border-[#333537] text-xs text-white"
                    />
                    <button
                      type="submit"
                      disabled={isCreatingSkill}
                      className="px-4 py-2 rounded-xl bg-gradient-to-r from-[#4b90ff] to-[#a855f7] text-white text-xs font-medium hover:opacity-95 disabled:opacity-50 cursor-pointer"
                    >
                      {isCreatingSkill
                        ? "Guardando SKILL.md..."
                        : "Guardar y Activar SKILL.md"}
                    </button>
                  </form>
                </>
              ) : activeHubTab === "mcp" ? (
                <>
                  <p className="text-xs text-[#9aa0a6]">
                    El <strong className="text-white">Hybrid MCP Router</strong> permite que modelos
                    locales pequeños (<code className="text-emerald-300">llama3.2</code>) ejecuten herramientas
                    reales del sistema antes de responder. Pulsa <strong>Probar en vivo</strong> en cualquiera
                    de las herramientas para verificar su funcionamiento:
                  </p>

                  <div className="space-y-2.5">
                    {mcpTools.map((tool) => (
                      <div
                        key={tool.name}
                        className="p-3.5 rounded-2xl bg-[#131314] border border-[#333537] flex flex-col sm:flex-row sm:items-center justify-between gap-3"
                      >
                        <div>
                          <div className="flex items-center gap-2">
                            <Plug className="w-4 h-4 text-emerald-400" />
                            <span className="font-semibold text-sm text-white">
                              {tool.title || tool.name}
                            </span>
                            <code className="text-[11px] px-2 py-0.5 rounded bg-[#1e1f20] text-emerald-300">
                              {tool.name}
                            </code>
                          </div>
                          <p className="text-xs text-[#9aa0a6] mt-1">
                            {tool.description}
                          </p>
                        </div>

                        <button
                          type="button"
                          onClick={() => void handleTestMcpTool(tool.name)}
                          disabled={isTestingMcp === tool.name}
                          className="shrink-0 inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 text-emerald-300 text-xs font-medium cursor-pointer transition-colors"
                        >
                          {isTestingMcp === tool.name ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Play className="w-3.5 h-3.5" />
                          )}
                          <span>Probar en vivo</span>
                        </button>
                      </div>
                    ))}
                  </div>

                  {mcpTestOutput && (
                    <div className="p-4 rounded-2xl bg-[#131314] border border-emerald-500/40 text-xs font-mono space-y-2">
                      <div className="flex items-center justify-between text-emerald-300">
                        <strong>
                          Resultado en vivo: {mcpTestOutput.tool_name}
                        </strong>
                        <span>{mcpTestOutput.duration_ms} ms</span>
                      </div>
                      <pre className="p-3 rounded-xl bg-[#1e1f20] text-[#e3e3e3] whitespace-pre-wrap overflow-x-auto max-h-52">
                        {mcpTestOutput.result}
                      </pre>
                    </div>
                  )}
                </>
              ) : (
                /* Pestaña Visual del Grafo de Estados LangGraph (`GET /api/graph/schema`) */
                <div className="space-y-5">
                  {/* Encabezado arquitectónico */}
                  <div className="p-4 rounded-2xl bg-gradient-to-r from-blue-500/10 via-indigo-500/10 to-purple-500/10 border border-purple-500/30 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <GitBranch className="w-4 h-4 text-purple-400" />
                        <h3 className="text-sm font-bold text-white">
                          {graphSchema.engine} — v{graphSchema.version}
                        </h3>
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-300 border border-purple-500/40 font-mono">
                          State: {graphSchema.state_schema}
                        </span>
                      </div>
                      <p className="text-xs text-[#9aa0a6] mt-1">
                        Orquestación agéntica basada en Máquina de Estados Finitos (
                        <code className="text-purple-300">specs/04-langgraph-architecture.md</code>
                        ) con {graphSchema.nodes.length} nodos de responsabilidad única y 4 aristas condicionales.
                      </p>
                    </div>

                    <button
                      type="button"
                      onClick={() => {
                        navigator.clipboard.writeText(graphSchema.mermaid);
                        setCopiedMermaid(true);
                        setTimeout(() => setCopiedMermaid(false), 2000);
                      }}
                      className="shrink-0 inline-flex items-center gap-1.5 px-3 py-2 rounded-xl bg-[#131314] hover:bg-[#282a2c] border border-[#333537] text-xs text-purple-300 cursor-pointer transition-colors"
                    >
                      {copiedMermaid ? (
                        <>
                          <Check className="w-3.5 h-3.5 text-emerald-400" />
                          <span className="text-emerald-300">¡Mermaid Copiado!</span>
                        </>
                      ) : (
                        <>
                          <Copy className="w-3.5 h-3.5" />
                          <span>Copiar Diagrama Mermaid</span>
                        </>
                      )}
                    </button>
                  </div>

                  {/* Flujo Visual Paso a Paso de los 9 Nodos y las 4 Aristas Condicionales */}
                  <div className="space-y-2.5">
                    <div className="flex items-center justify-between text-xs text-[#9aa0a6] px-1">
                      <span className="font-semibold uppercase tracking-wider text-white">
                        Topología en Vivo del StateGraph (START → 9 Nodos → END)
                      </span>
                      <span className="text-[11px] text-purple-300">
                        4 Aristas Condicionales Activas
                      </span>
                    </div>

                    <div className="space-y-2">
                      {graphSchema.nodes.map((node, index) => {
                        // Detectar si antes o después de este nodo hay una arista condicional clave
                        const conditionalBadge =
                          node.id === "node_mcp_executor"
                            ? "Arista Condicional 1: route_mcp_check (¿enable_mcp == True?)"
                            : node.id === "node_vision_bridge"
                            ? "Arista Condicional 2: route_vision_check (¿Hay imagen o modelo moondream?)"
                            : node.id === "node_context_compactor"
                            ? "Arista Condicional 3: route_compaction_check (¿Historial >= 14 msgs o >= 3200 tokens?)"
                            : node.id === "node_generate_standard"
                            ? "Arista Condicional 4 (Rama A): route_generation_mode -> Modo Estándar"
                            : node.id === "node_generate_ab"
                            ? "Arista Condicional 4 (Rama B): route_generation_mode -> Modo Dual A/B (cada 3 msgs o manual)"
                            : null;

                        return (
                          <React.Fragment key={node.id}>
                            {conditionalBadge && (
                              <div className="flex items-center gap-2 pl-4 py-1 text-[11px] text-amber-300 font-mono">
                                <ArrowDown className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                                <span className="px-2.5 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/35">
                                  ⚡ {conditionalBadge}
                                </span>
                              </div>
                            )}

                            <div className="p-3.5 rounded-2xl bg-[#131314] border border-[#333537] hover:border-purple-500/40 transition-colors flex items-start justify-between gap-3">
                              <div className="flex items-start gap-3">
                                <div className="w-7 h-7 rounded-xl bg-gradient-to-br from-[#4b90ff]/25 to-[#a855f7]/25 border border-purple-500/40 flex items-center justify-center text-xs font-bold text-purple-300 shrink-0 mt-0.5">
                                  {index + 1}
                                </div>
                                <div>
                                  <div className="flex flex-wrap items-center gap-2">
                                    <span className="font-semibold text-sm text-white">
                                      {node.label}
                                    </span>
                                    <code className="text-[11px] px-2 py-0.5 rounded bg-[#1e1f20] text-blue-300 border border-[#333537]">
                                      {node.id}
                                    </code>
                                  </div>
                                  <p className="text-xs text-[#9aa0a6] mt-1">
                                    {node.description}
                                  </p>
                                </div>
                              </div>

                              <span className="shrink-0 text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 font-mono">
                                Activo
                              </span>
                            </div>
                          </React.Fragment>
                        );
                      })}
                    </div>
                  </div>

                  {/* Bloque con la definición oficial en código Mermaid devuelta por GET /api/graph/schema */}
                  <div className="p-4 rounded-2xl bg-[#131314] border border-[#333537] space-y-2">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-semibold text-purple-300">
                        Especificación Mermaid en Vivo (GET /api/graph/schema)
                      </span>
                      <span className="text-[11px] text-[#9aa0a6] font-mono">
                        flowchart TD
                      </span>
                    </div>
                    <pre className="p-3 rounded-xl bg-[#1e1f20] text-[11px] text-[#e3e3e3] font-mono whitespace-pre-wrap overflow-x-auto max-h-56">
                      {graphSchema.mermaid}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
