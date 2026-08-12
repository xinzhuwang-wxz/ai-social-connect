/**
 * 「等配队」「给你找的人」「还差这几件事」三屏的取数。
 *
 * 类型全部来自 codegen（`lib/api-types.ts`），这里**不手写任何接口类型**。
 * 一个概念在数据库、API、前端用同一个名字，只由 codegen 做大小写转换。
 */
import { ApiError, api, type Intent, type IntentContentIn } from "./api";
import type { components } from "./api-types";
import { currentPrincipal } from "./session";

export type Waiting = components["schemas"]["WaitingOut"];
export type Gap = components["schemas"]["GapOut"];
export type Team = components["schemas"]["TeamOut"];
export type TeamMember = components["schemas"]["TeamMemberOut"];
export type ProofLine = components["schemas"]["ProofLineOut"];
export type Blocked = components["schemas"]["BlockedOut"];
export type Relaxation = components["schemas"]["RelaxationOut"];
export type NextStep = components["schemas"]["NextStepOut"];
export type GateStatus = components["schemas"]["GateStatusOut"];
export type ClearingReport = components["schemas"]["ClearingOut"];

/**
 * 答复的三档。
 *
 * 后端是 StrEnum，OpenAPI 里落成 `string`，codegen 生不出联合类型（`audience`
 * 同样如此）。给三个常量，免得字面量散落在各处拼错。
 */
export const ACCEPTED = "accepted";
export const DECLINED = "declined";
export const CONDITIONAL = "conditional";

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

/** 下次什么时候配队、这个方向上现在缺什么。只有聚合数，没有名字。 */
export const waitingNow = (actionKind?: string) =>
  request<Waiting>(
    actionKind ? `/api/me/waiting?action_kind=${encodeURIComponent(actionKind)}` : "/api/me/waiting",
  );

/** 这条需求配到的小队。空数组表示这一轮没凑出来——那时候去看 `blockedFor`。 */
export const teamsFor = (intentId: string) =>
  request<Team[]>(`/api/intents/${intentId}/teams`);

/** 凑不出队时卡在哪、放宽哪一项能多出多少人、下一步能做什么。 */
export const blockedFor = (intentId: string) =>
  request<Blocked>(`/api/intents/${intentId}/blocked`);

/** 还在等谁。 */
export const gateStatus = (proposalId: string) =>
  request<GateStatus>(`/api/proposals/${proposalId}/status`);

/**
 * 我加入 / 我不参加 / 我可以但……
 *
 * 身份走请求头，不走请求体——所以这里没有 principal_id 参数，也不该有。
 */
export const decide = (
  proposalId: string,
  answer: string,
  condition?: string,
  /** 「这次不行，以后类似的叫我」。只有拒绝时有意义——
   *  加入了就不需要"以后再叫我"。 */
  remindMe = false,
) =>
  request<GateStatus>(`/api/proposals/${proposalId}:decide`, {
    method: "POST",
    body: JSON.stringify({
      answer,
      condition: condition ?? null,
      remind_me: remindMe,
    }),
  });

/** 立刻配一轮。演示用：不必真等到窗口到点才看得见结果。同一窗口内重复调用是安全的。 */
export const runClearing = () =>
  request<ClearingReport>("/api/clearing:run", { method: "POST" });

export const fetchIntent = (intentId: string) =>
  request<Intent>(`/api/intents/${intentId}`);

/** 我正在等配队的那几件事。念头和草稿不算——它们还没进这一轮。 */
export async function myWaitingIntents(): Promise<Intent[]> {
  const mine = await api.myIntents();
  return mine.filter((intent) => intent.is_matchable);
}

/**
 * 这事不找了。
 *
 * **在这之前，一条发出去的需求没有任何办法收回。** 它会一直待在池子里，
 * 一轮一轮地占着会这一样的人，还不停给本人推他早就不想要的小队。
 * 后端的 `:withdraw` 一直在，客户端的 `api.withdraw` 也一直在，
 * 只是**没有一屏用它**——建好了却没有入口，和没建一样。
 */
export const dropIntent = (intentId: string) => api.withdraw(intentId);

/**
 * 改需求，然后把它送回队列。
 *
 * **改完必须重新确认。** 后端在改动之后把这条打回草稿（旧的确认不能沿用到新内容
 * 上），不补这一步的话，用户"改了一下"的代价是悄悄退出了配队——他不会知道，
 * 直到再也没有人被配给他。
 *
 * 只有本来就在等的那些才补确认：念头是用户存着还没想好的，替他确认等于替他
 * 决定这件事该开始找人了。
 */
export async function reviseAndReconfirm(
  intent: Intent,
  content: IntentContentIn,
): Promise<Intent> {
  const revised = await api.revise(intent.id, content);
  if (!intent.is_matchable || revised.is_matchable) return revised;
  return api.confirm(intent.id);
}
