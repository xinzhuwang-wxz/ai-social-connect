/**
 * 第六屏的产品行为：一起把这件事做完的地方。
 *
 * 断言的是用户看到什么、能做什么，不是组件内部长什么样。这一屏最要紧的一条
 * 是「关掉助手之后整屏照常可用」——它是产品的一条承诺，所以它有一条专门的
 * 测试，而不是靠人工点一遍。
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SpaceScreen } from "@/components/space-screen";

const SPACE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const ME = "33333333-3333-4333-8333-333333333333";
const SU = "44444444-4444-4444-8444-444444444444";
const CHEN = "55555555-5555-4555-8555-555555555555";

const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString();

/** 随产品发布的四种条目。前端不写死这张表，它从后端来。 */
const KINDS = [
  {
    key: "task",
    label: "要做的事",
    states: ["todo", "doing", "done"],
    done_states: ["done"],
    counts_toward_progress: true,
    needs_human_decision: false,
    required_extras: [],
    agent_may_draft: true,
  },
  {
    key: "material",
    label: "我们做的东西",
    states: ["shared"],
    done_states: [],
    counts_toward_progress: false,
    needs_human_decision: false,
    required_extras: ["source", "reach"],
    agent_may_draft: true,
  },
  {
    key: "decision_gate",
    label: "要定的事",
    states: ["open", "settled"],
    done_states: ["settled"],
    counts_toward_progress: false,
    needs_human_decision: true,
    required_extras: ["deciders"],
    agent_may_draft: true,
  },
  {
    key: "note",
    label: "记一笔",
    states: ["open"],
    done_states: [],
    counts_toward_progress: false,
    needs_human_decision: false,
    required_extras: [],
    agent_may_draft: true,
  },
];

type Item = {
  id: string;
  space_id: string;
  kind: string;
  label: string;
  title: string;
  body?: string | null;
  state: string;
  assignee_id?: string | null;
  due_at?: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  drafted_by_agent: boolean;
  accepted_by?: string | null;
  awaiting_a_person: boolean;
  deciders: string[];
  confirmed_by: string[];
  reach?: string | null;
  source?: string | null;
  notice?: string | null;
};

const item = (rest: Partial<Item> & Pick<Item, "id" | "kind" | "label" | "title" | "state">): Item => ({
  space_id: SPACE_ID,
  created_by: ME,
  created_at: inHours(-20),
  updated_at: inHours(-1),
  drafted_by_agent: false,
  awaiting_a_person: false,
  deciders: [],
  confirmed_by: [],
  ...rest,
});

const SCRIPT = item({
  id: "11111111-1111-4111-8111-111111111111",
  kind: "task",
  label: "要做的事",
  title: "周三之前把脚本写完",
  state: "done",
  assignee_id: ME,
});

const SHOOT = item({
  id: "22222222-2222-4222-8222-222222222222",
  kind: "task",
  label: "要做的事",
  title: "周四晚上拍夜景",
  state: "todo",
  assignee_id: null,
  due_at: inHours(40),
  notice: "还没人认领",
});

/** 别人手上的活。这一屏拿不到他的名字，只能说「有人在做」。 */
const LIGHTS = item({
  id: "99999999-9999-4999-8999-aaaaaaaaaaaa",
  kind: "task",
  label: "要做的事",
  title: "去借一盏灯",
  state: "doing",
  assignee_id: SU,
});

/** 我已经点过头的那一件。剩下两个人的名字要出现在卡上。 */
const CREDIT = item({
  id: "33333333-3333-4333-8333-aaaaaaaaaaaa",
  kind: "decision_gate",
  label: "要定的事",
  title: "作品署名怎么算",
  state: "open",
  deciders: [ME, SU, CHEN],
  confirmed_by: [ME],
  notice: "还差苏晚和陈牧点头",
});

/** 还轮得到我点头的那一件。 */
const PLACE = item({
  id: "44444444-4444-4444-8444-aaaaaaaaaaaa",
  kind: "decision_gate",
  label: "要定的事",
  title: "在哪剪片子",
  state: "open",
  deciders: [ME, CHEN],
  confirmed_by: [],
  notice: "还差陈牧和林一点头",
});

const CUT = item({
  id: "55555555-5555-4555-8555-aaaaaaaaaaaa",
  kind: "material",
  label: "我们做的东西",
  title: "第一版粗剪",
  state: "shared",
  source: "苏晚周二拍的那段",
  reach: "ours",
});

const GUESS_ONE = item({
  id: "66666666-6666-4666-8666-aaaaaaaaaaaa",
  kind: "task",
  label: "要做的事",
  title: "把片头字幕做出来",
  state: "todo",
  drafted_by_agent: true,
  awaiting_a_person: true,
  notice: "这是我猜的，你看对不对",
});

const GUESS_TWO = item({
  id: "77777777-7777-4777-8777-aaaaaaaaaaaa",
  kind: "task",
  label: "要做的事",
  title: "问问社团有没有灯",
  state: "todo",
  drafted_by_agent: true,
  awaiting_a_person: true,
  notice: "这是我猜的，你看对不对",
});

const SPACE = {
  id: SPACE_ID,
  title: "流浪猫短片",
  agent_enabled: true,
  cards: [SCRIPT, SHOOT, LIGHTS, CREDIT, PLACE, CUT],
  open_gates: [CREDIT, PLACE],
  stuck: [SHOOT],
  drafts: [GUESS_ONE, GUESS_TWO],
  // 助手写的两条也是「要做的事」，但它们不在这里面：既不进分子也不进分母。
  progress: { done: 1, total: 3 },
  summary: "3 件事做完 1 件，2 件事等着定，1 件卡住了，2 条等你过目",
  // PRD 要求房间顶部持续展示成员。少了它，「还差谁确认」只能说"还差 2 个人"，
  // 而那催不动任何人。
  members: [
    { principal_id: ME, display_name: "林知遥" },
    { principal_id: CHEN, display_name: "陈牧" },
  ],
  // 阶段由真实事实派生，不由聊天量派生（不变量 6）。
  growth: "seedling",
  growth_word: "长出幼苗",
  growth_why: "有人开始认领要做的事了",
};

/** 关掉助手之后的同一屏：人工那几栏一条都没少，只有草稿那一栏空了。 */
const SPACE_OFF: typeof SPACE = { ...SPACE, agent_enabled: false, drafts: [] };

/** 刚成局：只有一张来自「留给真人决定」的卡。 */
const FIRST = item({
  id: "88888888-8888-4888-8888-aaaaaaaaaaaa",
  kind: "task",
  label: "要做的事",
  title: "谁来定最后一版剪辑",
  state: "open",
  assignee_id: SU,
  due_at: inHours(48),
});

const FRESH: typeof SPACE = {
  // 从 SPACE 展开而不是重列一遍：漏一个字段，屏上就会崩在一个和这条
  // 用例无关的地方，而报出来的是"找不到某句文案"。
  ...SPACE,
  cards: [FIRST],
  open_gates: [],
  stuck: [],
  drafts: [],
  progress: { done: 0, total: 1 },
  summary: "1 件事做完 0 件",
};

const BARE: typeof SPACE = {
  ...FRESH,
  cards: [],
  progress: { done: 0, total: 0 },
  summary: "还没有要做的事",
};

const TIPS = [
  { kind: "task", title: "周五之前把第一版剪出来", grounded_in: ["周三之前把脚本写完"] },
  { kind: "task", title: "问一下能不能借到灯", grounded_in: ["周四晚上拍夜景"] },
];

/** 还没人写过这张卡。**这是一个状态，不是错误。** */
const NO_PLAN = {
  exists: false,
  nodded: [],
  waiting_on: [],
  confirmed: false,
  i_nodded: false,
  missing: ["什么时候", "在哪集合"],
};

const PLAN = {
  ...NO_PLAN,
  exists: true,
  title: "周六去后山拍流浪猫",
  starts_at: "2026-08-15T09:00:00Z",
  place: "北门地铁口",
  bring: "相机、充电宝",
  waiting_on: [ME, CHEN],
  missing: [],
};

/** 还没到那天。**这一块此时根本不该占地方。** */
const NOT_YET = {
  active: false,
  standings: [],
  done_by: [],
  done_waiting_on: [],
  all_done: false,
  i_marked_done: false,
};

/** 就是今天。 */
const TODAY = {
  ...NOT_YET,
  active: true,
  starts_at: "2026-08-15T09:00:00Z",
  where: "北门地铁口",
  bring: "相机",
  done_waiting_on: [ME, CHEN],
};

type Call = { url: string; method: string; body: unknown };

type Options = {
  space?: typeof SPACE;
  offSpace?: typeof SPACE;
  tips?: typeof TIPS;
  spaceStatus?: number;
  kindsStatus?: number;
  tipsStatus?: number;
  plan?: Record<string, unknown>;
  dayOf?: Record<string, unknown>;
  polls?: Record<string, unknown>[];
  writeStatus?: number;
  hang?: boolean;
};

function mockApi(opts: Options = {}): Call[] {
  const calls: Call[] = [];
  const reply = (body: unknown, status = 200) => ({
    ok: status < 300,
    status,
    json: async () => body,
  });
  let on = (opts.space ?? SPACE).agent_enabled;
  let plan: Record<string, unknown> = opts.plan ?? NO_PLAN;
  let dayOf: Record<string, unknown> = opts.dayOf ?? NOT_YET;

  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (opts.hang) return new Promise(() => {});
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      calls.push({ url, method, body });

      // 房间里挂着聊天。桩不覆盖它的话，它会掉进兜底分支，
      // 而兜底返回的东西会被当成一屏聊天渲染出来。
      if (url.endsWith("/chat")) {
        return reply({ messages: [], threads: [] });
      }
      if (url.endsWith("/polls")) {
        return reply(opts.polls ?? []);
      }
      if (url.endsWith(":vote")) {
        return reply((opts.polls ?? [])[0] ?? null);
      }
      if (url.endsWith("/day-of") && method !== "GET") {
        dayOf = { ...dayOf, my_state: (body as { state: string }).state };
        return reply(dayOf);
      }
      if (url.endsWith("/day-of")) {
        return reply(dayOf);
      }
      if (url.endsWith("/done")) {
        const mine = method !== "DELETE";
        dayOf = {
          ...dayOf,
          i_marked_done: mine,
          done_by: mine ? [ME] : [],
          done_waiting_on: mine ? [CHEN] : [ME, CHEN],
          all_done: false,
        };
        return reply(dayOf);
      }
      if (url.endsWith("/plan:confirm")) {
        plan = { ...plan, i_nodded: true, nodded: [ME], waiting_on: [CHEN] };
        return reply(plan);
      }
      if (url.endsWith("/plan") && method === "PUT") {
        // 后端按内容摘要记点头：改了内容，所有人的确认一起失效。
        plan = {
          ...plan,
          ...(body as Record<string, unknown>),
          exists: true,
          nodded: [],
          waiting_on: [ME, CHEN],
          i_nodded: false,
          confirmed: false,
          missing: [],
        };
        return reply(plan);
      }
      if (url.endsWith("/plan")) {
        return reply(plan);
      }
      if (url === "/api/item-kinds") {
        return opts.kindsStatus
          ? reply({ detail: "没连上" }, opts.kindsStatus)
          : reply(KINDS);
      }
      if (url.endsWith("agent:toggle")) {
        on = Boolean((body as { enabled: boolean }).enabled);
        return reply(on ? (opts.space ?? SPACE) : (opts.offSpace ?? SPACE_OFF));
      }
      if (url.endsWith("/suggestions")) {
        if (opts.tipsStatus) return reply({ detail: "没连上" }, opts.tipsStatus);
        // 助手关着的时候是空数组加 200，不是一次故障。
        return reply(on ? (opts.tips ?? TIPS) : []);
      }
      if (url.endsWith(":accept")) {
        return opts.writeStatus
          ? reply({ detail: "没连上" }, opts.writeStatus)
          : reply(SCRIPT, 201);
      }
      if (url.endsWith(":confirm")) {
        return opts.writeStatus
          ? reply({ detail: "没连上" }, opts.writeStatus)
          : reply(CREDIT);
      }
      if (url.endsWith("/items")) {
        return opts.writeStatus
          ? reply({ detail: "没连上" }, opts.writeStatus)
          : reply(SCRIPT, 201);
      }
      if (url.includes("/items/")) {
        return opts.writeStatus
          ? reply({ detail: "没连上" }, opts.writeStatus)
          : reply(SHOOT);
      }
      if (url === `/api/spaces/${SPACE_ID}`) {
        if (opts.spaceStatus) return reply({ detail: "没连上" }, opts.spaceStatus);
        const current = on ? (opts.space ?? SPACE) : (opts.offSpace ?? SPACE_OFF);
        return reply(current);
      }
      return reply(null, 404);
    }),
  );
  return calls;
}

const group = (name: string) => within(screen.getByRole("region", { name }));
const card = (title: string) => within(screen.getByRole("article", { name: title }));
const writes = (calls: Call[]) => calls.filter((c) => c.method !== "GET");

const opened = async () => {
  render(<SpaceScreen spaceId={SPACE_ID} />);
  // 条目类型是第二次取数：等它回来，卡上的操作按钮才齐。
  await screen.findByRole("button", { name: "我来做" });
};

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.localStorage.setItem("cofield.principal", ME);
});

describe("这是画布，不是群聊", () => {
  it("四个分组各就各位，一屏看得见要做什么、卡在哪、还有哪些决定没关", async () => {
    mockApi();
    await opened();

    expect(group("卡在哪").getByText("周四晚上拍夜景")).toBeVisible();
    expect(group("还没定下来的").getByText("作品署名怎么算")).toBeVisible();
    expect(group("要做什么").getByText("周三之前把脚本写完")).toBeVisible();
    expect(group("等你过目").getByText("把片头字幕做出来")).toBeVisible();
  });

  it("一条只出现一次：卡住的和要定的不在「要做什么」里再来一遍", async () => {
    mockApi();
    await opened();

    const rest = group("要做什么");
    expect(rest.queryByText("周四晚上拍夜景")).toBeNull();
    expect(rest.queryByText("作品署名怎么算")).toBeNull();
    expect(screen.getAllByRole("article", { name: "周四晚上拍夜景" })).toHaveLength(1);
  });

  it("每条东西都有类型、状态、负责人和时限，不是一句沉底的话", async () => {
    mockApi();
    await opened();

    const shoot = card("周四晚上拍夜景");
    expect(shoot.getByText("要做的事")).toBeVisible();
    expect(shoot.getByText("还没人认领")).toBeVisible();
    expect(shoot.getByText(/还没开始/)).toBeVisible();
    expect(card("周三之前把脚本写完").getByText(/你在做/)).toBeVisible();
  });

  it("认领一件没人认的事，是一次指派，不是发一句「我来吧」", async () => {
    const calls = mockApi();
    await opened();

    await userEvent.click(card("周四晚上拍夜景").getByRole("button", { name: "我来做" }));

    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0]).toMatchObject({
      method: "PATCH",
      body: { assignee_id: ME },
    });
  });

  it("不把任何人的内部编号糊到脸上", async () => {
    mockApi();
    await opened();

    // 别人的名字这一屏拿不到，那就说「有人」，不显示一串没人看得懂的编号。
    expect(document.body.textContent ?? "").not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}/);
    expect(card("去借一盏灯").getByText(/有人在做/)).toBeVisible();
  });
});

describe("要定的事", () => {
  it("说的是还差谁，不是一个比例", async () => {
    mockApi();
    await opened();

    expect(card("作品署名怎么算").getByText("还差苏晚和陈牧点头")).toBeVisible();
    expect(document.body.textContent ?? "").not.toMatch(/\d\s*\/\s*\d|已确认|%|％/);
  });

  it("轮到我点头才有那个按钮，点过的人看到的是已经点过", async () => {
    const calls = mockApi();
    await opened();

    expect(card("作品署名怎么算").queryByRole("button", { name: "我点头" })).toBeNull();
    expect(card("作品署名怎么算").getByText("你点过头了")).toBeVisible();

    await userEvent.click(card("在哪剪片子").getByRole("button", { name: "我点头" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    // 点头的是请求头里的那个人，所以这个请求没有请求体。
    expect(writes(calls)[0]).toMatchObject({ method: "POST", body: null });
    expect(writes(calls)[0]?.url).toContain(":confirm");
  });

  it("推进不了：要真人点头的那一类不给「做完了」这条路", async () => {
    mockApi();
    await opened();

    expect(card("在哪剪片子").queryByRole("button", { name: "做完了" })).toBeNull();
    expect(card("在哪剪片子").queryByRole("button", { name: /定下来了/ })).toBeNull();
  });
});

describe("助手在角落", () => {
  it("它写的东西一眼可辨，采纳之前不进进度", async () => {
    mockApi();
    await opened();

    // 助手起草的两条也是「要做的事」，算进去就该是 5 件。
    expect(within(screen.getByRole("region", { name: "这件事现在到哪了" })).getByText("3 件")).toBeVisible();
    expect(screen.queryByLabelText(/一共 5 件/)).toBeNull();

    const guess = card("把片头字幕做出来");
    expect(guess.getByText("还没人认下这条，它不算数")).toBeVisible();
    // 不算数的东西不给操作按钮：给了就等于让人以为它已经在推进了。
    expect(guess.queryByRole("button")).toBeNull();
  });

  it("每条建议都能一键说「不用了」，说完不再回来", async () => {
    const calls = mockApi();
    await opened();

    const corner = within(screen.getByRole("complementary", { name: "助手写的" }));
    expect(corner.getByText("周五之前把第一版剪出来")).toBeVisible();
    expect(corner.getByText(/我是看着这个写的：周三之前把脚本写完/)).toBeVisible();

    await userEvent.click(
      within(corner.getByRole("listitem", { name: "周五之前把第一版剪出来" })).getByRole(
        "button",
        { name: "不用了" },
      ),
    );

    expect(screen.queryByText("周五之前把第一版剪出来")).toBeNull();
    expect(screen.getByText("问一下能不能借到灯")).toBeVisible();
    // 说一句「不用了」不该往服务端写任何东西。
    expect(writes(calls)).toHaveLength(0);
  });

  it("逐条采纳，并且把它写的依据一起带回去", async () => {
    const calls = mockApi();
    await opened();

    await userEvent.click(
      within(screen.getByRole("listitem", { name: "问一下能不能借到灯" })).getByRole("button", {
        name: "放进来",
      }),
    );

    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0]).toMatchObject({
      method: "POST",
      body: { kind: "task", title: "问一下能不能借到灯", grounded_in: ["周四晚上拍夜景"] },
    });
    // 没有一键全收：另一条还在那儿等着单独被决定。
    expect(screen.getByText("周五之前把第一版剪出来")).toBeVisible();
  });

  it("它不占主区：那张卡在四个分组之后", async () => {
    mockApi();
    await opened();

    const main = screen.getByRole("main");
    const corner = screen.getByRole("complementary", { name: "助手写的" });
    const groups = screen.getByRole("region", { name: "等你过目" });
    expect(main).toContainElement(corner);
    expect(groups.compareDocumentPosition(corner) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });
});

describe("关掉助手之后整屏照常", () => {
  it("建议那一栏消失，四个分组和所有操作按钮一格不少", async () => {
    mockApi();
    await opened();
    expect(screen.getByRole("complementary", { name: "助手写的" })).toBeVisible();

    await userEvent.click(screen.getByRole("switch", { name: "助手帮我看着" }));

    await waitFor(() => {
      expect(screen.queryByRole("complementary", { name: "助手写的" })).toBeNull();
    });

    // 四个分组一个不少。
    for (const name of ["卡在哪", "还没定下来的", "要做什么", "等你过目"]) {
      expect(screen.getByRole("region", { name })).toBeVisible();
    }
    // 人工那几栏的东西一条不少。
    expect(group("卡在哪").getByText("周四晚上拍夜景")).toBeVisible();
    expect(group("还没定下来的").getByText("作品署名怎么算")).toBeVisible();
    expect(group("要做什么").getByText("第一版粗剪")).toBeVisible();
    // 所有操作按钮一个不少。
    for (const name of ["我来做", "我点头", "放回去", "放一条东西", "放到外面去"]) {
      expect(screen.getByRole("button", { name })).toBeEnabled();
    }
    expect(within(screen.getByRole("region", { name: "这件事现在到哪了" })).getByText("3 件")).toBeVisible();
    // 关掉助手不是一次故障，界面上不该出现任何报错。
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("草稿没有被删掉，界面明说重新打开就回来", async () => {
    const calls = mockApi();
    await opened();

    await userEvent.click(screen.getByRole("switch", { name: "助手帮我看着" }));

    expect(
      await group("等你过目").findByText(/助手关着。它写过的东西还留着，重新打开就回来/),
    ).toBeVisible();
    expect(writes(calls)[0]).toMatchObject({ body: { enabled: false } });
    expect(screen.getByRole("switch", { name: "助手帮我看着" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });
});

describe("放一条东西", () => {
  it("选项来自后端的清单，不是前端写死的一张表", async () => {
    mockApi();
    await opened();

    await userEvent.click(screen.getByRole("button", { name: "放一条东西" }));

    expect(screen.getByRole("radio", { name: "要做的事" })).toBeVisible();
    expect(screen.getByRole("radio", { name: "我们做的东西" })).toBeVisible();
    expect(screen.getByRole("radio", { name: "记一笔" })).toBeVisible();
    // 「要定的事」要写明谁必须点头，而这一屏问不出人名——问不出来就不放进选项，
    // 而不是先收下再让后端拒。
    expect(screen.queryByRole("radio", { name: "要定的事" })).toBeNull();
  });

  it("「我们做的东西」必须说清从哪来的、谁能看见", async () => {
    const calls = mockApi();
    await opened();

    await userEvent.click(screen.getByRole("button", { name: "放一条东西" }));
    await userEvent.click(screen.getByRole("radio", { name: "我们做的东西" }));

    await userEvent.type(screen.getByLabelText("一句话说清是什么"), "第二版粗剪");
    expect(screen.getByRole("button", { name: "放上去" })).toBeDisabled();

    await userEvent.type(screen.getByLabelText("从哪来的"), "陈牧周四剪的");
    await userEvent.click(screen.getByRole("radio", { name: "只有我们几个看得见" }));
    await userEvent.click(screen.getByRole("button", { name: "放上去" }));

    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0]).toMatchObject({
      method: "POST",
      body: {
        kind: "material",
        title: "第二版粗剪",
        extras: { source: "陈牧周四剪的", reach: "ours" },
      },
    });
  });

  it("收回来是一步完成的，不问为什么", async () => {
    const calls = mockApi();
    await opened();

    expect(card("第一版粗剪").getByText("只有我们几个看得见")).toBeVisible();
    await userEvent.click(card("第一版粗剪").getByRole("button", { name: "放到外面去" }));

    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0]).toMatchObject({ method: "PATCH", body: { reach: "outside" } });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("五态", () => {
  it("首次：说清这一屏是干什么的，不是一片白", async () => {
    mockApi();
    await opened();

    expect(screen.getByRole("heading", { name: "流浪猫短片" })).toBeVisible();
    expect(screen.getByText(SPACE.summary)).toBeVisible();
    expect(screen.getByRole("switch", { name: "助手帮我看着" })).toBeVisible();
    expect(screen.getByText("随时关掉，这一屏其余照常")).toBeVisible();
  });

  it("加载：给骨架，不是转圈", () => {
    mockApi({ hang: true });
    render(<SpaceScreen spaceId={SPACE_ID} />);

    expect(screen.getByLabelText("加载中")).toBeVisible();
  });

  it("空：刚开始的时候把下一步说出来，不是一个空看板", async () => {
    mockApi({ space: FRESH });
    render(<SpaceScreen spaceId={SPACE_ID} />);

    expect(await screen.findByText("先做这件事：谁来定最后一版剪辑")).toBeVisible();
    expect(screen.getByText(/认领它，或者往下面再放一条/)).toBeVisible();
    // 下一步就摆在手边：不用先找到一个按钮才能放第一条东西。
    expect(await screen.findByRole("region", { name: "放一条东西" })).toBeVisible();
  });

  it("空：连那一张卡都没有时，说清该放点什么", async () => {
    mockApi({ space: BARE });
    render(<SpaceScreen spaceId={SPACE_ID} />);

    expect(await screen.findByText("这里还什么都没有。")).toBeVisible();
    expect(screen.getByText(/放一条要做的事，写清是什么/)).toBeVisible();
    expect(await screen.findByRole("region", { name: "放一条东西" })).toBeVisible();
  });

  it("错误：说清哪里断了，并说明什么都没有被改动", async () => {
    mockApi({ spaceStatus: 500 });
    render(<SpaceScreen spaceId={SPACE_ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("打不开这个地方");
    expect(screen.getByRole("button", { name: "再试一次" })).toBeVisible();
  });

  it("降级：助手那一段取不到时，画布照常，只是那一栏不显示", async () => {
    mockApi({ tipsStatus: 503 });
    await opened();

    expect(screen.queryByRole("complementary", { name: "助手写的" })).toBeNull();
    // 取不到建议不是一次事故，不该弹红框。
    expect(screen.queryByRole("alert")).toBeNull();
    // 画布一格不少。
    for (const name of ["卡在哪", "还没定下来的", "要做什么", "等你过目"]) {
      expect(screen.getByRole("region", { name })).toBeVisible();
    }
    expect(screen.getByRole("button", { name: "我来做" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "我点头" })).toBeEnabled();
  });

  it("降级：放不了新东西的时候，画布上已有的照常能用", async () => {
    mockApi({ kindsStatus: 500 });
    render(<SpaceScreen spaceId={SPACE_ID} />);

    expect(await screen.findByText("现在放不了新东西。上面这些照常能用。")).toBeVisible();
    expect(screen.getByText("周四晚上拍夜景")).toBeVisible();
    // 点头不靠那张清单，所以它还在。
    expect(screen.getByRole("button", { name: "我点头" })).toBeEnabled();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("错误：一次写入没发出去时，这条还是原样", async () => {
    mockApi({ writeStatus: 500 });
    await opened();

    await userEvent.click(card("周四晚上拍夜景").getByRole("button", { name: "我来做" }));

    expect(await card("周四晚上拍夜景").findByRole("alert")).toHaveTextContent(
      "这一下没发出去",
    );
  });
});

describe("语言", () => {
  it("整屏不出现领域词汇", async () => {
    mockApi();
    const { container } = render(<SpaceScreen spaceId={SPACE_ID} />);

    await screen.findByRole("button", { name: "我来做" });
    expectNoDomainWords(container.textContent ?? "");
  });

  it("展开「放一条东西」之后也不出现", async () => {
    mockApi();
    await opened();

    await userEvent.click(screen.getByRole("button", { name: "放一条东西" }));
    await userEvent.click(screen.getByRole("radio", { name: "我们做的东西" }));

    expectNoDomainWords(document.body.textContent ?? "");
  });

  it("状态和可见范围的英文标识符不会原样露出来", async () => {
    mockApi();
    await opened();

    for (const raw of [
      "todo",
      "doing",
      "done",
      "open",
      "settled",
      "shared",
      "ours",
      "outside",
      "task",
      "material",
      "decision_gate",
      "drafted_by_agent",
    ]) {
      expect(document.body.textContent ?? "").not.toContain(raw);
    }
  });
});

function expectNoDomainWords(text: string) {
  for (const term of [
    "共域",
    "切面",
    "意图",
    "主体",
    "提案",
    "求解",
    "约束",
    "漏斗",
    "召回",
    "智能体",
    "代理",
    "素材",
    "回声",
    "成局",
    "撮合",
    "信封",
    "凭证",
    "稳定性",
    "共同事件",
    "行动类别",
    "组织者",
  ]) {
    expect(text).not.toContain(term);
  }
}

describe("这件事现在到哪了", () => {
  it("顶上一眼看得见：长到哪一步、有谁、还剩什么", async () => {
    // PRD 要求房间顶部**持续展示**目标、成员、已确认、未确认、进度、下一步。
    // 散在下面几栏里等于没有——一个刚点进来的人要在一眼之内知道
    // "这件事现在到哪了、下一步是什么"。
    mockApi();
    render(<SpaceScreen spaceId={SPACE_ID} />);

    const board = await screen.findByRole("region", { name: "这件事现在到哪了" });
    expect(within(board).getByText("长出幼苗")).toBeVisible();
    expect(within(board).getByText(/有人开始认领/)).toBeVisible();
    expect(within(board).getByText(/林知遥、陈牧/)).toBeVisible();
  });

  it("阶段说得出凭什么，不是一个百分比", async () => {
    // 说不出判据的进度条会被当成系统在评价你。
    // 而且这一屏**不出现百分比**——定了时间没定地点，和定了地点没定时间，
    // 谁更"完成"？
    mockApi();
    render(<SpaceScreen spaceId={SPACE_ID} />);

    const board = await screen.findByRole("region", { name: "这件事现在到哪了" });
    expect(board.textContent).not.toMatch(/%|％/);
  });
});

describe("这次怎么办", () => {
  it("还没人写过时，说清它是干什么的，并给一个入口", async () => {
    mockApi();
    render(<SpaceScreen spaceId={SPACE_ID} />);

    const card = await screen.findByRole("region", { name: "这次怎么办" });
    expect(within(card).getByRole("button", { name: "写一张" })).toBeVisible();
  });

  it("要素没齐就确认不了，而且说得出缺哪一样", async () => {
    // 一张没写什么时候、在哪的卡不是计划，是一个愿望。
    // 让人对着愿望点头，等于让"确认"这个动作贬值。
    mockApi({ plan: { ...PLAN, missing: ["在哪集合"] } });
    render(<SpaceScreen spaceId={SPACE_ID} />);

    const card = await screen.findByRole("region", { name: "这次怎么办" });
    expect(within(card).getByText(/还差在哪集合没写/)).toBeVisible();
    expect(within(card).getByRole("button", { name: "就这么办" })).toBeDisabled();
  });

  it("还差谁确认，指名道姓", async () => {
    // 「还差 2 个人」催不动任何人。
    mockApi({ plan: PLAN });
    render(<SpaceScreen spaceId={SPACE_ID} />);

    const card = await screen.findByRole("region", { name: "这次怎么办" });
    // **"还差谁"里不该有我自己**——我该看到的是一个可以点的按钮，
    // 不是一句催我自己的话。
    expect(within(card).getByText(/还差陈牧确认/)).toBeVisible();
    expect(within(card).queryByText(/林知遥/)).toBeNull();
  });

  it("改之前就说清楚：改了要请大家重新确认", async () => {
    // 事后才说，他会以为自己只是改了个错别字。
    mockApi({ plan: { ...PLAN, nodded: [CHEN], waiting_on: [ME] } });
    render(<SpaceScreen spaceId={SPACE_ID} />);

    const card = await screen.findByRole("region", { name: "这次怎么办" });
    await userEvent.click(within(card).getByRole("button", { name: "改一改" }));

    expect(
      await screen.findByText(/已经有 1 个人确认过了。改完要请他们再确认一次/),
    ).toBeVisible();
  });
});

describe("到那天了", () => {
  it("还没到那天，这一块不占地方", async () => {
    // 一个常驻的"我出发了"按钮在事情还没定下来的时候只是噪音，
    // 而噪音会让人学会忽略这一整块。
    mockApi();
    render(<SpaceScreen spaceId={SPACE_ID} />);

    await screen.findByRole("region", { name: "这件事现在到哪了" });
    expect(screen.queryByRole("region", { name: "到那天了" })).toBeNull();
  });

  it("到了那天，说清在哪集合、带什么，并给几个轻量状态", async () => {
    // PRD：首版不需要持续定位，只要地址入口和必要状态。
    mockApi({ dayOf: TODAY });
    render(<SpaceScreen spaceId={SPACE_ID} />);

    const card = await screen.findByRole("region", { name: "到那天了" });
    expect(within(card).getByText(/在北门地铁口集合/)).toBeVisible();
    for (const label of ["准备好了", "出发了", "到了"]) {
      expect(within(card).getByRole("button", { name: label })).toBeVisible();
    }
  });

  it("「临时有变」要能说一句怎么了", async () => {
    // 一个不说原因的「临时有变」只会让所有人干着急。
    mockApi({ dayOf: TODAY });
    render(<SpaceScreen spaceId={SPACE_ID} />);

    const card = await screen.findByRole("region", { name: "到那天了" });
    await userEvent.click(within(card).getByRole("button", { name: "临时有变" }));

    expect(within(card).getByLabelText("怎么了？")).toBeVisible();
    expect(within(card).getByRole("button", { name: "告诉大家" })).toBeDisabled();
  });

  it("我说做完了之后，说清还差谁——并且点错了能收回", async () => {
    // 一个人说做完了就标记完成，等于让他替所有人宣布。
    // 不给收回的路，人就不敢点，而不敢点会让这一步整个失效。
    mockApi({ dayOf: TODAY });
    render(<SpaceScreen spaceId={SPACE_ID} />);

    const card = await screen.findByRole("region", { name: "到那天了" });
    await userEvent.click(within(card).getByRole("button", { name: "我这边做完了" }));

    expect(await within(card).findByText(/还差陈牧/)).toBeVisible();
    expect(within(card).getByRole("button", { name: "点错了" })).toBeVisible();
  });
});

describe("要选一个", () => {
  it("票数看得见，而且指名道姓", async () => {
    // 藏着计票会让人觉得系统在操纵；而这是一个五六个人的组，
    // 藏起来他们也猜得到，猜出来的版本往往更伤人。
    mockApi({
      polls: [
        {
          item_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          question: "周六去东湖还是磨山？",
          tally: [
            { label: "东湖", votes: 2, by: ["林知遥", "陈牧"] },
            { label: "磨山", votes: 0, by: [] },
          ],
          my_choice: 0,
          waiting_on: [],
          leading: "东湖",
          settled: false,
        },
      ],
    });
    render(<SpaceScreen spaceId={SPACE_ID} />);

    const poll = await screen.findByRole("region", { name: "周六去东湖还是磨山？" });
    expect(within(poll).getByText("2 票")).toBeVisible();
    expect(within(poll).getByText("林知遥、陈牧")).toBeVisible();
  });

  it("票最多也不算定下来", async () => {
    // 一次投票是表达，不是承诺（不变量 11）。
    mockApi({
      polls: [
        {
          item_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          question: "去哪？",
          tally: [{ label: "东湖", votes: 2, by: [] }, { label: "磨山", votes: 1, by: [] }],
          my_choice: 0,
          waiting_on: [],
          leading: "东湖",
          settled: false,
        },
      ],
    });
    render(<SpaceScreen spaceId={SPACE_ID} />);

    const poll = await screen.findByRole("region", { name: "去哪？" });
    expect(within(poll).getByText(/还要有人点头才算定下来/)).toBeVisible();
  });

  it("平票就说平票，不替人破局", async () => {
    mockApi({
      polls: [
        {
          item_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          question: "去哪？",
          tally: [{ label: "东湖", votes: 1, by: [] }, { label: "磨山", votes: 1, by: [] }],
          my_choice: 0,
          waiting_on: [],
          leading: null,
          settled: false,
        },
      ],
    });
    render(<SpaceScreen spaceId={SPACE_ID} />);

    const poll = await screen.findByRole("region", { name: "去哪？" });
    expect(within(poll).getByText(/票数打平——你们自己定一个吧/)).toBeVisible();
  });

  it("定了的那一条不再占地方", async () => {
    mockApi({
      polls: [
        {
          item_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          question: "去哪？",
          tally: [],
          my_choice: null,
          waiting_on: [],
          leading: null,
          settled: true,
        },
      ],
    });
    render(<SpaceScreen spaceId={SPACE_ID} />);

    await screen.findByRole("region", { name: "这件事现在到哪了" });
    expect(screen.queryByRole("region", { name: "去哪？" })).toBeNull();
  });
});
