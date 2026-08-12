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

export type Again = components["schemas"]["AgainOut"];
export type Intent = components["schemas"]["IntentOut"];

/** 照这件事再来一次：一张**还没保存**的草稿。
 *
 *  它不直接建需求——抽取只产出草稿这条规矩在这里同样成立：带过来的东西
 *  要让本人过目，尤其是时间和地点，它们必然是新的。 */
export const againFrom = (eventId: string) =>
  request<Again>(`/api/events/${eventId}/again`);

/** 我发过的所有需求。调用方自己过滤 is_matchable。 */
export const myMatchableIntents = () => request<Intent[]>("/api/me/intents");

/**
 * 把这条新需求问上次那几个人。
 *
 * **不是把他们拉进来**——不变量 3：成局前只有提案，没有关系。
 * 每个人收到的是一条待答复，要各自点头才算进来。
 * 返回 { asked: N }，N 是发出去几条待答复（过求解器和稳定性检查，不稳定就是 0）。
 */
export const askThemAgain = (
  eventId: string,
  intentId: string,
  invite: string[],
) =>
  request<{ [key: string]: number }>(`/api/events/${eventId}:again`, {
    method: "POST",
    body: JSON.stringify({ intent_id: intentId, invite }),
  });

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

/** 这一队里我会得到什么。不在名单上的人拿到 404。
 *  从通知点进来看单独一队时用它；整页列表**不用**——见下。 */
export const invitationFor = (proposalId: string) =>
  request<Invitation>(`/api/proposals/${proposalId}/invitation`);

/**
 * 我被邀请进的每一队，连内容一起。
 *
 * ## 这里曾经是一个 N+1，而且是坏的
 *
 * 原先它先取一串 id，再逐个去问内容。可 `/api/me/proposals` 返回的从来
 * 就是**完整的邀请对象**，不是 id 字符串——于是拼出来的路径是
 * `/api/proposals/[object Object]/invitation`，每一条都 422，
 * 整屏退到「现在调不出等你答复的事」。
 *
 * 而导航上那个「有 N 件事等你答复」读的是同一个接口、按对象解析，所以
 * 它显示 3。**用户看到"有 3 件事等你答复"，点进去是一句"调不出来"。**
 *
 * TypeScript 没能挡住：那一步的返回类型是手写的 `string[]` 而不是
 * codegen 出来的——「不手写任何接口类型」这条规矩正是为了防这个。
 *
 * 现在一次取完。少一轮 N+1，也少一处会和后端漂移的手写类型。
 */
export async function myInvitations(): Promise<Invitation[]> {
  return request<Invitation[]>("/api/me/proposals");
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
