"use client";

import React from "react";
import {
  Plus,
  MessageSquare,
  Trash2,
  Cpu,
  SplitSquareHorizontal,
  Sparkles,
  RefreshCw,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { ChatSummary, OllamaModelInfo } from "@/lib/api";

export interface SidebarProps {
  chats: ChatSummary[];
  activeChatId: string | null;
  onSelectChat: (chatId: string) => void;
  onNewChat: () => void;
  onDeleteChat: (chatId: string) => void;
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
}

export default function Sidebar({
  chats,
  activeChatId,
  onSelectChat,
  onNewChat,
  onDeleteChat,
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
}: SidebarProps) {
  if (!isOpen) {
    return (
      <aside className="flex flex-col items-center justify-between py-4 px-2 bg-[#1e1f20] border-r border-[#333537]/80 w-16 shrink-0 h-screen select-none transition-all duration-200">
        <div className="flex flex-col items-center gap-4">
          {onToggleSidebar && (
            <button
              type="button"
              onClick={onToggleSidebar}
              title="Expandir barra lateral"
              className="p-2.5 rounded-full text-[#9aa0a6] hover:text-white hover:bg-[#282a2c] transition-colors"
            >
              <PanelLeftOpen className="w-5 h-5" />
            </button>
          )}

          <button
            type="button"
            onClick={onNewChat}
            title="Nuevo chat"
            className="p-3 rounded-full bg-gradient-to-r from-[#4b90ff] to-[#a855f7] text-white shadow-lg hover:opacity-95 transition-all"
          >
            <Plus className="w-5 h-5" />
          </button>
        </div>

        <button
          type="button"
          onClick={() => onToggleCompareMode(!compareMode)}
          title="Modo Comparación (Elegir entre 2 respuestas)"
          className={`p-2.5 rounded-xl border transition-all ${
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
      <div className="flex items-center justify-between px-4 pt-4 pb-3">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-[#4b90ff] via-indigo-500 to-[#a855f7] flex items-center justify-center shadow-md shadow-blue-500/20">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <div>
            <span className="font-semibold text-base tracking-tight bg-gradient-to-r from-blue-400 via-indigo-300 to-purple-400 bg-clip-text text-transparent">
              LocalGem Chat
            </span>
            <span className="block text-[10px] text-[#9aa0a6] leading-none">
              100% Local • SQLite + Ollama
            </span>
          </div>
        </div>

        {onToggleSidebar && (
          <button
            type="button"
            onClick={onToggleSidebar}
            title="Contraer barra lateral"
            className="p-2 rounded-full text-[#9aa0a6] hover:text-white hover:bg-[#282a2c] transition-colors"
          >
            <PanelLeftClose className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Botón Destacado "+ Nuevo chat" arriba del todo */}
      <div className="px-4 py-2">
        <button
          type="button"
          onClick={onNewChat}
          className="w-full flex items-center justify-center gap-2.5 py-2.5 px-4 rounded-full font-medium text-sm text-white bg-gradient-to-r from-[#4b90ff] to-[#a855f7] hover:from-[#5c9dff] hover:to-[#b469f9] shadow-md shadow-blue-600/20 active:scale-[0.99] transition-all"
        >
          <Plus className="w-4 h-4 stroke-[2.5]" />
          <span>+ Nuevo chat</span>
        </button>
      </div>

      {/* Lista desplazable de "Chats recientes" guardados en SQLite */}
      <div className="px-4 pt-3 pb-1.5 flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wider text-[#9aa0a6]">
          Chats recientes
        </span>
        <span className="text-[11px] text-[#9aa0a6]/80 bg-[#131314] px-2 py-0.5 rounded-full">
          {chats.length}
        </span>
      </div>

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
              Envía un mensaje o pulsa &ldquo;+ Nuevo chat&rdquo;.
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
                  <span className="truncate text-xs sm:text-sm" title={chat.title}>
                    {chat.title || "Nuevo Chat"}
                  </span>
                </div>

                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteChat(chat.id);
                  }}
                  title="Eliminar este chat"
                  aria-label={`Eliminar chat ${chat.title}`}
                  className="opacity-70 group-hover:opacity-100 p-1.5 rounded-lg text-[#9aa0a6] hover:text-red-400 hover:bg-red-500/15 transition-colors shrink-0"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            );
          })
        )}
      </div>

      {/* Panel Inferior: Selector de Modelo Ollama + Interruptor Modo Comparación A/B */}
      <div className="p-3.5 border-t border-[#333537]/80 bg-[#131314]/50 space-y-3">
        {/* Interruptor (Toggle) "Modo Comparación (Elegir entre 2 respuestas)" */}
        <div
          onClick={() => onToggleCompareMode(!compareMode)}
          role="switch"
          aria-checked={compareMode}
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onToggleCompareMode(!compareMode);
            }
          }}
          className={`p-3 rounded-xl border cursor-pointer transition-all ${
            compareMode
              ? "bg-gradient-to-r from-blue-500/15 to-purple-500/20 border-purple-500/50"
              : "bg-[#1e1f20] border-[#333537] hover:border-[#444746]"
          }`}
        >
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <SplitSquareHorizontal
                className={`w-4 h-4 shrink-0 ${
                  compareMode ? "text-purple-400" : "text-[#9aa0a6]"
                }`}
              />
              <span className="text-xs font-medium text-[#e3e3e3]">
                Modo Comparación
              </span>
            </div>

            {/* Switch visual */}
            <div
              className={`w-9 h-5 flex items-center rounded-full p-0.5 transition-colors ${
                compareMode
                  ? "bg-gradient-to-r from-[#4b90ff] to-[#a855f7]"
                  : "bg-[#333537]"
              }`}
            >
              <div
                className={`bg-white w-4 h-4 rounded-full shadow-md transform transition-transform ${
                  compareMode ? "translate-x-4" : "translate-x-0"
                }`}
              />
            </div>
          </div>
          <p className="text-[11px] text-[#9aa0a6] mt-1 leading-snug">
            Elegir entre 2 respuestas (A concisa vs B detallada). También se activa automáticamente cada 3 mensajes.
          </p>
        </div>

        {/* Selector desplegable de Modelo Local de Ollama */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label
              htmlFor="ollama-model-select"
              className="flex items-center gap-1.5 text-xs font-medium text-[#9aa0a6]"
            >
              <Cpu className="w-3.5 h-3.5 text-[#4b90ff]" />
              <span>Modelo Ollama Local</span>
            </label>

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
                  className="p-1 rounded-md text-[#9aa0a6] hover:text-white hover:bg-[#282a2c] transition-colors"
                >
                  <RefreshCw className="w-3 h-3" />
                </button>
              )}
            </div>
          </div>

          <select
            id="ollama-model-select"
            value={selectedModel}
            onChange={(e) => onSelectModel(e.target.value)}
            className="w-full px-3 py-2 text-xs rounded-xl bg-[#1e1f20] border border-[#333537] text-[#e3e3e3] focus:outline-none focus:border-[#4b90ff] transition-colors"
          >
            {models.length === 0 ? (
              <option value={selectedModel || "llama3.2:latest"}>
                {selectedModel || "llama3.2:latest"} (Auto-detección)
              </option>
            ) : (
              models.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}
                </option>
              ))
            )}
          </select>
        </div>
      </div>
    </aside>
  );
}
