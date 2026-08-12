/**
 * 要选一个——投票卡的判据测试。
 *
 * 断言的是「判据真的成立」而不是「组件能渲染」。
 * 每条判据对应的测试：
 *   1. 票数实时可见、不做匿名投票 → 「票数和投票人的名字一眼可见」
 *   2. 每人一票，可改 → 「改了主意投另一个，计数跟着更新」
 *   3. 结果不自动生效，仍然要有人点头 → 「票最多的那个领先，但屏上说的是还要有人点头」
 *   4. 平票就说平票，不替人破局 → 「平票时说你们自己定一个，不把任何一个标为领先」
 *
 * 桩只打在 `fetch` 上（那是外部边界，这是本仓库既有的前端测试约定）。
 * 不给自己的模块写 mock/stub。
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Polls } from "@/components/poll-card";

const SPACE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const ITEM_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
// 固定身份，和 space-screen.test.tsx 保持一致
const ME = "33333333-3333-4333-8333-333333333333";

/** 所有人都投过、东湖领先的基础状态。 */
const POLL = {
  item_id: ITEM_ID,
  question: "周六去东湖还是磨山？",
  tally: [
    { label: "东湖", votes: 2, by: ["林知遥", "陈牧"] },
    { label: "磨山", votes: 0, by: [] },
  ],
  my_choice: 0,      // 我已投第 0 个（东湖）
  waiting_on: [],    // 所有人都投过了
  leading: "东湖",
  settled: false,
};

type Call = { url: string; body: unknown };

/**
 * 按 URL 返回约定数据的 fetch 桩。
 *
 * 只覆盖投票相关的两个端点；其余返回 404——
 * 如果有一条意外的请求发出来，测试会因找不到东西而失败，
 * 而不是静悄悄地通过。
 */
function stubFetch(polls: unknown[], voteReply?: unknown): Call[] {
  const calls: Call[] = [];
  const reply = (body: unknown, status = 200) => ({
    ok: status < 300,
    status,
    json: async () => body,
  });

  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      calls.push({ url, body });

      if (url.endsWith("/polls")) {
        return reply(polls);
      }
      if (url.includes(":vote")) {
        return reply(voteReply ?? polls[0] ?? null);
      }
      return reply(null, 404);
    }),
  );

  return calls;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.localStorage.setItem("cofield.principal", ME);
});

describe("票数实时可见，不做匿名投票", () => {
  it("票数和投票人的名字一眼可见，没人选的如实说「还没人选」", async () => {
    // 藏着计票会让人觉得系统在操纵；这是一个五六个人的组，藏起来他们也猜得到。
    // 猜出来的版本往往更伤人——所以直接说，包括说是谁选的（不做匿名投票）。
    stubFetch([POLL]);
    render(<Polls spaceId={SPACE_ID} />);

    const poll = await screen.findByRole("region", { name: "周六去东湖还是磨山？" });
    // 有人投过的那个：票数和投票人名字都在
    expect(within(poll).getByText("2 票")).toBeVisible();
    expect(within(poll).getByText("林知遥、陈牧")).toBeVisible();
    // 还没人投的那个：说「还没人选」而不是「0 票」
    // ——数字 0 比一句话更容易让人跳过，但投票意味着每个人都该表态
    expect(within(poll).getByText("还没人选")).toBeVisible();
  });

  it("还差谁没选，指名道姓", async () => {
    // 「还差 1 个人」催不动任何人；名字才能让人知道该去找谁。
    const waitingPoll = {
      ...POLL,
      tally: [
        { label: "东湖", votes: 1, by: ["林知遥"] },
        { label: "磨山", votes: 0, by: [] },
      ],
      my_choice: 0,
      waiting_on: ["陈牧"],  // 还差陈牧没投
      leading: "东湖",
    };
    stubFetch([waitingPoll]);
    render(<Polls spaceId={SPACE_ID} />);

    const poll = await screen.findByRole("region", { name: "周六去东湖还是磨山？" });
    // 说的是「还差陈牧没选」，不是「还差 1 个人」
    expect(within(poll).getByText("还差陈牧没选。")).toBeVisible();
  });
});

describe("每人一票，可改", () => {
  it("改了主意投另一个，计数跟着更新，原来那票的数字降下来", async () => {
    // 每人只有一票：改投不是再加一票，是把那票移走。
    // 前端必须用后端返回的新 tally 整体替换，不能只在本地加减——
    // 本地加减在多人同时改票时会算错。
    const afterRevote = {
      ...POLL,
      tally: [
        { label: "东湖", votes: 1, by: ["陈牧"] },    // 林知遥改投后只剩陈牧
        { label: "磨山", votes: 1, by: ["林知遥"] },  // 林知遥改投了这个
      ],
      my_choice: 1,   // 我改投了磨山（第 1 个选项）
      waiting_on: [],
      leading: null,  // 改完之后平票
    };
    stubFetch([POLL], afterRevote);
    render(<Polls spaceId={SPACE_ID} />);

    const poll = await screen.findByRole("region", { name: "周六去东湖还是磨山？" });
    // 初始：东湖 2 票，磨山 0 票
    expect(within(poll).getByText("2 票")).toBeVisible();

    // 我点磨山改票
    await userEvent.click(within(poll).getByRole("button", { name: /磨山/ }));

    // 改完之后：两个都是 1 票，不是 2+1=3 票
    await waitFor(() => expect(within(poll).getAllByText("1 票")).toHaveLength(2));
    // 名字也跟着后端返回的新数据更新了
    expect(within(poll).getByText("陈牧")).toBeVisible();
    expect(within(poll).getByText("林知遥")).toBeVisible();
  });

  it("投票发的是选项序号（从 0 起），不是文字标签", async () => {
    // 接口约定：choice 是第几个，不是标签字符串。
    // 传序号才能和后端的数组下标对齐；传文字的话，选项顺序一变投票就乱了。
    const calls = stubFetch([POLL], POLL);
    render(<Polls spaceId={SPACE_ID} />);

    const poll = await screen.findByRole("region", { name: "周六去东湖还是磨山？" });
    // 点第 1 个选项（磨山，从 0 起所以是 1）
    await userEvent.click(within(poll).getByRole("button", { name: /磨山/ }));

    await waitFor(() =>
      expect(calls.filter((c) => c.url.includes(":vote"))).toHaveLength(1),
    );
    const voteCall = calls.find((c) => c.url.includes(":vote"))!;
    // 必须是序号 1，不是字符串"磨山"
    expect(voteCall.body).toEqual({ choice: 1 });
  });
});

describe("结果不自动生效，仍然要有人点头（不变量 11）", () => {
  it("票最多的那个领先，但屏上说的是「还要有人点头才算定下来」", async () => {
    // 不变量 11：AI 可以代为表达，不能代为承诺。
    // 票多是表达，不是承诺——定下来仍然要真人点头。
    // 若这里显示成「结果是东湖」等于绕过了这道门，把"表达"变成了"承诺"。
    stubFetch([POLL]);
    render(<Polls spaceId={SPACE_ID} />);

    const poll = await screen.findByRole("region", { name: "周六去东湖还是磨山？" });
    // 说的是「领先但未定」，不是「已选定」
    expect(within(poll).getByText(/还要有人点头才算定下来/)).toBeVisible();
    // 任何暗示已经定了的词都不该出现
    expect(within(poll).queryByText(/已确认|已选定|结果是/)).toBeNull();
  });

  it("定了的票不占地方，未定的照常显示", async () => {
    // 「已定」的票再占一行只是杂音——人们的注意力该给还没定的那几个。
    const settledPoll = {
      ...POLL,
      question: "那个已经定了的问题",
      settled: true,
    };
    const openPoll = {
      ...POLL,
      item_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      question: "还没定的那道题",
    };
    stubFetch([settledPoll, openPoll]);
    render(<Polls spaceId={SPACE_ID} />);

    // 等未定的那个出现，再验已定的确实没有
    await screen.findByRole("region", { name: "还没定的那道题" });
    expect(screen.queryByRole("region", { name: "那个已经定了的问题" })).toBeNull();
  });
});

describe("平票就说平票，不替人破局", () => {
  it("平票时说「你们自己定一个」，不把任何选项标为领先", async () => {
    // 替人破局等于替人做决定；这一步的全部意义正是把决定交回给人。
    // 后端已经用 leading: null 表达了「这是平票」，前端不该自己再选一个出来。
    const tiePoll = {
      ...POLL,
      tally: [
        { label: "东湖", votes: 1, by: ["林知遥"] },
        { label: "磨山", votes: 1, by: ["陈牧"] },
      ],
      my_choice: 0,
      waiting_on: [],
      leading: null,   // 平票，后端不给 leading
    };
    stubFetch([tiePoll]);
    render(<Polls spaceId={SPACE_ID} />);

    const poll = await screen.findByRole("region", { name: "周六去东湖还是磨山？" });
    // 明确说平票，让人自己决定
    expect(within(poll).getByText(/票数打平——你们自己定一个吧/)).toBeVisible();
    // 没有任何选项被显示成领先的
    expect(within(poll).queryByText(/还要有人点头才算定下来/)).toBeNull();
  });
});
