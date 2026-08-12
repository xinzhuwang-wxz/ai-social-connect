/**
 * 「我们的空间」那一屏的取数。
 *
 * 类型全部来自 codegen（`lib/api-types.ts`），这里**不手写任何接口类型**。
 * 一个概念在数据库、API、前端用同一个名字，只由 codegen 做大小写转换。
 *
 * 一屏四次独立取数，**故意不合成一个接口**：助手那一段挂了，画布照常
 * （docs/08 §5 的降级那一列）。合成一个接口的话，一处失败就是整屏失败——
 * 而"关掉助手之后整屏照常可用"这条承诺，第一个要经得起的就是助手挂掉。
 */
import { ApiError } from "./api";
import type { components } from "./api-types";
import { currentPrincipal } from "./session";

export type Space = components["schemas"]["SpaceOut"];
export type Item = components["schemas"]["ItemOut"];
export type ItemKind = components["schemas"]["ItemKindOut"];
export type Progress = components["schemas"]["ProgressOut"];
export type Suggestion = components["schemas"]["SuggestionOut"];
export type Reach = components["schemas"]["ItemReach"];
export type NewItem = components["schemas"]["AddItemRequest"];
export type Plan = components["schemas"]["PlanOut"];
export type PlanIn = components["schemas"]["PlanIn"];
export type DayOf = components["schemas"]["DayOfOut"];
export type Poll = components["schemas"]["PollOut"];
export type ItemPatch = components["schemas"]["ReviseItemRequest"];
export type TakeSuggestion = components["schemas"]["AcceptSuggestionRequest"];

/** 谁能看见。后端是 StrEnum，这里给常量免得字面量散落各处拼错。 */
export const OURS = "ours";
export const OUTSIDE = "outside";

/** `extras` 里几个有约定含义的键。三层同名，不做层间翻译。 */
export const SOURCE = "source";
export const REACH = "reach";

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

/** 一屏：要做什么、卡在哪、还有哪些决定没关、助手写了什么等你过目。 */
export const fetchSpace = (spaceId: string) =>
  request<Space>(`/api/spaces/${spaceId}`);

/**
 * 能往这里放哪几类东西。
 *
 * 注册表驱动：后端多声明一类，这里自动多一个选项，前端不改代码。
 */
export const itemKinds = () => request<ItemKind[]>("/api/item-kinds");

/** 这个空间里正在投的票。 */
export const fetchPolls = (spaceId: string) =>
  request<Poll[]>(`/api/spaces/${spaceId}/polls`);

/** 投一票。改主意就再投一次——**一个人只能改自己那一票**。 */
export const castVote = (spaceId: string, itemId: string, choice: number) =>
  request<Poll>(`/api/spaces/${spaceId}/items/${itemId}:vote`, {
    method: "POST",
    body: JSON.stringify({ choice }),
  });

/** 这次到底要做什么。还没建过卡时返回一个空态，不是 404。 */
export const fetchPlan = (spaceId: string) =>
  request<Plan>(`/api/spaces/${spaceId}/plan`);

/** 写这张卡。**改任何一项，所有人的点头一起失效。** */
export const savePlan = (spaceId: string, body: PlanIn) =>
  request<Plan>(`/api/spaces/${spaceId}/plan`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

/** 到那天了这一屏。计划还没定时间时它是不激活的，不是错误。 */
export const fetchDayOf = (spaceId: string) =>
  request<DayOf>(`/api/spaces/${spaceId}/day-of`);

/** 改我自己此刻的处境。每人一条，覆盖——它是处境不是历史。 */
export const setDayOf = (spaceId: string, state: string, note?: string) =>
  request<DayOf>(`/api/spaces/${spaceId}/day-of`, {
    method: "PUT",
    body: JSON.stringify({ state, note: note ?? null }),
  });

/** 我这边做完了。**全员点头才算完成。** */
export const markDone = (spaceId: string) =>
  request<DayOf>(`/api/spaces/${spaceId}/done`, { method: "POST" });

/** 点错了收回。不给收回的路，人就不敢点。 */
export const unmarkDone = (spaceId: string) =>
  request<DayOf>(`/api/spaces/${spaceId}/done`, { method: "DELETE" });

/** 我确认这次就这么办。 */
export const confirmPlan = (spaceId: string) =>
  request<Plan>(`/api/spaces/${spaceId}/plan:confirm`, { method: "POST" });

/** 放一条东西。放的人取自请求头，不取自请求体。 */
export const addItem = (spaceId: string, body: NewItem) =>
  request<Item>(`/api/spaces/${spaceId}/items`, {
    method: "POST",
    body: JSON.stringify(body),
  });

/**
 * 推进一步、换个负责人，或者改谁能看见。
 *
 * "没给"和"给了 null"是两件事：`assignee_id: null` 是把活放回去，
 * 不给这个键才是不动它。所以这里原样透传调用方给的对象，不补默认值。
 */
export const reviseItem = (spaceId: string, itemId: string, patch: ItemPatch) =>
  request<Item>(`/api/spaces/${spaceId}/items/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

/** 点头。点头的人取自请求头，所以这里没有请求体，也不该有。 */
export const confirmItem = (spaceId: string, itemId: string) =>
  request<Item>(`/api/spaces/${spaceId}/items/${itemId}:confirm`, {
    method: "POST",
  });

/** 开关助手。返回的仍然是完整的一屏——人工那几栏一条都不会少。 */
export const toggleAgent = (spaceId: string, enabled: boolean) =>
  request<Space>(`/api/spaces/${spaceId}/agent:toggle`, {
    method: "POST",
    body: JSON.stringify({ enabled }),
  });

/** 助手写的几条下一步。关掉时是空数组加 200，不是一次故障。 */
export const suggestionsFor = (spaceId: string) =>
  request<Suggestion[]>(`/api/spaces/${spaceId}/suggestions`);

/** 采纳一条。逐条采纳，没有一键全收。 */
export const acceptSuggestion = (spaceId: string, take: TakeSuggestion) =>
  request<Item>(`/api/spaces/${spaceId}/suggestions:accept`, {
    method: "POST",
    body: JSON.stringify(take),
  });

// --- 这一屏自己的判断 -------------------------------------------------------

/**
 * 画布分栏，且一条只出现一次。
 *
 * 「卡住的」和「还没定的」是「要做的」的子集，不是另一批东西。同一张卡出现
 * 在两栏里，看板就开始说谎——数一遍以为有六件事，其实只有四件。所以按
 * 「谁现在最需要人」排序：卡住的、要定的排在前面，剩下的归「要做什么」。
 * 顺序本身就是一句话：先看这里。
 */
export function board(space: Space): {
  stuck: Item[];
  gates: Item[];
  rest: Item[];
} {
  const seen = new Set<string>();
  const take = (items: Item[]) =>
    items.filter((item) => {
      if (seen.has(item.id)) return false;
      seen.add(item.id);
      return true;
    });
  const stuck = take(space.stuck);
  const gates = take(space.open_gates);
  const rest = take(space.cards);
  return { stuck, gates, rest };
}

/**
 * 这件事轮不轮得到我点头。
 *
 * 不该我点头的人不该看到那个按钮——一个点了会被拒的按钮，比没有按钮更糟。
 */
export function myNod(item: Item, me: string): "mine" | "done" | "none" {
  if (!item.deciders.includes(me)) return "none";
  return item.confirmed_by.includes(me) ? "done" : "mine";
}

/**
 * 这一条还能推到哪几个状态。
 *
 * 要真人逐个点头的那一类**不给这条路**：它只能靠点头关上。前端多给一个
 * 按钮，后端会拒，但用户看到的是"点了没反应"——而没反应的按钮迟早
 * 会被当成 bug 修掉，那条不变量也就跟着没了。
 */
export function moves(kind: ItemKind, item: Item): string[] {
  return kind.states.filter(
    (state) =>
      state !== item.state &&
      !(kind.needs_human_decision && kind.done_states.includes(state)),
  );
}

/**
 * 这一屏问得出这一类的必填项吗。
 *
 * 「谁必须点头」要的是人，而这一屏拿不到这个空间有哪些人（只有 UUID，
 * 没有名字）。问不出来就不放进选项里，而不是先收下再报错——后者是把
 * 后端的 422 当成界面。这个判断挂在**能不能问出来**上，不挂在类型的 key 上，
 * 所以新增一类只要它的必填项这里问得出来，就自动多一个选项。
 */
const ASKABLE = new Set([SOURCE, REACH]);

export const canAsk = (kind: ItemKind) =>
  kind.required_extras.every((key) => ASKABLE.has(key));

/**
 * 刚开始的空间：成局时留下的那一张卡，此外什么都还没有。
 *
 * 这不是"没有数据"，是一件正好可以开始做的事。界面要说的是下一步，
 * 不是一个空看板。
 */
export function justStarted(space: Space): boolean {
  return (
    space.drafts.length === 0 &&
    space.open_gates.length === 0 &&
    space.stuck.length === 0 &&
    space.cards.length <= 1 &&
    space.progress.done === 0
  );
}
