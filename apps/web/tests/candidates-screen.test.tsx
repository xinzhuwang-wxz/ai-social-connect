/**
 * 「谁说了愿意」这一屏的产品行为。
 *
 * 这一屏是投递制的收口（ADR 0010）：发起人面对的每一个人都已经说过愿意。
 * 所以这里断言的不是"列表能渲染"，是几件**做错了产品就不成立**的事：
 *
 * - 屏上没有分数、没有百分比、没有名次——有了，这一屏就退回成推荐列表
 * - 还没答的人只给数量不给名字——指名等于把"还没答"变成一条公开记录
 * - 选中之后那个人不再给按钮——不然"我到底选了谁"要靠猜
 * - 收满时给得出一条通往那件事的路——不给，这一屏就成了终点
 * - 一个人都没答时说得出"投出去了几份"——白屏会被当成"没人要我"
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { CandidatesScreen } from "@/components/candidates-screen";
import type { components } from "@/lib/api-types";

/** 契约由 OpenAPI 生成，用例**不另写一份**——两份迟早对不上。 */
type Screen = components["schemas"]["CandidatesOut"];
type Card = components["schemas"]["CandidateOut"];

const INTENT_ID = "11111111-1111-4111-8111-111111111111";
const SU_WAN = "22222222-2222-4222-8222-222222222222";
const CHEN_MU = "33333333-3333-4333-8333-333333333333";
const SPACE_ID = "44444444-4444-4444-8444-444444444444";

const SU_WAN_CARD: Card = {
  principal_id: SU_WAN,
  display_name: "苏晚",
  why: ["她周三晚上有空，你说的就是周三", "她剪过两支短片"],
  note: "我有台稳定器，可以带上",
  chosen: false,
};

const CHEN_MU_CARD: Card = {
  principal_id: CHEN_MU,
  display_name: "陈牧",
  why: ["他也在东校区"],
  note: null,
  chosen: false,
};

const SCREEN: Screen = {
  still_need: 2,
  chosen: [],
  willing: [SU_WAN_CARD, CHEN_MU_CARD],
  still_thinking: 3,
};

type Call = { url: string; method: string; principal: string | undefined };

type Options = {
  screen?: Screen;
  /** 挑人之后服务端回的那一版。不给就按"苏晚被选中"推。 */
  afterChoose?: Screen;
  status?: number;
  chooseStatus?: number;
  hang?: boolean;
};

function mockApi(opts: Options = {}): Call[] {
  const calls: Call[] = [];
  const reply = (body: unknown, status = 200) => ({
    ok: status < 300,
    status,
    json: async () => body,
  });
  const first = opts.screen ?? SCREEN;

  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (opts.hang) return new Promise(() => {});
      const method = init?.method ?? "GET";
      const headers = (init?.headers ?? {}) as Record<string, string>;
      calls.push({ url, method, principal: headers["X-Principal-Id"] });

      if (url.includes(":choose")) {
        if (opts.chooseStatus) return reply({ detail: "没连上" }, opts.chooseStatus);
        return reply(
          opts.afterChoose ?? {
            ...first,
            still_need: first.still_need - 1,
            chosen: [{ ...SU_WAN_CARD, chosen: true }],
            willing: first.willing.filter((c) => c.principal_id !== SU_WAN),
          },
        );
      }
      if (url.endsWith("/candidates")) {
        return opts.status ? reply({ detail: "没连上" }, opts.status) : reply(first);
      }
      return reply(null, 404);
    }),
  );
  return calls;
}

beforeEach(() => vi.unstubAllGlobals());

it("还在调的时候先给骨架，不是空白", async () => {
  mockApi({ hang: true });
  render(<CandidatesScreen intentId={INTENT_ID} />);

  expect(screen.getByLabelText("加载中")).toBeTruthy();
});

it("一个人都还没答的时候，说得出投出去了几份", async () => {
  // 白屏会被读成"没人要我"。而事实是它已经到了三个人手里，只是还没人答。
  mockApi({ screen: { still_need: 1, chosen: [], willing: [], still_thinking: 3 } });
  render(<CandidatesScreen intentId={INTENT_ID} />);

  const empty = await screen.findByRole("region", { name: "还没有人答" });
  expect(empty.textContent).toContain("投出去了 3 份");
  expect(empty.textContent).toContain("还没人答");
});

it("连不上的时候说得出话，还能再试一次", async () => {
  mockApi({ status: 500 });
  render(<CandidatesScreen intentId={INTENT_ID} />);

  expect((await screen.findByRole("alert")).textContent).toContain("调不出");
  expect(screen.getByRole("button", { name: "再试一次" })).toBeTruthy();
});

it("每个人的理由逐条列出来，还差几个人说得出", async () => {
  mockApi();
  render(<CandidatesScreen intentId={INTENT_ID} />);

  const card = await screen.findByRole("article", { name: "苏晚" });
  expect(within(card).getByText("她剪过两支短片")).toBeTruthy();
  expect(within(card).getByText("她周三晚上有空，你说的就是周三")).toBeTruthy();
  expect(document.body.textContent).toContain("还差 2 个人");
});

it("屏上没有分数、没有百分比、也没有名次", async () => {
  // 有了任何一个，这一屏就退回成推荐列表：用户既无从判断也无从反驳。
  mockApi();
  render(<CandidatesScreen intentId={INTENT_ID} />);

  await screen.findByRole("article", { name: "苏晚" });
  const text = document.body.textContent ?? "";
  expect(text).not.toMatch(/%|％/);
  expect(text).not.toMatch(/匹配度|契合度|分数|得分|评分|排名|第\s*\d+\s*名/);
});

it("还没答的人只给数量，不给名字", async () => {
  mockApi({
    screen: {
      still_need: 2,
      chosen: [],
      willing: [SU_WAN_CARD],
      still_thinking: 3,
    },
  });
  render(<CandidatesScreen intentId={INTENT_ID} />);

  const pending = await screen.findByRole("region", { name: "还没答的" });
  expect(pending.textContent).toContain("3 个人");
  // 名单从来没到过前端，但这条断言守的是**将来也不许显示**。
  expect(pending.textContent).not.toContain("陈牧");
});

it("候选自己写的那句话显示出来", async () => {
  // 系统的理由是关于他的，这一句是他本人说的。丢掉它，等于把人删成一份摘要。
  mockApi();
  render(<CandidatesScreen intentId={INTENT_ID} />);

  const card = await screen.findByRole("article", { name: "苏晚" });
  expect(card.textContent).toContain("我有台稳定器，可以带上");
});

it("按钮是人点的动作词，不是「AI 推荐」", async () => {
  // AI 排序、AI 解释，但那一下必须是人点的（不变量 11）。
  mockApi();
  render(<CandidatesScreen intentId={INTENT_ID} />);

  const card = await screen.findByRole("article", { name: "苏晚" });
  expect(within(card).getByRole("button", { name: "选 TA" })).toBeTruthy();
  expect(document.body.textContent).not.toMatch(/推荐|AI 帮你选|自动/);
});

it("选中之后那个人不再给按钮，并且进「已经选好的」那一栏", async () => {
  const calls = mockApi();
  render(<CandidatesScreen intentId={INTENT_ID} />);

  const card = await screen.findByRole("article", { name: "苏晚" });
  await userEvent.click(within(card).getByRole("button", { name: "选 TA" }));

  await waitFor(() =>
    expect(screen.getByRole("region", { name: "已经选好的" })).toBeTruthy(),
  );
  const picked = within(screen.getByRole("region", { name: "已经选好的" })).getByRole(
    "article",
    { name: "苏晚" },
  );
  expect(within(picked).queryByRole("button", { name: "选 TA" })).toBeNull();
  // 还没被选的人照常可点——挑人是一个个来的。
  const still = within(screen.getByRole("region", { name: "说了愿意的" })).getByRole(
    "article",
    { name: "陈牧" },
  );
  expect(within(still).getByRole("button", { name: "选 TA" })).toBeTruthy();

  const posted = calls.filter((c) => c.method === "POST");
  expect(posted).toHaveLength(1);
  expect(posted[0]!.url).toContain(`/api/intents/${INTENT_ID}/candidates/${SU_WAN}:choose`);
  // 服务端只按这个头认人。掉了它就等于换了一个人在挑。
  expect(posted[0]!.principal).toBeTruthy();
});

it("收满的时候说「人齐了」，并给一条通往那件事的路", async () => {
  mockApi({
    screen: { still_need: 1, chosen: [], willing: [SU_WAN_CARD], still_thinking: 0 },
    afterChoose: {
      still_need: 0,
      chosen: [{ ...SU_WAN_CARD, chosen: true }],
      willing: [],
      still_thinking: 0,
      formed_event_id: "55555555-5555-4555-8555-555555555555",
      space_id: SPACE_ID,
    },
  });
  render(<CandidatesScreen intentId={INTENT_ID} />);

  const card = await screen.findByRole("article", { name: "苏晚" });
  await userEvent.click(within(card).getByRole("button", { name: "选 TA" }));

  const done = await screen.findByRole("region", { name: "人齐了" });
  expect(done.textContent).toContain("人齐了");
  // 刚挑完的人最想去的是做事的地方，不是回头再看一遍名单。
  const go = within(done).getByRole("link", { name: "去这件事的地方" });
  expect(go.getAttribute("href")).toBe(`/spaces/${SPACE_ID}`);
});

it("还差最后一个人时，先说清楚这一下会把事情定下来", async () => {
  // 事后才说，他会以为自己只是又选了一个人，而其余的人已经被关掉了。
  mockApi({
    screen: { still_need: 1, chosen: [], willing: [SU_WAN_CARD], still_thinking: 2 },
  });
  render(<CandidatesScreen intentId={INTENT_ID} />);

  await screen.findByRole("article", { name: "苏晚" });
  expect(document.body.textContent).toContain("再选一个人就齐了");
});

it("选人这一下失败时不吞掉，也不假装已经选上了", async () => {
  mockApi({ chooseStatus: 500 });
  render(<CandidatesScreen intentId={INTENT_ID} />);

  const card = await screen.findByRole("article", { name: "苏晚" });
  await userEvent.click(within(card).getByRole("button", { name: "选 TA" }));

  expect((await screen.findByRole("alert")).textContent).toContain("没有人被选中");
  expect(screen.queryByRole("region", { name: "已经选好的" })).toBeNull();
  expect(
    within(screen.getByRole("article", { name: "苏晚" })).getByRole("button", {
      name: "选 TA",
    }),
  ).toBeTruthy();
});

it("界面上不出现领域词汇", async () => {
  // docs/07：严谨性要能被感受到，不能被阅读到。
  mockApi();
  render(<CandidatesScreen intentId={INTENT_ID} />);

  await screen.findByRole("article", { name: "苏晚" });
  expect(document.body.textContent ?? "").not.toMatch(
    /意图|提案|撮合|召回|主体|切面|凭证|信封|成局|稳定性|候选人|授权/,
  );
});
