/**
 * 「正在招人的事」与「发一份招募」两侧的取数。
 *
 * 类型全部来自 codegen（`lib/api-types.ts`），这里**不手写任何接口类型**。
 * 一个概念在数据库、API、前端用同一个名字，只由 codegen 做大小写转换。
 *
 * ## 后端目前还差三样，界面必须诚实地表现出来
 *
 * 1. **返回里没有负责人。** 领域模型里每份招募都带一个真人 `steward_id`
 *    ——"没有负责人的成局会导致责任分散"——但 HTTP 层没把它透出来。
 *    这里给 `steward_id` / `steward_name` 留了两个读取位：后端补上之后这一层
 *    不用改；在那之前界面**明说"没写谁负责"**，不假装有人负责。
 * 2. **要求分不出硬软。** `qualifications` 是一串纯文本，学生读不出哪条是必须
 *    满足的、哪条是加分的——读错一条就是白跑一趟。在后端把它结构化之前，
 *    两侧共用下面这一对读写函数，用前缀编码，前缀只活在这一个文件里。
 * 3. **没有"列出组织"的端点。** 发一份招募要填 `organization_id`，而界面上不该
 *    让人去背一串 id。这里从已经发过招募的那些反推出可选项，代价是一个全新的、
 *    还没发过任何招募的组织暂时选不到。
 */
import { ApiError, api, type ActionKind } from "./api";
import type { components, paths } from "./api-types";
import { currentPrincipal } from "./session";

export type { ActionKind };
export type Seat = components["schemas"]["SeatOut"];
export type SeatIn = components["schemas"]["SeatIn"];

/**
 * 一份招募。
 *
 * 负责人那两项是**预留的读取位**（见文件头第 1 条），不是另一份手写契约：
 * 后端把 `steward_name` 加进 `OpportunityOut` 的那天，这里删掉这个交集即可。
 */
export type Opportunity = components["schemas"]["OpportunityOut"] & {
  steward_id?: string | null;
  steward_name?: string | null;
};

/**
 * 发一份招募的请求体。
 *
 * `steward_name` 同上：后端现在从请求头取发布者当负责人，这个字段会被忽略。
 * 仍然带上它，是因为不带就等于把发布者填的名字当场丢掉——而丢掉之后，
 * 学生那一侧看到的永远是"没写谁负责"。
 */
export type NewOpportunity =
  paths["/api/opportunities"]["post"]["requestBody"]["content"]["application/json"] & {
    steward_name?: string;
  };

/** 后端查不到组织时回填的名字。界面据此走降级那一栏，而不是把它当成组织名显示。 */
export const ORG_UNKNOWN = "未知组织";

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

/** 还能报名的那些。已满和已过期的后端不返回——列表上每一条都该能点。 */
export const openOpportunities = () => request<Opportunity[]>("/api/opportunities");

export const publish = (body: NewOpportunity) =>
  request<Opportunity>("/api/opportunities", {
    method: "POST",
    body: JSON.stringify(body),
  });

/** 发的时候要选"这是件什么事"，选项来自同一份类别表，前端不写死。 */
export const actionKinds = () => api.actionKinds();

// --- 我能补上哪个缺口 -------------------------------------------------------

/** 一份招募，加上"我能补上它的哪几个角色"。 */
export type Listed = { opportunity: Opportunity; fills: string[] };

/** 我说过我能出什么。它是排序的依据，拿不到也不该挡住列表。 */
export async function whatICanDo(): Promise<string[]> {
  const mine = await api.myIntents();
  return [...new Set(mine.flatMap((intent) => intent.content.offers))];
}

function matches(role: string, mine: string): boolean {
  const a = role.trim();
  const b = mine.trim();
  if (!a || !b) return false;
  return a === b || a.includes(b) || b.includes(a);
}

function fillsOf(opportunity: Opportunity, canDo: string[]): string[] {
  return opportunity.seats
    .filter((seat) => seat.gap > 0)
    .map((seat) => seat.role)
    .filter((role) => canDo.some((mine) => matches(role, mine)));
}

/**
 * 排序：我能补上的缺口排前面，其次截止得急的。
 *
 * 按发布时间排是给发布方看的顺序，不是给学生看的。学生问的是"哪一条我能上"，
 * 而一条他补不上的招募排在第一位，只会让他把整个列表读成噪音。
 */
export function arrange(list: Opportunity[], canDo: string[]): Listed[] {
  return list
    .map((opportunity) => ({ opportunity, fills: fillsOf(opportunity, canDo) }))
    .sort(
      (a, b) =>
        b.fills.length - a.fills.length ||
        Date.parse(a.opportunity.deadline) - Date.parse(b.opportunity.deadline),
    );
}

// --- 要求：必须满足的，还是加分的 -------------------------------------------

const MUST = "必须：";
const PLUS = "加分：";

/** `hard` 为 null 表示这条没说清是哪种——不擅自当成硬要求，那会把够格的人挡在外面。 */
export type Requirement = { text: string; hard: boolean | null };

export function readRequirement(raw: string): Requirement {
  if (raw.startsWith(MUST)) return { text: raw.slice(MUST.length), hard: true };
  if (raw.startsWith(PLUS)) return { text: raw.slice(PLUS.length), hard: false };
  return { text: raw, hard: null };
}

export function writeRequirement(text: string, hard: boolean): string {
  return (hard ? MUST : PLUS) + text;
}

// --- 可选的组织 -------------------------------------------------------------

export type Org = { id: string; name: string; verified: boolean };

/**
 * 从已经发过招募的那些里反推出可选的组织（见文件头第 3 条）。
 *
 * 未验证的照样列出来，不悄悄过滤掉：选中之后拦住并说清"这个组织还没被核过"，
 * 比让人对着一个短了一项的下拉框猜自己为什么找不到有用。
 */
export function organizationsIn(list: Opportunity[]): Org[] {
  const found = new Map<string, Org>();
  for (const o of list) {
    if (o.organization_name === ORG_UNKNOWN) continue;
    found.set(o.organization_id, {
      id: o.organization_id,
      name: o.organization_name,
      verified: o.organization_verified,
    });
  }
  return [...found.values()].sort((a, b) => a.name.localeCompare(b.name, "zh"));
}

// --- 一份还没发出去的招募 ---------------------------------------------------

export type DraftSeat = { role: string; capacity: string };
export type DraftRequirement = { text: string; hard: boolean };

export type Draft = {
  organizationId: string;
  kindKey: string;
  title: string;
  goal: string;
  seats: DraftSeat[];
  steward: string;
  /** `datetime-local` 的原样文本，不是 ISO。转换只在送出去的那一步做。 */
  deadline: string;
  location: string;
  requirements: DraftRequirement[];
};

export const emptyDraft = (): Draft => ({
  organizationId: "",
  kindKey: "",
  title: "",
  goal: "",
  seats: [{ role: "", capacity: "1" }],
  steward: "",
  deadline: "",
  location: "",
  requirements: [],
});

function seatsOf(draft: Draft): SeatIn[] {
  return draft.seats
    .filter((seat) => seat.role.trim())
    .map((seat) => ({
      role: seat.role.trim(),
      capacity: Number.parseInt(seat.capacity, 10),
    }));
}

/**
 * 还差什么。**逐条说清缺的是哪一样**，不是一句"请填写完整"。
 *
 * 拦住的理由要能直接读成下一步动作：一份缺角色或缺负责人的招募，学生既判断不出
 * 自己能不能补上，也找不到人问——它发出去只会浪费两边的时间。
 */
export function missing(draft: Draft, orgs: Org[], now: Date): string[] {
  const gaps: string[] = [];

  if (!draft.title.trim()) gaps.push("还没写这件事叫什么。");
  if (!draft.goal.trim()) gaps.push("还没写这件事要做成什么样。");
  if (!draft.kindKey) gaps.push("还没选这是件什么事。");

  const seats = seatsOf(draft);
  if (seats.length === 0) {
    gaps.push("还没写缺哪些角色。只写「招若干人」，谁都不知道自己能不能补上。");
  } else if (seats.some((seat) => !Number.isFinite(seat.capacity) || seat.capacity < 1)) {
    gaps.push("有一个角色没写要几个人。");
  } else if (new Set(seats.map((seat) => seat.role)).size !== seats.length) {
    gaps.push("同一个角色写了两遍，合成一条。");
  }

  if (!draft.steward.trim()) {
    gaps.push("还没写谁负责这件事。没人负责的话，事情会烂在那里。");
  }

  if (!draft.deadline) {
    gaps.push("还没写什么时候截止。");
  } else if (!(Date.parse(draft.deadline) > now.getTime())) {
    gaps.push("截止时间已经过了，往后挪一挪。");
  }

  const org = orgs.find((o) => o.id === draft.organizationId);
  if (!org) gaps.push("还没选这份招募由哪个组织发。");
  else if (!org.verified) {
    gaps.push(`${org.name}还没被校园核过。换一个组织，或者先去把这一步办了。`);
  }

  if (draft.requirements.some((r) => !r.text.trim())) {
    gaps.push("有一条要求是空的，写上或者删掉。");
  }

  return gaps;
}

/** 送出去的那一刻才把本地文本转成接口要的形状。 */
export function toRequest(draft: Draft): NewOpportunity {
  return {
    organization_id: draft.organizationId,
    kind_key: draft.kindKey,
    title: draft.title.trim(),
    goal: draft.goal.trim(),
    seats: seatsOf(draft),
    deadline: new Date(draft.deadline).toISOString(),
    location_scope: draft.location.trim() || null,
    qualifications: draft.requirements
      .filter((r) => r.text.trim())
      .map((r) => writeRequirement(r.text.trim(), r.hard)),
    steward_name: draft.steward.trim(),
  };
}

/**
 * 把还没发出去的草稿摆成学生会看到的样子。
 *
 * 预览和列表渲染的是**同一个组件**，所以"预览"不是一张另外画的示意图——
 * 另画一张的话，两边迟早对不上，而对不上的那一刻，预览就成了误导。
 */
export function asPreview(draft: Draft, orgs: Org[]): Opportunity {
  const org = orgs.find((o) => o.id === draft.organizationId);
  const seats: Seat[] = seatsOf(draft).map((seat) => ({
    role: seat.role,
    capacity: Number.isFinite(seat.capacity) ? seat.capacity : 0,
    filled: 0,
    gap: Number.isFinite(seat.capacity) ? seat.capacity : 0,
  }));
  return {
    id: "",
    organization_id: org?.id ?? "",
    organization_name: org?.name ?? ORG_UNKNOWN,
    organization_verified: org?.verified ?? false,
    kind_key: draft.kindKey,
    title: draft.title.trim() || "（还没写标题）",
    goal: draft.goal.trim(),
    seats,
    total_gap: seats.reduce((sum, seat) => sum + seat.gap, 0),
    deadline: draft.deadline ? new Date(draft.deadline).toISOString() : "",
    location_scope: draft.location.trim() || null,
    qualifications: draft.requirements
      .filter((r) => r.text.trim())
      .map((r) => writeRequirement(r.text.trim(), r.hard)),
    state: "open",
    // 后端现在必给负责人（领域里它本来就是必填的，只是接口曾经没透出）。
    steward_id: "",
    steward_name: draft.steward.trim(),
  };
}
