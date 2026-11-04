"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  Plus,
  MessageSquare,
  Trash2,
  Edit3,
  Cpu,
  SplitSquareHorizontal,
  Sparkles,
  RefreshCw,
  PanelLeftClose,
  PanelLeftOpen,
  Zap,
  Plug,
  ChevronUp,
  Check,
  Eye,
} from "lucide-react";
import { ChatSummary, OllamaModelInfo } from "@/lib/api";

export interface SidebarProps {
  chats: ChatSummary[];
  activeChatId: string | null;
  onSelectChat: (chatId: string) => void;
  onNewChat: () => void;
  onDeleteChat: (chatId: string) => void;
  onRenameChat?: (chatId: string, newTitle: string) => Promise<void>;
  models: OllamaModelInfo[];
  selectedModel: string;
  onSelectModel: (modelName: string) => void;
  onRefreshModels?: () => void;
  ollamaReachable?: boolean;
  compareMode: boolean;
  onToggleCompareMode: (enabled: boolean) => void;
  isOpen?: boolean;
  onToggleSidebar?: () => void;
  isLoadingChats?: boolean;
  skillsCount?: number;
  mcpToolsCount?: number;
  onOpenSkillsMcpModal?: () => void;
}

/**
 * Provee etiqueta y descripción concisa para cada modelo de Ollama en el selector.
 */
function getModelDetails(modelName: string): {
  label: string;
  badge?: string;
  description: string;
  iconType: "vision" | "main" | "fast" | "default";
} {
  const lower = modelName.toLowerCase();
  if (lower.includes("moondream") || lower.includes("vision") || lower.includes("llava")) {
    return {
      label: modelName,
      badge: "Detector de imagen",
      description: "Análisis y reconocimiento visual de fotos / diagramas",
      iconType: "vision",
    };
  }
  if (lower.includes("1b")) {
    return {
      label: modelName,
      badge: "Ultra-rápido",
      description: "Respuestas veloces con mínimo consumo de RAM",
      iconType: "fast",
    };
  }
  if (lower.includes("llama3.2") || lower.includes("3b")) {
    return {
      label: modelName,
      badge: "Recomendado",
      description: "Cerebro principal: texto, código, razonamiento y A/B",
      iconType: "main",
    };
  }
  return {
    label: modelName,
    description: "Modelo conversacional local de Ollama",
    iconType: "default",
  };
}

export default function Sidebar({
  chats,
  activeChatId,
  onSelectChat,
  onNewChat,
  onDeleteChat,
  onRenameChat,
  models,
  selectedModel,
  onSelectModel,
  onRefreshModels,
  ollamaReachable = true,
  compareMode,
  onToggleCompareMode,
  isOpen = true,
  onToggleSidebar,
  isLoadingChats = false,
  skillsCount = 4,
  mcpToolsCount = 5,
  onOpenSkillsMcpModal,
}: SidebarProps) {
  const [editingChatId, setEditingChatId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState<string>("");
  const [isModelDropdownOpen, setIsModelDropdownOpen] = useState(false);
  const modelDropdownRef = useRef<HTMLDivElement | null>(null);

  // Cerrar menú desplegable al hacer clic fuera
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        modelDropdownRef.current &&
        !modelDropdownRef.current.contains(event.target as Node)
      ) {
        setIsModelDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  const handleStartRename = (chat: ChatSummary, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    setEditingChatId(chat.id);
    setEditingTitle(chat.title);
  };

  const handleConfirmRename = async (chatId: string, originalTitle: string) => {
    const trimmed = editingTitle.trim();
    setEditingChatId(null);
    if (!trimmed || trimmed === originalTitle) return;
    if (onRenameChat) {
      await onRenameChat(chatId, trimmed);
    }
  };

  const displayModels =
    models.length > 0
      ? models
      : [
          { name: "llama3.2:latest" },
          { name: "llama3.2:1b" },
          { name: "moondream:latest" },
        ];

  const currentDetails = getModelDetails(selectedModel || "llama3.2:latest");

  if (!isOpen) {
    return (
      <aside className="flex flex-col items-center justify-between py-4 px-2 bg-[#1e1f20] border-r border-[#333537]/80 w-16 shrink-0 h-screen select-none transition-all duration-200">
        <div className="flex flex-col items-center gap-4">
          {onToggleSidebar && (
            <button
              type="button"
              onClick={onToggleSidebar}
              title="Expandir barra lateral"
              className="p-2.5 rounded-full text-[#9aa0a6] hover:text-white hover:bg-[#282a2c] cursor-pointer transition-colors"
            >
              <PanelLeftOpen className="w-5 h-5" />
            </button>
          )}

          <button
            type="button"
            onClick={onNewChat}
            title="Nuevo chat"
            className="p-3 rounded-full bg-gradient-to-r from-[#4b90ff] to-[#a855f7] text-white shadow-lg hover:opacity-95 cursor-pointer transition-all"
          >
            <Plus className="w-5 h-5" />
          </button>

          {onOpenSkillsMcpModal && (
            <button
              type="button"
              onClick={onOpenSkillsMcpModal}
              title="Skills (SKILL.md) y Herramientas MCP"
              className="p-2.5 rounded-xl bg-[#131314]/80 border border-[#333537] text-amber-400 hover:text-white cursor-pointer transition-colors"
            >
              <Zap className="w-5 h-5" />
            </button>
          )}
        </div>

        <button
          type="button"
          onClick={() => onToggleCompareMode(!compareMode)}
          title="Modo Comparación (Elegir entre 2 respuestas)"
          className={`p-2.5 rounded-xl border cursor-pointer transition-all ${
            compareMode
              ? "bg-violet-500/20 border-violet-400/50 text-violet-300"
              : "bg-[#131314]/60 border-[#333537] text-[#9aa0a6] hover:text-white"
          }`}
        >
          <SplitSquareHorizontal className="w-5 h-5" />
        </button>
      </aside>
    );
  }

  return (
    <aside className="flex flex-col w-80 shrink-0 h-screen bg-[#1e1f20] border-r border-[#333537]/70 text-[#e3e3e3] select-none transition-all duration-200">
      {/* Cabecera de Marca + Botón Colapsar */}
      <div className="flex items-center justify-between px-4 pt-4 pb-2.5">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-[#4b90ff] via-indigo-500 to-[#a855f7] flex items-center justify-center shadow-md shadow-blue-500/20">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <div>
            <span className="font-semibold text-base tracking-tight bg-gradient-to-r from-blue-400 via-indigo-300 to-purple-400 bg-clip-text text-transparent">
              LocalGem Chat
            </span>
            <span className="block text-[10px] text-[#9aa0a6] leading-none">
              100% Local • LangGraph + Ollama + MCP
            </span>
          </div>
        </div>

        {onToggleSidebar && (
          <button
            type="button"
            onClick={onToggleSidebar}
            title="Contraer barra lateral"
            className="p-2 rounded-full text-[#9aa0a6] hover:text-white hover:bg-[#282a2c] cursor-pointer transition-colors"
          >
            <PanelLeftClose className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Acceso directo al Hub de Skills, Herramientas MCP y Grafo LangGraph */}
      {onOpenSkillsMcpModal && (
        <div className="px-4 py-2">
          <button
            type="button"
            onClick={onOpenSkillsMcpModal}
            className="w-full flex items-center justify-between px-3 py-2.5 rounded-xl bg-[#131314]/80 hover:bg-[#282a2c] border border-[#333537] hover:border-[#4b90ff]/50 text-xs cursor-pointer transition-all shadow-sm group"
          >
            <span className="flex items-center gap-1.5 font-medium text-[#e3e3e3] group-hover:text-white truncate">
              <Zap className="w-3.5 h-3.5 text-amber-400 shrink-0" />
              <span className="truncate">Skills, MCP &amp; Grafo</span>
            </span>
            <span className="flex items-center gap-1 text-[10px] text-[#9aa0a6] shrink-0">
              <span className="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30">
                {skillsCount} Skills
              </span>
              <span className="px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 inline-flex items-center gap-0.5">
                <Plug className="w-2.5 h-2.5" />
                {mcpToolsCount} MCP
              </span>
              <span className="px-1.5 py-0.5 rounded bg-purple-500/15 text-purple-300 border border-purple-500/30">
                LangGraph
              </span>
            </span>
          </button>
        </div>
      )}

      {/* Encabezado "Chats recientes" con el botón '+' en lugar del contador numérico */}
      <div className="px-4 pt-3 pb-1.5 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-[#9aa0a6]">
          Chats recientes
        </span>
        <button
          type="button"
          onClick={onNewChat}
          title="Crear un nuevo chat"
          className="p-1.5 rounded-lg text-[#9aa0a6] hover:text-white bg-[#131314] hover:bg-gradient-to-r hover:from-[#4b90ff]/20 hover:to-[#a855f7]/20 border border-[#333537] hover:border-[#4b90ff]/60 transition-all cursor-pointer flex items-center justify-center shadow-sm"
        >
          <Plus className="w-3.5 h-3.5 text-[#e3e3e3]" />
        </button>
      </div>

      {/* Lista desplazable de chats guardados en SQLite */}
      <div className="flex-1 overflow-y-auto px-3 py-1 space-y-1">
        {isLoadingChats ? (
          <div className="space-y-2 px-1 py-2">
            {[1, 2, 3].map((idx) => (
              <div
                key={idx}
                className="h-10 rounded-xl bg-[#282a2c]/60 animate-pulse"
              />
            ))}
          </div>
        ) : chats.length === 0 ? (
          <div className="text-center py-8 px-3 rounded-2xl bg-[#131314]/40 border border-[#333537]/50 my-2">
            <MessageSquare className="w-6 h-6 text-[#9aa0a6] mx-auto mb-2 opacity-60" />
            <p className="text-xs text-[#9aa0a6]">
              Aún no hay conversaciones guardadas.
            </p>
            <p className="text-[11px] text-[#9aa0a6]/70 mt-1">
              Envía un mensaje o pulsa el botón &ldquo;+&rdquo;.
            </p>
          </div>
        ) : (
          chats.map((chat) => {
            const isSelected = chat.id === activeChatId;
            return (
              <div
                key={chat.id}
                onClick={() => onSelectChat(chat.id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelectChat(chat.id);
                  }
                }}
                className={`group flex items-center justify-between gap-2 px-3 py-2.5 rounded-xl text-sm cursor-pointer transition-all ${
                  isSelected
                    ? "bg-gradient-to-r from-[#4b90ff]/20 to-[#a855f7]/20 text-white border border-blue-500/40 font-medium"
                    : "text-[#e3e3e3]/90 hover:bg-[#282a2c] border border-transparent"
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0 flex-1">
                  <MessageSquare
                    className={`w-4 h-4 shrink-0 ${
                      isSelected ? "text-[#4b90ff]" : "text-[#9aa0a6]"
                    }`}
                  />

                  {editingChatId === chat.id ? (
                    <input
                      autoFocus
                      type="text"
                      value={editingTitle}
                      maxLength={100}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => setEditingTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          void handleConfirmRename(chat.id, chat.title);
                        } else if (e.key === "Escape") {
                          setEditingChatId(null);
                        }
                      }}
                      onBlur={() => void handleConfirmRename(chat.id, chat.title)}
                      className="flex-1 bg-[#131314] text-xs sm:text-sm text-white px-2 py-0.5 rounded border border-[#4b90ff] focus:outline-none"
                    />
                  ) : (
                    <div className="flex items-center gap-1.5 min-w-0 flex-1">
                      <span
                        className="truncate text-xs sm:text-sm flex-1 select-none"
                        title={`${chat.title || "Nuevo Chat"} (Doble clic para renombrar)`}
                        onDoubleClick={(e) => handleStartRename(chat, e)}
                      >
                        {chat.title || "Nuevo Chat"}
                      </span>
                      {chat.is_context_compacted && (
                        <span
                          title="Memoria compactada activa (Context Compactor)"
                          className="shrink-0 text-[10px] px-1.5 py-0.2 rounded-full bg-blue-500/15 border border-blue-500/30 text-blue-300 font-mono"
                        >
                          🧠
                        </span>
                      )}
                    </div>
                  )}
                </div>

                {editingChatId !== chat.id && (
                  <div className="flex items-center gap-0.5 shrink-0">
                    <button
                      type="button"
                      onClick={(e) => handleStartRename(chat, e)}
                      title="Renombrar este chat"
                      aria-label={`Renombrar chat ${chat.title}`}
                      className="opacity-0 group-hover:opacity-80 hover:opacity-100 p-1.5 rounded-lg text-[#9aa0a6] hover:text-[#4b90ff] hover:bg-blue-500/15 cursor-pointer transition-all"
                    >
                      <Edit3 className="w-3.5 h-3.5" />
                    </button>

                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteChat(chat.id);
                      }}
                      title="Eliminar este chat"
                      aria-label={`Eliminar chat ${chat.title}`}
                      className="opacity-60 group-hover:opacity-100 p-1.5 rounded-lg text-[#9aa0a6] hover:text-red-400 hover:bg-red-500/15 cursor-pointer transition-colors"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Panel Inferior: Selector de Modelo Ollama */}
      <div className="p-3.5 border-t border-[#333537]/80 bg-[#131314]/50">
        {/* Selector personalizado de Modelo Local de Ollama con descripción e icono */}
        <div className="space-y-1.5 relative" ref={modelDropdownRef}>
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-xs font-medium text-[#9aa0a6]">
              <Cpu className="w-3.5 h-3.5 text-[#4b90ff]" />
              <span>Modelo Ollama Local</span>
            </span>

            <div className="flex items-center gap-1.5">
              <span
                className={`w-2 h-2 rounded-full ${
                  ollamaReachable ? "bg-emerald-400" : "bg-amber-400"
                }`}
                title={
                  ollamaReachable
                    ? "Ollama conectado en localhost:11434"
                    : "Ollama no detectado en localhost:11434"
                }
              />
              {onRefreshModels && (
                <button
                  type="button"
                  onClick={onRefreshModels}
                  title="Actualizar lista de modelos de Ollama"
                  className="p-1 rounded-md text-[#9aa0a6] hover:text-white hover:bg-[#282a2c] cursor-pointer transition-colors"
                >
                  <RefreshCw className="w-3 h-3" />
                </button>
              )}
            </div>
          </div>

          {/* Menú desplegable emergente hacia arriba (diseño mejorado con cursor pointer y descripciones) */}
          {isModelDropdownOpen && (
            <div className="absolute bottom-full mb-2 left-0 right-0 z-50 rounded-2xl bg-[#1a1b1e] border border-[#333537] shadow-2xl p-1.5 space-y-1 backdrop-blur-md animate-in fade-in zoom-in-95 duration-150">
              <div className="px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-[#9aa0a6] border-b border-[#333537]/60 flex items-center justify-between">
                <span>Modelos Locales</span>
                <span className="text-[10px] text-blue-400 font-normal">Clic para cambiar</span>
              </div>

              <div className="max-h-60 overflow-y-auto space-y-1 pr-0.5">
                {displayModels.map((m) => {
                  const isSelected = m.name === selectedModel;
                  const details = getModelDetails(m.name);
                  return (
                    <button
                      key={m.name}
                      type="button"
                      onClick={() => {
                        onSelectModel(m.name);
                        setIsModelDropdownOpen(false);
                      }}
                      className={`w-full text-left p-2.5 rounded-xl transition-all cursor-pointer flex items-center justify-between gap-2.5 ${
                        isSelected
                          ? "bg-gradient-to-r from-blue-500/20 to-purple-500/20 border border-[#4b90ff]/50 text-white shadow-sm"
                          : "hover:bg-[#282a2c] text-[#e3e3e3] border border-transparent"
                      }`}
                    >
                      <div className="flex items-start gap-2.5 min-w-0">
                        <div
                          className={`p-1.5 rounded-lg shrink-0 mt-0.5 ${
                            details.iconType === "vision"
                              ? "bg-cyan-500/20 text-cyan-300"
                              : details.iconType === "fast"
                              ? "bg-amber-500/20 text-amber-300"
                              : details.iconType === "main"
                              ? "bg-purple-500/20 text-purple-300"
                              : "bg-blue-500/20 text-blue-300"
                          }`}
                        >
                          {details.iconType === "vision" ? (
                            <Eye className="w-3.5 h-3.5" />
                          ) : details.iconType === "fast" ? (
                            <Zap className="w-3.5 h-3.5" />
                          ) : details.iconType === "main" ? (
                            <Sparkles className="w-3.5 h-3.5" />
                          ) : (
                            <Cpu className="w-3.5 h-3.5" />
                          )}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <span className="font-semibold text-xs text-white truncate">
                              {m.name}
                            </span>
                            {details.badge && (
                              <span
                                className={`text-[9px] px-1.5 py-0.2 rounded-full font-medium ${
                                  details.iconType === "vision"
                                    ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/30"
                                    : details.iconType === "fast"
                                    ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                                    : "bg-purple-500/20 text-purple-300 border border-purple-500/30"
                                }`}
                              >
                                {details.badge}
                              </span>
                            )}
                          </div>
                          <p className="text-[10px] text-[#9aa0a6] leading-tight mt-0.5">
                            {details.description}
                          </p>
                        </div>
                      </div>

                      {isSelected && (
                        <Check className="w-4 h-4 text-[#4b90ff] shrink-0" />
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Botón trigger para abrir/cerrar el selector con flecha limpia */}
          <button
            type="button"
            onClick={() => setIsModelDropdownOpen(!isModelDropdownOpen)}
            className={`w-full flex items-center justify-between px-3 py-2.5 text-xs rounded-xl bg-[#1e1f20] hover:bg-[#282a2c] border text-[#e3e3e3] cursor-pointer transition-all shadow-sm ${
              isModelDropdownOpen
                ? "border-[#4b90ff] ring-1 ring-[#4b90ff]/40 shadow-blue-500/10"
                : "border-[#333537] hover:border-[#4b90ff]/60"
            }`}
          >
            <div className="flex items-center gap-2 truncate">
              <div
                className={`p-1 rounded-md shrink-0 ${
                  currentDetails.iconType === "vision"
                    ? "bg-cyan-500/20 text-cyan-300"
                    : currentDetails.iconType === "fast"
                    ? "bg-amber-500/20 text-amber-300"
                    : currentDetails.iconType === "main"
                    ? "bg-purple-500/20 text-purple-300"
                    : "bg-blue-500/20 text-blue-300"
                }`}
              >
                {currentDetails.iconType === "vision" ? (
                  <Eye className="w-3 h-3" />
                ) : currentDetails.iconType === "fast" ? (
                  <Zap className="w-3 h-3" />
                ) : currentDetails.iconType === "main" ? (
                  <Sparkles className="w-3 h-3" />
                ) : (
                  <Cpu className="w-3 h-3" />
                )}
              </div>
              <span className="font-semibold text-xs text-white truncate">
                {selectedModel || "llama3.2:latest"}
              </span>
              {currentDetails.badge && (
                <span className="text-[9px] px-1.5 py-0.2 rounded-full bg-[#131314] text-[#9aa0a6] border border-[#333537] hidden sm:inline">
                  {currentDetails.badge}
                </span>
              )}
            </div>

            <ChevronUp
              className={`w-4 h-4 text-[#9aa0a6] transition-transform duration-200 shrink-0 ${
                isModelDropdownOpen ? "rotate-180 text-[#4b90ff]" : ""
              }`}
            />
          </button>
        </div>
      </div>
    </aside>
  );
}
