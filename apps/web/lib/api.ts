/**
 * 领域 API 客户端。
 *
 * 类型由 OpenAPI 3.1 生成（`pnpm gen:api`），这里**不手写任何接口类型**。
 * 一个概念在数据库、API、前端用同一个名字，只由 codegen 做大小写转换。
 */
import type { components, paths } from "./api-types";
import { currentPrincipal } from "./session";

export type ActionKind = components["schemas"]["ActionKindOut"];
export type IntentContent = components["schemas"]["IntentContentOut"];
export type IntentContentIn = components["schemas"]["IntentContentIn"];
export type Intent = components["schemas"]["IntentOut"];
export type CompileResult = components["schemas"]["CompileResponse"];
export type FollowUp = components["schemas"]["FollowUpOut"];
export type Conflict = components["schemas"]["ConflictOut"];

/** 后端返回的结构化错误。用来把冲突逐条显示出来，而不是弹一句"出错了"。 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : "请求没能完成");
  }

  /** 确认被拒时后端会说明是哪几条约束打架。 */
  get conflicts(): Conflict[] {
    const d = this.detail;
    if (d && typeof d === "object" && "conflicts" in d) {
      return (d as { conflicts: Conflict[] }).conflicts;
    }
    return [];
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Principal-Id": currentPrincipal(),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body?.detail ?? body);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

type CompileBody = paths["/api/intents:compile"]["post"]["requestBody"]["content"]["application/json"];
type CreateBody = paths["/api/intents"]["post"]["requestBody"]["content"]["application/json"];

export const api = {
  actionKinds: () => request<ActionKind[]>("/api/action-kinds"),

  /** 抽取。**不写库**——没有用户确认，什么都进不了撮合。 */
  compile: (expression: string) =>
    request<CompileResult>("/api/intents:compile", {
      method: "POST",
      body: JSON.stringify({ expression } satisfies CompileBody),
    }),

  create: (body: CreateBody) =>
    request<Intent>("/api/intents", { method: "POST", body: JSON.stringify(body) }),

  confirm: (id: string) =>
    request<Intent>(`/api/intents/${id}:confirm`, { method: "POST" }),

  withdraw: (id: string) =>
    request<Intent>(`/api/intents/${id}:withdraw`, { method: "POST" }),

  revise: (id: string, content: IntentContentIn) =>
    request<Intent>(`/api/intents/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ content }),
    }),

  myIntents: () => request<Intent[]>("/api/me/intents"),
};

/** 把抽取结果转成可回传的内容。`uncertain_fields` 是抽取器的自述，不回传。 */
export function toContentIn(content: IntentContent): IntentContentIn {
  const { uncertain_fields: _drop, ...rest } = content;
  return rest;
}
