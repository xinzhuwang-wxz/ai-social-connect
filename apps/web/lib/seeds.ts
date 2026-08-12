/**
 * 信箱与挑人：投递制那条链路的取数。
 *
 * ## 为什么它单独一个文件
 *
 * 投递不是"提案的另一种叫法"：提案是一支队等大家点头，投递是**一对一**
 * ——每个候选各自一条、各自的状态、各自的留言。两者放一个文件里，
 * "还在等谁"和"谁说了愿意"迟早会被写成同一个函数。
 */
import type { components } from "./api-types";
import { currentPrincipal } from "./session";

export type Seed = components["schemas"]["SeedOut"];
export type Candidates = components["schemas"]["CandidatesOut"];
export type Candidate = components["schemas"]["CandidateOut"];

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Principal-Id": currentPrincipal(),
      ...init?.headers,
    },
  });
  if (!res.ok) throw new Error(String(res.status));
  return (await res.json()) as T;
}

/** 我的信箱。已经找到同行者的种子不再占地方。 */
export const mySeeds = () => request<Seed[]>("/api/me/seeds");

/**
 * 愿意参与，或者这次不感兴趣。
 *
 * **愿意不等于加入**：还要发起人挑中才成局。这句话界面上必须说清楚，
 * 否则用户会以为自己已经答应了，然后在没被选中时觉得被放了鸽子。
 */
export const respondToSeed = (
  intentId: string,
  willing: boolean,
  note?: string,
  remindMe = false,
) =>
  request<Seed>(`/api/seeds/${intentId}:respond`, {
    method: "POST",
    body: JSON.stringify({ willing, note: note ?? null, remind_me: remindMe }),
  });

/** 谁说了愿意。发起人在这一屏挑人。 */
export const candidatesFor = (intentId: string) =>
  request<Candidates>(`/api/intents/${intentId}/candidates`);

/** 挑一个人。**AI 不替他做这一下**——它排序、它解释，按下去的必须是人。 */
export const chooseCandidate = (intentId: string, who: string) =>
  request<Candidates>(`/api/intents/${intentId}/candidates/${who}:choose`, {
    method: "POST",
  });
