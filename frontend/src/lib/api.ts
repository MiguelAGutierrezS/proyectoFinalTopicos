/**
 * Cliente HTTP tipado para LocalGem Chat v2.0.
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

export interface MCPToolCallTrace {
  tool_name: string;
  arguments: Record<string, unknown>;
  status: string;
  result_preview: string;
  duration_ms: number;
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
  active_skill?: string | null;
  mcp_tool_calls?: MCPToolCallTrace[];
  created_at: string;
  attachments: Attachment[];
}

export interface ChatSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  is_context_compacted?: boolean;
}

export interface ChatDetail {
  id: string;
  title: string;
  context_summary?: string | null;
  compacted_up_to_index?: number | null;
  is_context_compacted?: boolean;
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

// --- Skills (SKILL.md) ---

export interface SkillInfo {
  id: string;
  name: string;
  description: string;
  icon: string;
  triggers: string[];
  recommended_tools: string[];
  instructions_preview: string;
  file_path: string;
}

export interface SkillsListResponse {
  skills: SkillInfo[];
}

export interface SkillCreatePayload {
  id: string;
  name: string;
  description: string;
  icon?: string;
  triggers?: string[];
  recommended_tools?: string[];
  instructions: string;
}

// --- MCP (Model Context Protocol Local) ---

export interface MCPToolDefinition {
  name: string;
  title: string;
  description: string;
  category: string;
  input_schema: Record<string, unknown>;
}

export interface MCPToolsListResponse {
  tools: MCPToolDefinition[];
  mcp_enabled: boolean;
}

export interface MCPCallResponse {
  tool_name: string;
  arguments: Record<string, unknown>;
  status: string;
  result: string;
  duration_ms: number;
}

// --- LangGraph StateGraph Schema (`GET /api/graph/schema`) ---

export interface GraphNodeSchema {
  id: string;
  label: string;
  description: string;
}

export interface GraphSchemaResponse {
  engine: string;
  version: string;
  state_schema: string;
  nodes: GraphNodeSchema[];
  mermaid: string;
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

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE_URL}/health`, {
    method: "GET",
    cache: "no-store",
  });
  return handleApiResponse<HealthResponse>(res);
}

export async function fetchModels(): Promise<ModelsListResponse> {
  const res = await fetch(`${API_BASE_URL}/models`, {
    method: "GET",
    cache: "no-store",
  });
  return handleApiResponse<ModelsListResponse>(res);
}

export async function fetchChats(): Promise<ChatSummary[]> {
  const res = await fetch(`${API_BASE_URL}/chats`, {
    method: "GET",
    cache: "no-store",
  });
  return handleApiResponse<ChatSummary[]>(res);
}

export async function createChat(title: string = "Nuevo Chat"): Promise<ChatDetail> {
  const res = await fetch(`${API_BASE_URL}/chats`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  return handleApiResponse<ChatDetail>(res);
}

export async function fetchChatById(chatId: string): Promise<ChatDetail> {
  const res = await fetch(`${API_BASE_URL}/chats/${encodeURIComponent(chatId)}`, {
    method: "GET",
    cache: "no-store",
  });
  return handleApiResponse<ChatDetail>(res);
}

export async function updateChatTitle(chatId: string, title: string): Promise<ChatDetail> {
  const res = await fetch(`${API_BASE_URL}/chats/${encodeURIComponent(chatId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  return handleApiResponse<ChatDetail>(res);
}

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
  skillId?: string;
  enableMcp?: boolean;
  files?: File[];
}

export async function sendMessage({
  chatId,
  content,
  model,
  compareMode = false,
  skillId = "auto",
  enableMcp = true,
  files = [],
}: SendMessageParams): Promise<SendMessageResponse> {
  const formData = new FormData();
  formData.append("content", content);
  formData.append("compare_mode", String(compareMode));
  formData.append("force_ab_test", String(compareMode));
  formData.append("skill_id", skillId || "auto");
  formData.append("enable_mcp", String(enableMcp));

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

export async function fetchPreferenceSummary(): Promise<PreferenceSummary> {
  const res = await fetch(`${API_BASE_URL}/preferences/summary`, {
    method: "GET",
    cache: "no-store",
  });
  return handleApiResponse<PreferenceSummary>(res);
}

// =====================================================================
// 4. Funciones para Skills (`SKILL.md`) y Herramientas MCP Locales
// =====================================================================

export async function fetchSkills(): Promise<SkillsListResponse> {
  const res = await fetch(`${API_BASE_URL}/skills`, {
    method: "GET",
    cache: "no-store",
  });
  return handleApiResponse<SkillsListResponse>(res);
}

export async function createSkill(payload: SkillCreatePayload): Promise<SkillInfo> {
  const res = await fetch(`${API_BASE_URL}/skills`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleApiResponse<SkillInfo>(res);
}

export async function fetchMCPTools(): Promise<MCPToolsListResponse> {
  const res = await fetch(`${API_BASE_URL}/mcp/tools`, {
    method: "GET",
    cache: "no-store",
  });
  return handleApiResponse<MCPToolsListResponse>(res);
}

export async function callMCPTool(
  toolName: string,
  args: Record<string, unknown> = {}
): Promise<MCPCallResponse> {
  const res = await fetch(`${API_BASE_URL}/mcp/call`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tool_name: toolName,
      arguments: args,
    }),
  });
  return handleApiResponse<MCPCallResponse>(res);
}

export async function fetchGraphSchema(): Promise<GraphSchemaResponse> {
  const res = await fetch(`${API_BASE_URL}/graph/schema`, {
    method: "GET",
    cache: "no-store",
  });
  return handleApiResponse<GraphSchemaResponse>(res);
}

