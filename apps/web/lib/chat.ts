/**
 * 项目空间里那段群聊的取数。
 *
 * 类型全部来自 codegen（`lib/api-types.ts`），这里**不手写任何接口类型**。
 * 一个概念在数据库、API、前端用同一个名字，只由 codegen 做大小写转换。
 *
 * 和画布分开取数，**故意不合成一个接口**：说话这件事不该被画布的任何一段
 * 拖垮，反过来也一样。助手那一段更是——它挂了，大家照样能说话。
 */
import { ApiError } from "./api";
import type { components } from "./api-types";
import { currentPrincipal } from "./session";
import type { Space } from "./space";

export type Chat = components["schemas"]["ChatOut"];
export type Message = components["schemas"]["MessageOut"];
export type Thread = components["schemas"]["ThreadOut"];
export type NewMessage = components["schemas"]["SayRequest"];

/** 一张话题卡。后端是 StrEnum，这里给常量免得字面量散落各处拼错。 */
export const TOPIC = "topic";

/**
 * 这一段自己的取数。
 *
 * 和画布那边长得一样但是各写一份：那边是私有的，而为了共用一个 helper 去改
 * 一个正在被别人改的文件，代价比这十行大。
 */
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

/**
 * 说过的话，全部。
 *
 * 不分页、不截断——「往回翻得到当时怎么说的」是这一段的承诺，一个默认只给
 * 最近五十条的接口会让这件事做不到。
 */
export const fetchChat = (spaceId: string) =>
  request<Chat>(`/api/spaces/${spaceId}/chat`);

/** 说一句。说话的人取自请求头，不取自请求体。 */
export const say = (spaceId: string, body: NewMessage) =>
  request<Message>(`/api/spaces/${spaceId}/chat`, {
    method: "POST",
    body: JSON.stringify(body),
  });

/**
 * 让助手把还没定的事变成几句可以回答的话。
 *
 * 助手关着、或者它一时说不出话时是空数组加 200，**不是一次故障**。
 */
export const askForTopics = (spaceId: string) =>
  request<Message[]>(`/api/spaces/${spaceId}/chat:topics`, { method: "POST" });

// --- 这一段自己的判断 -------------------------------------------------------

/**
 * 主线上从上到下的东西。
 *
 * 两种：一句话，和一张话题卡（卡下面挂着回复）。
 *
 * **按时间排，不给话题卡置顶。** 没人回的那张不藏起来——它照样在它当时的
 * 位置上；但也不该一直顶在最上面：没人接的话题说明这张卡问得不对，或者
 * 这件事大家不在意，把它顶上去只会让更多人学会略过助手说的话。
 *
 * 挂在卡下面的回复不在主线上再来一遍。而**回给一条不是话题卡的消息**
 * 仍然留在主线上——那种消息后端接得下，`threads` 里却没有它的位置，
 * 漏掉就等于聊天记录少了一句。这一段承诺的是一句都不少。
 */
export type Line =
  | { kind: "said"; id: string; at: string; message: Message }
  | {
      kind: "card";
      id: string;
      at: string;
      topic: Message;
      replies: Message[];
      answered: boolean;
    };

export function timeline(chat: Chat): Line[] {
  const cards = new Map(chat.threads.map((t) => [t.topic.id, t]));
  const tucked = new Set(
    chat.threads.flatMap((t) => t.replies.map((r) => r.id)),
  );

  const lines: Line[] = [];
  for (const message of chat.messages) {
    if (tucked.has(message.id)) continue;
    const thread = cards.get(message.id);
    lines.push(
      thread
        ? {
            kind: "card",
            id: message.id,
            at: message.created_at,
            topic: thread.topic,
            replies: [...thread.replies],
            answered: thread.answered,
          }
        : { kind: "said", id: message.id, at: message.created_at, message },
    );
  }
  return lines;
}

/** 一句话都还没说。刚被拉进来的那一刻，这里最要紧。 */
export const nobodySpokeYet = (chat: Chat) => chat.messages.length === 0;

/**
 * 一张话题卡指的那件事：叫什么、定下来了没有。
 *
 * 接口只给得出一个编号，而编号不能上屏。名字要去画布那边问——问不到就少说
 * 一行，不把一串编号糊到脸上。
 *
 * `settled` 用「还在等着定的那几件里有没有它」来判断，不去猜状态字段：
 * 这一段真正要说的是「聊完还得去点头」，而该不该去点头正是这个判断。
 */
export type About = { title: string; settled: boolean };

export function whatTheyreAbout(space: Space): Map<string, About> {
  const waiting = new Set(space.open_gates.map((item) => item.id));
  const index = new Map<string, About>();
  for (const item of [...space.cards, ...space.open_gates, ...space.stuck]) {
    index.set(item.id, { title: item.title, settled: !waiting.has(item.id) });
  }
  return index;
}

/**
 * 哪一天说的。
 *
 * 一条不截断的记录往回翻的时候，没有日子就没法定位。只到天：一段对话里
 * 精确到分钟的时间戳除了让人盯着看，什么也没多说。
 */
export function dayPhrase(iso: string, now: Date): string {
  const t = new Date(iso);
  const midnight = (d: Date) =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((midnight(now) - midnight(t)) / 86_400_000);
  if (days <= 0) return "今天";
  if (days === 1) return "昨天";
  return `${t.getMonth() + 1} 月 ${t.getDate()} 日`;
}
