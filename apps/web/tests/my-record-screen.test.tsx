/**
 * 三个自我管理面的产品行为：我参加过的 / 关于我的记录 / 谁能看到我。
 *
 * 断言的是**权利真的顺手**、**该分开的确实分开**、**收回之后界面立刻变**，
 * 不是组件内部长什么样。
 *
 * 这里的 fetch 桩是**有状态的**：收回过的那条不会再被任何一次取数带出来。
 * 一个每次都返回同一份数据的桩，会让"收回即时生效"这条断言变成走过场。
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MyRecordScreen } from "@/components/my-record-screen";
import type { MyEvent, MyRecords, Visibility } from "@/lib/me";

const ME = "33333333-3333-4333-8333-333333333333";
const EVENT = "11111111-1111-4111-8111-111111111111";
const DRAFT = "22222222-2222-4222-8222-222222222222";
const KEPT = "44444444-4444-4444-8444-444444444444";
const ENVELOPE = "55555555-5555-4555-8555-555555555555";
const INTENT = "66666666-6666-4666-8666-666666666666";
const SOURCE = "77777777-7777-4777-8777-777777777777";

const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString();

const EVENTS: MyEvent[] = [
  {
    event_id: EVENT,
    title: "檐下",
    goal: "拍一支 60 秒短片",
    state: "completed",
    formed_at: inHours(-72),
    deadline: null,
    left_at: null,
    with_others: ["苏晚", "陈牧"],
    counts_as_done: true,
  },
  {
    event_id: "88888888-8888-4888-8888-888888888888",
    title: "没做成的那次",
    goal: "办一场院系展",
    state: "abandoned",
    formed_at: inHours(-200),
    deadline: null,
    left_at: null,
    with_others: [],
    counts_as_done: false,
  },
];

const KEPT_TEXT = "他做完过一支 60 秒短片，负责剪辑";
const DRAFT_TEXT = "他好像会调色";

const RECORDS: MyRecords = {
  to_confirm: [
    {
      id: DRAFT,
      text: DRAFT_TEXT,
      state: "draft",
      drafted_by_agent: true,
      created_at: inHours(-2),
      confirmed_at: null,
      revoked_at: null,
      event_id: EVENT,
      event_title: "檐下",
      sources: [
        { evidence_id: SOURCE, kind: "note", title: "分镜脚本第 3 版", added_at: inHours(-70) },
      ],
      in_use: 0,
    },
  ],
  confirmed: [
    {
      id: KEPT,
      text: KEPT_TEXT,
      state: "confirmed",
      drafted_by_agent: false,
      created_at: inHours(-70),
      confirmed_at: inHours(-69),
      revoked_at: null,
      event_id: EVENT,
      event_title: "檐下",
      sources: [
        { evidence_id: SOURCE, kind: "artifact", title: "成片 檐下.mp4", added_at: inHours(-70) },
      ],
      in_use: 1,
    },
  ],
  revoked: [],
};

const SHOWN: Visibility[] = [
  {
    envelope_id: ENVELOPE,
    intent_id: INTENT,
    for_what: "拍一支 60 秒短片",
    shows: [
      { field_name: "goal", seen_by_others: true },
      { field_name: "major", seen_by_others: false },
    ],
    shows_records: [KEPT_TEXT],
    expires_at: inHours(60),
  },
];

const NOTHING: MyRecords = { to_confirm: [], confirmed: [], revoked: [] };

type Call = { url: string; method: string };

type Options = {
  events?: MyEvent[];
  records?: MyRecords;
  shown?: Visibility[];
  eventsStatus?: number;
  recordsStatus?: number;
  shownStatus?: number;
  writeStatus?: number;
  hang?: boolean;
};

/**
 * 有状态的桩：确认与收回真的改变后续取数的结果。
 *
 * 这样"收回之后那条立刻不再被引用"才是被验证的，而不是被假设的。
 */
function mockApi(opts: Options = {}): Call[] {
  const calls: Call[] = [];
  const records: MyRecords = JSON.parse(JSON.stringify(opts.records ?? RECORDS));
  let shown: Visibility[] = JSON.parse(JSON.stringify(opts.shown ?? SHOWN));
  const reply = (body: unknown, status = 200) => ({
    ok: status < 300,
    status,
    json: async () => body,
  });

  const find = (id: string) =>
    [...records.to_confirm, ...records.confirmed, ...records.revoked].find(
      (r) => r.id === id,
    );

  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (opts.hang) return new Promise(() => {});
      calls.push({ url, method: init?.method ?? "GET" });

      if (url === "/api/me/events") {
        return opts.eventsStatus
          ? reply({ detail: "没连上" }, opts.eventsStatus)
          : reply(opts.events ?? EVENTS);
      }
      if (url === "/api/me/facets") {
        return opts.recordsStatus
          ? reply({ detail: "没连上" }, opts.recordsStatus)
          : reply(records);
      }
      if (url === "/api/me/visibility") {
        return opts.shownStatus
          ? reply({ detail: "没连上" }, opts.shownStatus)
          : reply(shown);
      }

      if (opts.writeStatus) return reply({ detail: "没连上" }, opts.writeStatus);

      const confirming = url.match(/\/api\/facets\/(.+):confirm$/);
      if (confirming) {
        const record = find(confirming[1]!)!;
        records.to_confirm = records.to_confirm.filter((r) => r.id !== record.id);
        const kept = { ...record, state: "confirmed", confirmed_at: inHours(0) };
        records.confirmed = [kept, ...records.confirmed];
        return reply(kept);
      }

      const revoking = url.match(/\/api\/facets\/(.+):revoke$/);
      if (revoking) {
        const record = find(revoking[1]!)!;
        records.to_confirm = records.to_confirm.filter((r) => r.id !== record.id);
        records.confirmed = records.confirmed.filter((r) => r.id !== record.id);
        const gone = { ...record, state: "revoked", revoked_at: inHours(0), in_use: 0 };
        records.revoked = [gone, ...records.revoked];
        // 收回过的话不再能被引用，所以它从「现在带出去的话」里消失。
        // 这就是后端 `citable()` 做的事，桩照着同一条规则走。
        shown = shown.map((row) => ({
          ...row,
          shows_records: row.shows_records.filter((t) => t !== record.text),
        }));
        return reply(gone);
      }

      const stopping = url.match(/\/api\/envelopes\/(.+):revoke$/);
      if (stopping) {
        shown = shown.filter((row) => row.envelope_id !== stopping[1]);
        return reply({ id: stopping[1], state: "revoked" });
      }

      return reply(null, 404);
    }),
  );
  return calls;
}

/** 页签要等首次取数回来才在。等它出现再点，而不是假设它已经在了。 */
const openTab = async (name: string | RegExp) =>
  userEvent.click(await screen.findByRole("tab", { name }));

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.localStorage.setItem("cofield.principal", ME);
});

describe("我参加过的", () => {
  it("每条是一次做成的事：做的什么、和谁", async () => {
    mockApi();
    render(<MyRecordScreen />);

    const card = within(await screen.findByRole("article", { name: "檐下" }));
    expect(card.getByText("拍一支 60 秒短片")).toBeVisible();
    expect(card.getByText("和苏晚、陈牧一起")).toBeVisible();
    expect(card.getByText("这件事做成了")).toBeVisible();
  });

  it("取消的事在，但不算做成的", async () => {
    mockApi();
    render(<MyRecordScreen />);

    const card = within(await screen.findByRole("article", { name: "没做成的那次" }));
    expect(card.getByText("这件事后来取消了，不算做成的")).toBeVisible();
    expect(card.queryByText("这件事做成了")).toBeNull();
  });

  it("中途退出的事留着，但不算你做成的", async () => {
    mockApi({
      events: [{ ...EVENTS[0]!, left_at: inHours(-60), counts_as_done: false }],
    });
    render(<MyRecordScreen />);

    expect(
      await screen.findByText("你中途退出了，这次不算你做成的"),
    ).toBeVisible();
  });
});

describe("关于我的记录", () => {
  it("等你点头的和已经在用的分成两堆，不混在一起", async () => {
    mockApi();
    render(<MyRecordScreen />);
    await openTab(/关于我的记录/);

    const waiting = within(screen.getByRole("region", { name: "等你点头" }));
    const inUse = within(screen.getByRole("region", { name: "已经在用的" }));
    expect(waiting.getByRole("article", { name: DRAFT_TEXT })).toBeVisible();
    expect(waiting.queryByRole("article", { name: KEPT_TEXT })).toBeNull();
    expect(inUse.getByRole("article", { name: KEPT_TEXT })).toBeVisible();
    expect(screen.getByText("没点过头的这几条，任何人都看不到。")).toBeVisible();
  });

  it("每条都说得出从哪来的，也看得出是谁写的", async () => {
    mockApi();
    render(<MyRecordScreen />);
    await openTab(/关于我的记录/);

    const guess = within(screen.getByRole("article", { name: DRAFT_TEXT }));
    expect(guess.getByText("来自「檐下」，依据：分镜脚本第 3 版")).toBeVisible();
    expect(guess.getByText("这是我猜的，你看对不对")).toBeVisible();

    const mine = within(screen.getByRole("article", { name: KEPT_TEXT }));
    expect(mine.getByText("来自「檐下」，依据：成片 檐下.mp4")).toBeVisible();
    expect(mine.queryByText("这是我猜的，你看对不对")).toBeNull();
  });

  it("说不出来源的那条如实说，并建议删掉", async () => {
    mockApi({
      records: {
        ...RECORDS,
        to_confirm: [{ ...RECORDS.to_confirm[0]!, event_title: null, sources: [] }],
      },
    });
    render(<MyRecordScreen />);
    await openTab(/关于我的记录/);

    expect(
      screen.getByText("这条说不出是从哪来的。拿不准就删掉它"),
    ).toBeVisible();
  });

  it("点过头之后它挪到「已经在用的」那一堆", async () => {
    mockApi();
    render(<MyRecordScreen />);
    await openTab(/关于我的记录/);

    await userEvent.click(screen.getByRole("button", { name: "对，是这样" }));

    await waitFor(() => {
      const inUse = within(screen.getByRole("region", { name: "已经在用的" }));
      expect(inUse.getByRole("article", { name: DRAFT_TEXT })).toBeVisible();
    });
    const waiting = within(screen.getByRole("region", { name: "等你点头" }));
    expect(waiting.queryByRole("article", { name: DRAFT_TEXT })).toBeNull();
  });

  it("收回是一步完成的，不再确认一次，也不问为什么", async () => {
    const calls = mockApi();
    render(<MyRecordScreen />);
    await openTab(/关于我的记录/);

    const card = within(screen.getByRole("article", { name: KEPT_TEXT }));
    await userEvent.click(card.getByRole("button", { name: "收回" }));

    await waitFor(() => {
      expect(screen.getByRole("region", { name: "你收回过的" })).toBeVisible();
    });
    expect(
      calls.filter((c) => c.url.endsWith(":revoke") && c.method === "POST"),
    ).toHaveLength(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: /确定|确认|再想想|为什么/ })).toBeNull();
  });

  it("收回之后，那句话立刻不再出现在「谁能看到我」里", async () => {
    mockApi();
    render(<MyRecordScreen />);
    await openTab(/关于我的记录/);

    // 收回之前，它确实正被一处用着。
    expect(screen.getByText("现在有 1 处正在用这句话")).toBeVisible();
    await userEvent.click(
      within(screen.getByRole("article", { name: KEPT_TEXT })).getByRole("button", {
        name: "收回",
      }),
    );
    await screen.findByRole("region", { name: "你收回过的" });

    await openTab("谁能看到我");
    await waitFor(() => {
      expect(screen.queryByText("还带上你这几句话：")).toBeNull();
    });
    expect(screen.queryByText(KEPT_TEXT)).toBeNull();
    // 那一次给出去的其余部分还在——收回一句话不等于收回整次。
    expect(screen.getByText("他们看得到：要做什么")).toBeVisible();
  });

  it("收回过的那条不再给「收回」按钮，也说清它不会再被用到", async () => {
    mockApi();
    render(<MyRecordScreen />);
    await openTab(/关于我的记录/);

    await userEvent.click(
      within(screen.getByRole("article", { name: KEPT_TEXT })).getByRole("button", {
        name: "收回",
      }),
    );

    const gone = within(await screen.findByRole("region", { name: "你收回过的" }));
    expect(gone.getByText("你收回了这句话，它不会再被用到。")).toBeVisible();
    expect(gone.queryByRole("button", { name: "收回" })).toBeNull();
  });

  it("有几条等你点头，页签上就说几条", async () => {
    mockApi();
    render(<MyRecordScreen />);

    expect(await screen.findByRole("tab", { name: /关于我的记录/ })).toHaveTextContent(
      "1 条等你",
    );
  });
});

describe("谁能看到我", () => {
  it("说清这是给哪件事的、对方看得到什么、什么时候自己失效", async () => {
    mockApi();
    render(<MyRecordScreen />);
    await openTab("谁能看到我");

    const card = within(screen.getByRole("article", { name: "拍一支 60 秒短片" }));
    expect(card.getByText("他们看得到：要做什么")).toBeVisible();
    expect(card.getByText("只拿来配队、他们看不到：我的专业")).toBeVisible();
    expect(card.getByText(/自己失效/)).toBeVisible();
    expect(card.getByText(KEPT_TEXT)).toBeVisible();
  });

  it("一键收回，收回之后这一条立刻不在了", async () => {
    const calls = mockApi();
    render(<MyRecordScreen />);
    await openTab("谁能看到我");

    await userEvent.click(screen.getByRole("button", { name: "收回" }));

    expect(
      await screen.findByText(/现在没有人能看到你的任何东西/),
    ).toBeVisible();
    expect(
      calls.filter((c) => c.url.includes("/envelopes/") && c.method === "POST"),
    ).toHaveLength(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("英文字段名不会原样露出来", async () => {
    mockApi();
    render(<MyRecordScreen />);
    await openTab("谁能看到我");

    for (const raw of ["goal", "major", "solver_only", "candidates", "field_name"]) {
      expect(document.body.textContent ?? "").not.toContain(raw);
    }
  });
});

describe("五态", () => {
  it("首次：说清这一页不给别人看", async () => {
    mockApi();
    render(<MyRecordScreen />);

    expect(await screen.findByRole("heading", { name: "只有你看得到" })).toBeVisible();
    expect(
      screen.getByText(/别人只看到你为某一次事情亲手同意给出去的那一小块/),
    ).toBeVisible();
  });

  it("加载：给骨架，不是一片空白", () => {
    mockApi({ hang: true });
    render(<MyRecordScreen />);

    expect(screen.getByLabelText("加载中")).toBeVisible();
  });

  it("空：什么都没有的人看到一句有用的话加一个能点的入口，不是三个空列表", async () => {
    mockApi({ events: [], records: NOTHING, shown: [] });
    render(<MyRecordScreen />);

    expect(
      await screen.findByText("你还没参加过什么，先说说想做点什么。"),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "说说想做点什么" })).toHaveAttribute(
      "href",
      "/",
    );
    // 三个空框正是这一屏最该避免的样子。
    expect(screen.queryByRole("tab")).toBeNull();
  });

  it("空：只有某一块空的时候，那一块自己说下一步做什么", async () => {
    mockApi({ events: [], records: NOTHING });
    render(<MyRecordScreen />);
    await openTab(/关于我的记录/);

    expect(screen.getByText(/系统还没记下关于你的任何一句话/)).toBeVisible();
    expect(screen.getAllByRole("link", { name: "说说想做点什么" })[0]).toBeVisible();
  });

  it("错误：三块全调不出来时说清哪里断了，并说明什么都没被改动", async () => {
    mockApi({ eventsStatus: 500, recordsStatus: 500, shownStatus: 500 });
    render(<MyRecordScreen />);

    expect(await screen.findByRole("alert")).toHaveTextContent("调不出你这边的东西");
    expect(screen.getByText(/什么都不会被改动/)).toBeVisible();
    expect(screen.getByRole("button", { name: "再试一次" })).toBeVisible();
  });

  it("降级：一块挂了，另外两块照常能用", async () => {
    mockApi({ recordsStatus: 503 });
    render(<MyRecordScreen />);

    expect(await screen.findByRole("article", { name: "檐下" })).toBeVisible();
    await openTab(/关于我的记录/);
    expect(screen.getByText("现在调不出系统记下的那些话。")).toBeVisible();
    expect(screen.getByText(/这一页其余的照常能用/)).toBeVisible();
    await openTab("谁能看到我");
    expect(screen.getByRole("button", { name: "收回" })).toBeEnabled();
  });

  it("降级：收回没发出去时说清那句话还是原样", async () => {
    mockApi({ writeStatus: 503 });
    render(<MyRecordScreen />);
    await openTab(/关于我的记录/);

    await userEvent.click(
      within(screen.getByRole("article", { name: KEPT_TEXT })).getByRole("button", {
        name: "收回",
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("这句话还是原样");
    expect(screen.getByRole("article", { name: KEPT_TEXT })).toBeVisible();
  });
});

describe("语言", () => {
  it("三块都不出现领域词汇", async () => {
    mockApi();
    const { container } = render(<MyRecordScreen />);

    await screen.findByRole("article", { name: "檐下" });
    expectNoDomainWords(container.textContent ?? "");

    await openTab(/关于我的记录/);
    expectNoDomainWords(container.textContent ?? "");

    await openTab("谁能看到我");
    expectNoDomainWords(container.textContent ?? "");
  });

  it("什么都没有的那一屏也不出现领域词汇", async () => {
    mockApi({ events: [], records: NOTHING, shown: [] });
    const { container } = render(<MyRecordScreen />);

    await screen.findByText("你还没参加过什么，先说说想做点什么。");
    expectNoDomainWords(container.textContent ?? "");
  });

  it("不出现任何百分比或分数", async () => {
    mockApi();
    render(<MyRecordScreen />);
    await openTab(/关于我的记录/);

    expect(document.body.textContent ?? "").not.toMatch(
      /%|％|百分|匹配度|得分|评分|可靠度/,
    );
  });
});

function expectNoDomainWords(text: string) {
  for (const term of [
    "意图",
    "主体",
    "切面",
    "共域",
    "记忆切面",
    "匹配信封",
    "同意凭证",
    "代理",
    "授权",
    "成局提案",
    "成局证明",
    "行动回声",
    "共同事件",
    "共同素材",
    "撮合",
    "求解",
    "约束",
    "智能体",
    "组织者",
  ]) {
    expect(text).not.toContain(term);
  }
}
