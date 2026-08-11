/**
 * 「这次让他们看到我的」这一屏的取数。
 *
 * 类型全部来自 codegen（`lib/api-types.ts`），这里**不手写任何接口类型**。
 * 一个概念在数据库、API、前端用同一个名字，只由 codegen 做大小写转换。
 */
import { ApiError } from "./api";
import type { components } from "./api-types";
import { currentPrincipal } from "./session";

export type GrantableField = components["schemas"]["GrantableFieldOut"];
export type Grant = components["schemas"]["GrantOut"];
export type GrantIn = components["schemas"]["GrantIn"];
export type Envelope = components["schemas"]["EnvelopeOut"];
export type Preview = components["schemas"]["PreviewOut"];

/**
 * `audience` 在 OpenAPI 里是 `string`（Pydantic 的 StrEnum 取了 `.value`），
 * codegen 生不出联合类型。给两个常量，免得字面量散落在各处拼错。
 */
export const SOLVER_ONLY = "solver_only";
export const CANDIDATES = "candidates";

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

/** 这次可以逐项决定的内容。`present=false` 表示这条需求里还没写这一项。 */
export const grantableFields = (intentId: string) =>
  request<GrantableField[]>(`/api/intents/${intentId}/grantable-fields`);

/** 保存这次给出去的内容。整份覆盖——没列出来的项就是这次不给。 */
export const putEnvelope = (intentId: string, grants: GrantIn[]) =>
  request<Envelope>(`/api/intents/${intentId}/envelope`, {
    method: "PUT",
    body: JSON.stringify({ grants }),
  });

/** 全部收回。收回之后新的请求立刻被拒，不用等任何后台清理。 */
export const revokeEnvelope = (envelopeId: string) =>
  request<Envelope>(`/api/envelopes/${envelopeId}:revoke`, { method: "POST" });

/** 我给出过、且还在生效的授权。 */
export const myGrants = () => request<Envelope[]>("/api/me/grants");

/** 对方会看到的样子。服务端按对外输出的同一条路径投影，不是前端猜的。 */
export const fetchPreview = (intentId: string) =>
  request<Preview>(`/api/intents/${intentId}/preview`);

/**
 * 这条需求当前的授权。
 *
 * 后端没有「按需求取授权」的入口，只能从「我给出过的」里挑出这一条；
 * 已收回和已过期的不会出现在那份清单里，所以拿到 null 就是"这次还没给过"。
 */
export async function envelopeForIntent(
  intentId: string,
): Promise<Envelope | null> {
  const mine = await myGrants();
  return mine.find((e) => e.intent_id === intentId) ?? null;
}
