/**
 * 项目空间里那段群聊的产品行为。
 *
 * 断言的是用户看到什么、能做什么，不是组件内部长什么样。这一段有两条不能靠
 * 人工点一遍：**助手关掉之后大家照常说话**（产品的一条承诺），和**这里定不了
 * 任何事**（说反了，「相关的人一个不少地点过头才算定下来」当场作废）。
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SpaceChat } from "@/components/space-chat";

const SPACE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const ME = "33333333-3333-4333-8333-333333333333";
const SU = "44444444-4444-4444-8444-444444444444";
/** 助手在这个空间里的编号。它是不是助手看 `is_agent`，不靠认这串号。 */
const AGENT = "00000000-0000-4000-8000-000000000000";

const CREDIT_ID = "33333333-3333-4333-8333-aaaaaaaaaaaa";
const PLACE_ID = "44444444-4444-4444-8444-aaaaaaaaaaaa";

/**
 * 时刻按日历天摆，不按「几小时前」。
 *
 * 「几小时前」在半夜跑测试时会掉到前一天去，而这一段要断言的正是「今天／昨天」
 * 这两个落点。一条随运行时刻而变的断言，迟早会被当成偶发失败跳过。
 */
const DAY_START = new Date(new Date().setHours(0, 0, 0, 0)).getTime();
const todayAt = (hour: number) =>
  new Date(DAY_START + hour * 3_600_000).toISOString();
const yesterdayAt = (hour: number) =>
  new Date(DAY_START - 86_400_000 + hour * 3_600_000).toISOString();

type Message = {
  id: string;
  author_id: string;
  is_agent: boolean;
  kind: string;
  text: string;
  created_at: string;
  replies_to?: string | null;
  about_item_id?: string | null;
};

const said = (
  rest: Partial<Message> & Pick<Message, "id" | "text" | "created_at">,
): Message => ({
  author_id: ME,
  is_agent: false,
  kind: "said",
  ...rest,
});

const HELLO = said({
  id: "11111111-1111-4111-8111-111111111111",
  author_id: SU,
  text: "我是苏晚，之前拍过两支短片",
  created_at: yesterdayAt(20),
});

const MINE = said({
  id: "22222222-2222-4222-8222-222222222222",
  text: "我周三晚上都有空",
  created_at: yesterdayAt(20.5),
});

/** 助手在主线上说的一句话。它和人说的话必须一眼分得开。 */
const AGENT_SAID = said({
  id: "66666666-6666-4666-8666-666666666666",
  author_id: AGENT,
  is_agent: true,
  text: "还有两件事没定，我先把其中一件写成一句话",
  created_at: yesterdayAt(21),
});

/** 有人接了的那张话题卡。 */
const ANSWERED_TOPIC = said({
  id: "77777777-7777-4777-8777-777777777777",
  author_id: AGENT,
  is_agent: true,
  kind: "topic",
  text: "作品署名按谁出力多算，还是三个人并列？",
  created_at: yesterdayAt(21.5),
  about_item_id: CREDIT_ID,
});

const REPLY_ONE = said({
  id: "88888888-8888-4888-8888-888888888888",
  author_id: SU,
  text: "我倾向并列，谁也别算谁多",
  created_at: yesterdayAt(22),
  replies_to: ANSWERED_TOPIC.id,
});

const REPLY_TWO = said({
  id: "99999999-9999-4999-8999-999999999999",
  text: "我也是",
  created_at: yesterdayAt(22.5),
  replies_to: ANSWERED_TOPIC.id,
});

/** 没人回的那张。它不藏起来，但也不该被顶到最上面去。 */
const IGNORED_TOPIC = said({
  id: "aaaaaaaa-1111-4111-8111-111111111111",
  author_id: AGENT,
  is_agent: true,
  kind: "topic",
  text: "在哪剪片子，定在谁的宿舍还是社团活动室？",
  created_at: yesterdayAt(23),
  about_item_id: PLACE_ID,
});

/** 那张没人回的卡之后还有人说话——它没被顶上去，就该看得出来。 */
const LATER = said({
  id: "bbbbbbbb-1111-4111-8111-111111111111",
  author_id: SU,
  text: "灯我去社团借，明天给准信",
  created_at: todayAt(9),
});

const CHAT = {
  messages: [HELLO, MINE, AGENT_SAID, ANSWERED_TOPIC, REPLY_ONE, REPLY_TWO, IGNORED_TOPIC, LATER],
  threads: [
    { topic: ANSWERED_TOPIC, replies: [REPLY_ONE, REPLY_TWO], answered: true },
    { topic: IGNORED_TOPIC, replies: [], answered: false },
  ],
};

const EMPTY = { messages: [], threads: [] };

/** 画布那一边：话题卡关于哪件事，名字得去那边问。 */
const item = (id: string, title: string) => ({
  id,
  space_id: SPACE_ID,
  kind: "decision_gate",
  label: "要定的事",
  title,
  state: "open",
  created_by: ME,
  created_at: yesterdayAt(8),
  updated_at: yesterdayAt(8),
  drafted_by_agent: false,
  awaiting_a_person: false,
  deciders: [ME, SU],
  confirmed_by: [],
});

const CREDIT = item(CREDIT_ID, "作品署名怎么算");
const PLACE = item(PLACE_ID, "在哪剪片子");

const SPACE = {
  id: SPACE_ID,
  title: "流浪猫短片",
  agent_enabled: true,
  cards: [CREDIT, PLACE],
  open_gates: [CREDIT, PLACE],
  stuck: [],
  drafts: [],
  progress: { done: 0, total: 0 },
  summary: "2 件事等着定",
};

/** 署名那件事后来定下来了：卡还在，但它上面该改口。 */
const SPACE_SETTLED = {
  ...SPACE,
  cards: [{ ...CREDIT, state: "settled" }, PLACE],
  open_gates: [PLACE],
};

type Call = { url: string; method: string; body: unknown };

type Options = {
  chat?: typeof CHAT;
  space?: typeof SPACE;
  topics?: Message[];
  chatStatus?: number;
  spaceStatus?: number;
  sayStatus?: number;
  topicsStatus?: number;
  hang?: boolean;
};

function mockApi(opts: Options = {}): Call[] {
  const calls: Call[] = [];
  const reply = (body: unknown, status = 200) => ({
    ok: status < 300,
    status,
    json: async () => body,
  });

  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (opts.hang) return new Promise(() => {});
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      calls.push({ url, method, body });

      if (url.endsWith("chat:topics")) {
        if (opts.topicsStatus) return reply({ detail: "没连上" }, opts.topicsStatus);
        // 助手关着、或者它一时说不出话：空数组加 200，不是一次故障。
        return reply(opts.topics ?? []);
      }
      if (url.endsWith("/chat")) {
        if (method === "POST") {
          return opts.sayStatus
            ? reply({ detail: "没连上" }, opts.sayStatus)
            : reply(MINE, 201);
        }
        return opts.chatStatus
          ? reply({ detail: "没连上" }, opts.chatStatus)
          : reply(opts.chat ?? CHAT);
      }
      if (url === `/api/spaces/${SPACE_ID}`) {
        return opts.spaceStatus
          ? reply({ detail: "没连上" }, opts.spaceStatus)
          : reply(opts.space ?? SPACE);
      }
      return reply(null, 404);
    }),
  );
  return calls;
}

const card = (title: string) => within(screen.getByRole("article", { name: title }));
const writes = (calls: Call[]) => calls.filter((c) => c.method !== "GET");

const opened = async () => {
  render(<SpaceChat spaceId={SPACE_ID} />);
  // 话题卡关于哪件事是第二次取数：等它回来，卡上才说得出名字。
  await screen.findByText("关于：作品署名怎么算");
};

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.localStorage.setItem("cofield.principal", ME);
});

describe("谁说的一眼可辨", () => {
  it("助手的话和人的话在页面上分得开", async () => {
    mockApi();
    await opened();

    const record = within(screen.getByRole("list", { name: "说过的话" }));
    const lines = record.getAllByRole("listitem");

    const agentLine = lines.find((li) => li.textContent?.includes(AGENT_SAID.text));
    const humanLine = lines.find((li) => li.textContent?.includes(HELLO.text));

    expect(within(agentLine!).getByText("助手")).toBeVisible();
    expect(within(agentLine!).queryByText("组里的人")).toBeNull();
    expect(within(humanLine!).getByText("组里的人")).toBeVisible();
    expect(within(humanLine!).queryByText("助手")).toBeNull();
  });

  it("我说的话标成我，不是「组里的人」", async () => {
    mockApi();
    await opened();

    const mine = screen
      .getAllByRole("listitem")
      .find((li) => li.textContent?.includes(MINE.text));
    expect(within(mine!).getByText("我")).toBeVisible();
  });

  it("不把任何人的编号糊到脸上", async () => {
    mockApi();
    await opened();

    expect(document.body.textContent ?? "").not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}/);
  });
});

describe("话题卡不是普通消息", () => {
  it("它自己是一张卡，写着关于哪件还没定的事", async () => {
    mockApi();
    await opened();

    const topic = card(ANSWERED_TOPIC.text);
    expect(topic.getByText("关于：作品署名怎么算")).toBeVisible();
    // 普通的一句话不是卡。
    expect(screen.queryByRole("article", { name: HELLO.text })).toBeNull();
  });

  it("回复挂在这张卡下面，不散在主线上", async () => {
    mockApi();
    await opened();

    const topic = card(ANSWERED_TOPIC.text);
    expect(topic.getByText(REPLY_ONE.text)).toBeVisible();
    expect(topic.getByText(REPLY_TWO.text)).toBeVisible();
    // 主线上不再来一遍。
    expect(screen.getAllByText(REPLY_ONE.text)).toHaveLength(1);
  });

  it("点进去在下面回复，回的是这张卡", async () => {
    const calls = mockApi();
    await opened();

    const topic = card(ANSWERED_TOPIC.text);
    await userEvent.click(topic.getByRole("button", { name: "回一句" }));
    await userEvent.type(topic.getByLabelText("回一句"), "那就并列");
    await userEvent.click(topic.getByRole("button", { name: "回在这张卡下面" }));

    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0]).toMatchObject({
      method: "POST",
      body: { text: "那就并列", replies_to: ANSWERED_TOPIC.id },
    });
  });

  it("没人回的那张不藏起来，也不被顶到最上面", async () => {
    mockApi();
    await opened();

    const ignored = card(IGNORED_TOPIC.text);
    expect(ignored.getByText(/还没人接这个话/)).toBeVisible();

    // 它待在它当时的位置上：前面有更早的话，后面有更晚的话。
    const lines = screen.getByRole("list", { name: "说过的话" }).children;
    const texts = [...lines].map((li) => li.textContent ?? "");
    const where = texts.findIndex((t) => t.includes(IGNORED_TOPIC.text));
    expect(where).toBeGreaterThan(0);
    expect(texts.slice(where + 1).join()).toContain(LATER.text);
  });
});

describe("这里定不了任何事", () => {
  it("话题卡上说清了聊完还得去点头", async () => {
    mockApi();
    await opened();

    expect(
      card(ANSWERED_TOPIC.text).getByText(
        /这件事还没定。在这儿聊出结果也不算定下来——还得相关的人各自去点头/,
      ),
    ).toBeVisible();
  });

  it("整段的开头就把这句话说在前面", async () => {
    mockApi();
    await opened();

    expect(
      within(screen.getByRole("region", { name: "说说话" })).getByText(
        /这里聊出的结果不算定下来——每件事还得相关的人各自去点头/,
      ),
    ).toBeVisible();
  });

  it("那件事真定下来之后，卡上改口，不再催人去点头", async () => {
    mockApi({ space: SPACE_SETTLED });
    render(<SpaceChat spaceId={SPACE_ID} />);

    expect(await screen.findByText("关于：作品署名怎么算")).toBeVisible();
    const topic = card(ANSWERED_TOPIC.text);
    expect(topic.getByText("这件事已经定下来了。")).toBeVisible();
    expect(topic.queryByText(/还得相关的人各自去点头/)).toBeNull();
  });
});

describe("说一句", () => {
  it("说出去的是一句话，作者不写在请求体里", async () => {
    const calls = mockApi();
    await opened();

    await userEvent.type(screen.getByLabelText("说一句"), "我明天下午能过去");
    await userEvent.click(screen.getByRole("button", { name: "说出去" }));

    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0]).toMatchObject({
      method: "POST",
      body: { text: "我明天下午能过去" },
    });
    expect(writes(calls)[0]?.body).not.toHaveProperty("author_id");
  });

  it("整条记录都在，不截断", async () => {
    mockApi();
    await opened();

    for (const text of [HELLO.text, MINE.text, AGENT_SAID.text, REPLY_ONE.text, LATER.text]) {
      expect(screen.getByText(text)).toBeVisible();
    }
    // 隔了一天的两截记录之间有个落点，翻回去找得到。
    expect(screen.getByText("今天")).toBeVisible();
    expect(screen.getByText("昨天")).toBeVisible();
  });
});

describe("五态", () => {
  it("首次：说清这是哪儿、能干什么", async () => {
    mockApi();
    await opened();

    expect(screen.getByRole("heading", { name: "说说话" })).toBeVisible();
    expect(screen.getByLabelText("说一句")).toBeVisible();
    expect(screen.getByRole("button", { name: "让助手起个话头" })).toBeEnabled();
  });

  it("加载：给骨架，不是转圈", () => {
    mockApi({ hang: true });
    render(<SpaceChat spaceId={SPACE_ID} />);

    expect(screen.getByLabelText("加载中")).toBeVisible();
  });

  it("空：一句让人愿意开口的话，加一个让助手起话头的按钮", async () => {
    mockApi({ chat: EMPTY });
    render(<SpaceChat spaceId={SPACE_ID} />);

    expect(await screen.findByText("还没人说话。")).toBeVisible();
    expect(screen.getByText(/第一句最难，之后就顺了/)).toBeVisible();
    expect(screen.getByRole("button", { name: "让助手起个话头" })).toBeEnabled();
    // 想自己先说也不用先找按钮，框就在手边。
    expect(screen.getByLabelText("说一句")).toBeVisible();
  });

  it("错误：看不到说过的话时说清哪里断了，并说明什么都没丢", async () => {
    mockApi({ chatStatus: 500 });
    render(<SpaceChat spaceId={SPACE_ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("现在看不到这里说过的话");
    expect(screen.getByRole("button", { name: "再试一次" })).toBeVisible();
  });

  it("错误：一句话没发出去时，那句话还在框里", async () => {
    mockApi({ sayStatus: 500 });
    await opened();

    const box = screen.getByLabelText("说一句");
    await userEvent.type(box, "打了半天的一段话");
    await userEvent.click(screen.getByRole("button", { name: "说出去" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("这句话没发出去，还在框里");
    expect(box).toHaveValue("打了半天的一段话");
  });

  it("降级：助手关着的时候，大家照常说话", async () => {
    const calls = mockApi({ topics: [] });
    await opened();

    await userEvent.click(screen.getByRole("button", { name: "让助手起个话头" }));

    // 空数组加 200 不是一次故障：平静地说一句，不弹红框。
    expect(await screen.findByText(/助手这会儿起不了话头/)).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();

    // 说过的话一句不少，还能接着说。
    expect(screen.getByText(HELLO.text)).toBeVisible();
    expect(screen.getByText(REPLY_ONE.text)).toBeVisible();
    await userEvent.type(screen.getByLabelText("说一句"), "那我们自己聊");
    await userEvent.click(screen.getByRole("button", { name: "说出去" }));

    await waitFor(() => {
      expect(writes(calls).some((c) => c.url.endsWith("/chat"))).toBe(true);
    });
  });

  it("降级：起话头那一下挂了也不算事故，群聊照常", async () => {
    mockApi({ topicsStatus: 503 });
    await opened();

    await userEvent.click(screen.getByRole("button", { name: "让助手起个话头" }));

    expect(await screen.findByText(/助手这会儿起不了话头/)).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByLabelText("说一句")).toBeEnabled();
    expect(screen.getByText(LATER.text)).toBeVisible();
  });

  it("降级：问不到那件事叫什么的时候，话题卡还在，话照常说", async () => {
    mockApi({ spaceStatus: 500 });
    render(<SpaceChat spaceId={SPACE_ID} />);

    const topic = within(await screen.findByRole("article", { name: ANSWERED_TOPIC.text }));
    // 名字问不到就少说一行，不把一串编号糊到脸上。
    expect(topic.queryByText(/关于：/)).toBeNull();
    expect(document.body.textContent ?? "").not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}/);
    // 「聊完还得去点头」这句不能跟着丢——它不依赖那件事叫什么。
    expect(topic.getByText(/还得相关的人各自去点头/)).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByLabelText("说一句")).toBeEnabled();
  });
});

describe("语言", () => {
  it("整段不出现领域词汇", async () => {
    mockApi();
    const { container } = render(<SpaceChat spaceId={SPACE_ID} />);

    await screen.findByText("关于：作品署名怎么算");
    expectNoDomainWords(container.textContent ?? "");
  });

  it("展开一张话题卡的回复框之后也不出现", async () => {
    mockApi();
    await opened();

    await userEvent.click(card(ANSWERED_TOPIC.text).getByRole("button", { name: "回一句" }));
    expectNoDomainWords(document.body.textContent ?? "");
  });

  it("空的时候也不出现", async () => {
    mockApi({ chat: EMPTY });
    render(<SpaceChat spaceId={SPACE_ID} />);

    await screen.findByText("还没人说话。");
    expectNoDomainWords(document.body.textContent ?? "");
  });

  it("英文标识符不会原样露出来", async () => {
    mockApi();
    await opened();

    for (const raw of [
      "said",
      "topic",
      "is_agent",
      "about_item_id",
      "replies_to",
      "decision_gate",
      "open",
      "settled",
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
    "召回",
    "约束",
    "漏斗",
    "智能体",
    "代理",
    "场域",
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
    "决策门",
  ]) {
    expect(text).not.toContain(term);
  }
}
