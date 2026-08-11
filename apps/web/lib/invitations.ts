/**
 * 「这次你会得到什么」与「这次留下了什么」两屏的取数。
 *
 * 类型全部来自 codegen（`lib/api-types.ts`），这里**不手写任何接口类型**。
 * 一个概念在数据库、API、前端用同一个名字，只由 codegen 做大小写转换。
 *
 * 这两屏是同一条闭环的两端：一端问"我要不要进来"，另一端问"这次留下了
 * 什么、哪些算数"。它们放在一个文件里，是因为闭环断在中间的话，产品就只是
 * 一个更漂亮的组队工具。
 */
import { ApiError } from "./api";
import type { components } from "./api-types";
import type { MyRecord } from "./me";
import { currentPrincipal } from "./session";

export type Invitation = components["schemas"]["InvitationOut"];
export type Echo = components["schemas"]["EchoOut"];
export type Evidence = components["schemas"]["EvidenceOut"];
export type NewEvidence = components["schemas"]["EvidenceIn"];
export type Recap = components["schemas"]["RecapOut"];
export type Draft = components["schemas"]["DraftOut"];

/**
 * 一条记录的三种处境。
 *
 * 后端是 StrEnum，OpenAPI 里落成 `string`，codegen 生不出联合类型。
 * 给三个常量，免得字面量散落在各处拼错。
 */
export const DRAFT = "draft";
export const CONFIRMED = "confirmed";
export const REVOKED = "revoked";

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

// --- 这次你会得到什么 -------------------------------------------------------

/** 我被邀请进了哪几队。只有 id——一队长什么样要再问一次。 */
export const myInvitationIds = () => request<string[]>("/api/me/proposals");

/** 这一队里我会得到什么。不在名单上的人拿到 404。 */
export const invitationFor = (proposalId: string) =>
  request<Invitation>(`/api/proposals/${proposalId}/invitation`);

/**
 * 我被邀请进的每一队，连内容一起。
 *
 * 取不出的那几条**跳过**：一队坏掉不该让其余几队跟着看不见，而看不见的
 * 那几队正有人在等答复。全都取不出来才算这一屏坏了。
 */
export async function myInvitations(): Promise<Invitation[]> {
  const ids = await myInvitationIds();
  const settled = await Promise.allSettled(ids.map(invitationFor));
  const got = settled.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
  if (ids.length > 0 && got.length === 0) {
    throw new ApiError(503, "一条都没取出来");
  }
  return got;
}

// --- 这次留下了什么 ---------------------------------------------------------

/** 留下的东西、一段回顾、等我点头的几条。回顾取不到是常态，不是错误。 */
export const echoFor = (eventId: string) =>
  request<Echo>(`/api/events/${eventId}/echo`);

/** 留下一件东西。**只存事实**——这里没有一个字段能放"谁做得好"。 */
export const leaveOneThing = (eventId: string, item: NewEvidence) =>
  request<Evidence>(`/api/events/${eventId}/evidence`, {
    method: "POST",
    body: JSON.stringify(item),
  });

/** 自己写一条。它同样是草稿，同样要再点一次头才算数。 */
export const writeOwn = (eventId: string, text: string) =>
  request<Draft>(`/api/events/${eventId}/records`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });

/**
 * 这一屏上的一条记录。
 *
 * 等我点头的（`DraftOut`）和已经在用的（`MyRecordOut`）在后端是两个形状——
 * 它们来自两条不同的读路径。界面上它们是**同一件东西的三种处境**，所以在
 * 这里收敛成一个形状：让组件按 `state` 分堆，而不是按"它是从哪个接口来的"分堆。
 * 后者会让"点过头之后它去哪了"变成一个界面自己也答不上来的问题。
 */
export type EchoRecord = {
  id: string;
  text: string;
  /** 常驻那句话。草稿必须自己带着它，不靠界面记得加角标。 */
  hint: string;
  /** 它依据了哪些留下来的东西。 */
  based_on: string[];
  drafted_by_agent: boolean;
  /** draft / confirmed / revoked */
  state: string;
  /** 现在有几处正在用这句话。收回之后是 0。 */
  in_use: number;
};

export function fromDraft(draft: Draft): EchoRecord {
  return {
    id: draft.facet_id,
    text: draft.text,
    hint: draft.hint,
    based_on: draft.grounded_in,
    drafted_by_agent: draft.drafted_by_agent,
    state: DRAFT,
    in_use: 0,
  };
}

export function fromMine(record: MyRecord): EchoRecord {
  return {
    id: record.id,
    text: record.text,
    hint: "",
    based_on: record.sources.map((source) => source.title),
    drafted_by_agent: record.drafted_by_agent,
    state: record.state,
    // 收回过的不再被任何地方引用。这里不信旧数字，免得界面还显示它在被用着。
    in_use: record.state === REVOKED ? 0 : record.in_use,
  };
}

/** 这件事上我已经点过头的那几条。别的事情上的记录不在这一屏里。 */
export function confirmedHere(records: MyRecord[], eventId: string): EchoRecord[] {
  return records
    .filter((record) => record.event_id === eventId)
    .map(fromMine)
    .filter((record) => record.state !== DRAFT);
}
