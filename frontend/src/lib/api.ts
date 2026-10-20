/**
 * Cliente HTTP tipado para LocalGem Chat.
 * Conecta con todos los endpoints de `http://localhost:8000/api` según `specs/02-database-and-api.md`.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000/api";

export const BACKEND_ORIGIN = API_BASE_URL.replace(/\/api$/, "");

// =====================================================================
// 1. Tipos e Interfaces (Sincronizados con backend/schemas.py)
// =====================================================================

export type AttachmentFileType = "image" | "document" | "audio";
export type MessageRole = "user" | "assistant" | "system";
export type CandidateChoice = "A" | "B";
export type PreferredStyleType = "concise" | "detailed";

export interface Attachment {
  id: string;
  message_id: string;
  file_name: string;
  file_type: AttachmentFileType;
  mime_type: string;
  local_path: string;
  extracted_text?: string | null;
}

export interface Message {
  id: string;
  chat_id: string;
  role: MessageRole;
  content: string;
  follow_up_options: string[];
  is_ab_test: boolean;
  candidate_a: string | null;
  candidate_b: string | null;
  selected_candidate: CandidateChoice | null;
  created_at: string;
  attachments: Attachment[];
}

export interface ChatSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ChatDetail {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  user_message_count: number;
  messages: Message[];
}

export interface ChatDeleteResponse {
  deleted: boolean;
  chat_id: string;
}

export interface SendMessageResponse {
  chat_id: string;
  chat_title: string;
  user_message_count: number;
  user_message: Message;
  assistant_message: Message;
}

export interface UserPreferenceRecord {
  id: string;
  preferred_style: PreferredStyleType;
  message_id: string;
  created_at: string;
}

export interface SelectABResponse {
  message: Message;
  preference_recorded: UserPreferenceRecord;
}

export interface PreferenceSummary {
  total_ab_selections: number;
  concise_count: number;
  detailed_count: number;
  dominant_style: "concise" | "detailed" | "balanced";
}

export interface OllamaModelInfo {
  name: string;
  size?: number | null;
  modified_at?: string | null;
}

export interface ModelsListResponse {
  models: OllamaModelInfo[];
  default_model: string;
}

export interface HealthResponse {
  status: string;
  database: string;
  ollama_reachable: boolean;
  active_model: string;
  available_models: string[];
}

// =====================================================================
// 2. Utilidades de Red y Manejo de Errores
// =====================================================================

async function handleApiResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let errorDetail = `Error HTTP ${response.status}`;
    try {
      const errJson = await response.json();
      if (typeof errJson?.detail === "string") {
        errorDetail = errJson.detail;
      } else if (Array.isArray(errJson?.detail)) {
        errorDetail = errJson.detail.map((e: { msg?: string }) => e.msg).join(", ");
      }
    } catch {
      const text = await response.text().catch(() => "");
      if (text) errorDetail = text;
    }
    throw new Error(errorDetail);
  }
  return response.json() as Promise<T>;
}

/**
 * Construye la URL pública para previsualizar o reproducir un archivo subido en `/uploads/...`.
 */
export function getAttachmentUrl(localPath: string): string {
  const normalized = localPath.replace(/^\/+/, "");
  return `${BACKEND_ORIGIN}/${normalized}`;
}

// =====================================================================
// 3. Funciones del Cliente API (`http://localhost:8000/api`)
// =====================================================================

/**
 * Verifica el estado del servidor FastAPI, SQLite y conexión con Ollama.
 */
export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE_URL}/health`, {
    method: "GET",
    cache: "no-store",
  });
  return handleApiResponse<HealthResponse>(res);
}

/**
 * Obtiene la lista de modelos instalados localmente en Ollama (`GET /api/models`).
 */
export async function fetchModels(): Promise<ModelsListResponse> {
  const res = await fetch(`${API_BASE_URL}/models`, {
    method: "GET",
    cache: "no-store",
  });
  return handleApiResponse<ModelsListResponse>(res);
}

/**
 * Obtiene todos los chats guardados en SQLite ordenados por `updated_at` descendente (`GET /api/chats`).
 */
export async function fetchChats(): Promise<ChatSummary[]> {
  const res = await fetch(`${API_BASE_URL}/chats`, {
    method: "GET",
    cache: "no-store",
  });
  return handleApiResponse<ChatSummary[]>(res);
}

/**
 * Crea un nuevo chat vacío en SQLite (`POST /api/chats`).
 */
export async function createChat(title: string = "Nuevo Chat"): Promise<ChatDetail> {
  const res = await fetch(`${API_BASE_URL}/chats`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  return handleApiResponse<ChatDetail>(res);
}

/**
 * Obtiene el detalle de un chat con todos sus mensajes, adjuntos, opciones de seguimiento y estado A/B (`GET /api/chats/{chat_id}`).
 */
export async function fetchChatById(chatId: string): Promise<ChatDetail> {
  const res = await fetch(`${API_BASE_URL}/chats/${encodeURIComponent(chatId)}`, {
    method: "GET",
    cache: "no-store",
  });
  return handleApiResponse<ChatDetail>(res);
}

/**
 * Actualiza el título de un chat (`PATCH /api/chats/{chat_id}`).
 */
export async function updateChatTitle(chatId: string, title: string): Promise<ChatDetail> {
  const res = await fetch(`${API_BASE_URL}/chats/${encodeURIComponent(chatId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  return handleApiResponse<ChatDetail>(res);
}

/**
 * Elimina un chat y todo su historial de mensajes y archivos adjuntos (`DELETE /api/chats/{chat_id}`).
 */
export async function deleteChat(chatId: string): Promise<ChatDeleteResponse> {
  const res = await fetch(`${API_BASE_URL}/chats/${encodeURIComponent(chatId)}`, {
    method: "DELETE",
  });
  return handleApiResponse<ChatDeleteResponse>(res);
}

export interface SendMessageParams {
  chatId: string;
  content: string;
  model?: string;
  compareMode?: boolean;
  files?: File[];
}

/**
 * Envía un mensaje del usuario con texto y/o archivos multimodales (`POST /api/chats/{chat_id}/messages`).
 * Recibe el mensaje guardado del usuario y la respuesta del asistente (con `follow_up_options` y pares A/B si aplica).
 */
export async function sendMessage({
  chatId,
  content,
  model,
  compareMode = false,
  files = [],
}: SendMessageParams): Promise<SendMessageResponse> {
  const formData = new FormData();
  formData.append("content", content);
  formData.append("compare_mode", String(compareMode));
  formData.append("force_ab_test", String(compareMode));

  if (model && model.trim()) {
    formData.append("model", model.trim());
  }

  for (const file of files) {
    formData.append("files", file);
  }

  const res = await fetch(`${API_BASE_URL}/chats/${encodeURIComponent(chatId)}/messages`, {
    method: "POST",
    body: formData,
  });
  return handleApiResponse<SendMessageResponse>(res);
}

/**
 * Registra la respuesta preferida del usuario ('A' o 'B') en el Modo de Satisfacción A/B (`POST /api/messages/{message_id}/select-ab`).
 */
export async function selectABCandidate(
  messageId: string,
  selected: CandidateChoice
): Promise<SelectABResponse> {
  const res = await fetch(
    `${API_BASE_URL}/messages/${encodeURIComponent(messageId)}/select-ab`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ selected, selected_candidate: selected }),
    }
  );
  return handleApiResponse<SelectABResponse>(res);
}

/**
 * Obtiene el resumen de preferencias de estilo aprendidas del usuario (`GET /api/preferences/summary`).
 */
export async function fetchPreferenceSummary(): Promise<PreferenceSummary> {
  const res = await fetch(`${API_BASE_URL}/preferences/summary`, {
    method: "GET",
    cache: "no-store",
  });
  return handleApiResponse<PreferenceSummary>(res);
}
