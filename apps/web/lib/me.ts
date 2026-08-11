/**
 * 三个自我管理面的取数：我参加过的 / 关于我的记录 / 谁能看到我。
 *
 * 类型全部来自 codegen（`lib/api-types.ts`），这里**不手写任何接口类型**。
 * 一个概念在数据库、API、前端用同一个名字，只由 codegen 做大小写转换。
 *
 * 三个面各是一次独立取数，**故意不合成一个接口**：其中一个挂了，
 * 另外两个照常能用（docs/08 §5 的降级那一列）。合成一个接口的话，
 * 一处失败就是整屏失败。
 */
import { ApiError } from "./api";
import type { components } from "./api-types";
import { currentPrincipal } from "./session";

export type MyEvent = components["schemas"]["MyEventOut"];
export type MyRecord = components["schemas"]["MyRecordOut"];
export type MyRecords = components["schemas"]["MyRecordsOut"];
export type RecordSource = components["schemas"]["RecordSourceOut"];
export type Visibility = components["schemas"]["VisibilityOut"];
export type ShownField = components["schemas"]["ShownFieldOut"];
export type Envelope = components["schemas"]["EnvelopeOut"];

/** 事件的三种处境。后端是 StrEnum，OpenAPI 里落成 `string`，codegen 生不出联合类型。 */
export const ACTIVE = "active";
export const COMPLETED = "completed";
export const ABANDONED = "abandoned";

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

/** 我参加过的事。进行中、已完成、已取消都在——取消的也是我的真实经历。 */
export const myEvents = () => request<MyEvent[]>("/api/me/events");

/** 系统记着的关于我的每一句话。没点过头的和点过头的是分开的两堆。 */
export const myRecords = () => request<MyRecords>("/api/me/facets");

/** 我给出去过、现在还生效的那几次。 */
export const myVisibility = () => request<Visibility[]>("/api/me/visibility");

/** 点头。点过头的才可能出现在别人看到的说明里。 */
export const confirmRecord = (recordId: string) =>
  request<MyRecord>(`/api/facets/${recordId}:confirm`, { method: "POST" });

/**
 * 收回。一步完成，不再确认一次。
 *
 * 后端收回是把那一行改掉，而引用它的**唯一**入口只认没被收回的行——
 * 所以这里不需要通知任何别的地方，也没有第二份会变旧的副本。
 */
export const revokeRecord = (recordId: string) =>
  request<MyRecord>(`/api/facets/${recordId}:revoke`, { method: "POST" });

/**
 * 收回一次对外披露。
 *
 * 复用「这次让他们看到我的」那一屏用的同一条命令，不另开一条写路径——
 * 两条写路径迟早会不一致，而不一致的那一刻用户以为自己收回了、其实没有。
 */
export const stopShowing = (envelopeId: string) =>
  request<Envelope>(`/api/envelopes/${envelopeId}:revoke`, { method: "POST" });

/** 这个人是不是什么都还没有。三个面同时为空才算——只空一个是正常的。 */
export function nothingYet(
  events: MyEvent[] | null,
  records: MyRecords | null,
  shown: Visibility[] | null,
): boolean {
  if (events === null || records === null || shown === null) return false;
  const noRecords =
    records.to_confirm.length === 0 &&
    records.confirmed.length === 0 &&
    records.revoked.length === 0;
  return events.length === 0 && noRecords && shown.length === 0;
}
