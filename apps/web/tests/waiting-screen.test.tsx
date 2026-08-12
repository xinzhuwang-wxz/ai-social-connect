/**
 * 第三屏的产品行为：等配队。
 *
 * 断言的是用户在等待期间能知道什么、能做什么，不是组件内部长什么样。
 * 后端在这套用例里是有状态的——改完需求要能看见它真的被送回队列，
 * 否则"等待期仍然可以改"这条就成了对着写死的假数据自说自话。
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WaitingScreen } from "@/components/waiting-screen";

const INTENT_ID = "11111111-1111-4111-8111-111111111111";
const ME = "33333333-3333-4333-8333-333333333333";

/** 三小时后配队。用相对时间写，免得用例跟着机器时区飘。 */
const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString();

const GAPS = [
  { skill: "剪辑", wanted: 12, offered: 3, scarce: true },
  { skill: "拍摄", wanted: 5, offered: 8, scarce: false },
];

const CONTENT = {
  goal: "周五前完成 60 秒校园流浪猫短片",
  offers: ["写脚本"],
  needs: ["拍摄", "剪辑"],
  time_window: { earliest: inHours(1), deadline: inHours(48) },
  location_scope: null,
  team_size: { minimum: 3, maximum: 4 },
  boundaries: [],
  open_questions: [],
  uncertain_fields: [],
};

const INTENT = {
  id: INTENT_ID,
  principal_id: ME,
  state: "active",
  raw_expression: "想拍个短片",
  content: CONTENT,
  created_at: inHours(-2),
  expires_at: inHours(48),
  is_matchable: true,
  action_kind: "creative_work",
};

type Call = { url: string; method: string; body: unknown };

type Options = {
  nextRoundAt?: string;
  gaps?: typeof GAPS;
  waitingCount?: number;
  canStillRevise?: boolean;
  intents?: (typeof INTENT)[];
  waitingStatus?: number;
  intentsStatus?: number;
  patchStatus?: number;
  hang?: boolean;
};

function mockApi(opts: Options = {}): Call[] {
  let intents = opts.intents ?? [INTENT];
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

      if (url.startsWith("/api/me/waiting")) {
        return opts.waitingStatus
          ? reply({ detail: "没连上" }, opts.waitingStatus)
          : reply({
              next_round_at: opts.nextRoundAt ?? inHours(3),
              waiting_count: opts.waitingCount ?? 12,
              gaps: opts.gaps ?? GAPS,
              can_still_revise: opts.canStillRevise ?? true,
            });
      }
      if (url === "/api/me/intents") {
        return opts.intentsStatus
          ? reply({ detail: "没连上" }, opts.intentsStatus)
          : reply(intents);
      }
      if (url === "/api/clearing:run") {
        return reply({ considered: 8, proposed: 2, blocked: 1, early: 0 });
      }
      if (url === `/api/intents/${INTENT_ID}` && method === "PATCH") {
        if (opts.patchStatus) return reply({ detail: "没连上" }, opts.patchStatus);
        // 后端会把改过的需求打回草稿——不重新确认就等于退出了配队。
        intents = intents.map((i) => ({
          ...i,
          content: { ...i.content, ...(body?.content ?? {}) },
          state: "draft",
          is_matchable: false,
        }));
        return reply(intents[0]);
      }
      if (url === `/api/intents/${INTENT_ID}:withdraw`) {
        intents = intents.map((i) => ({
          ...i,
          state: "withdrawn",
          is_matchable: false,
        }));
        return reply(intents[0]);
      }
      if (url === `/api/intents/${INTENT_ID}:confirm`) {
        intents = intents.map((i) => ({ ...i, state: "active", is_matchable: true }));
        return reply(intents[0]);
      }
      return reply(null, 404);
    }),
  );
  return calls;
}

const gaps = () => screen.getByRole("region", { name: "现在缺什么" });
const patched = (calls: Call[]) =>
  calls.filter((c) => c.method === "PATCH").at(-1)?.body as
    | { content: { needs: string[]; offers: string[] } }
    | undefined;

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.localStorage.setItem("cofield.principal", ME);
});

describe("等待要有信息", () => {
  it("说清下次什么时候配队，不是一串时间戳", async () => {
    const at = inHours(3);
    mockApi({ nextRoundAt: at });
    const { container } = render(<WaitingScreen />);

    expect(await screen.findByRole("heading", { name: /开始配队/ })).toBeVisible();
    expect(screen.getByText(/还有约 3 小时/)).toBeVisible();
    expect(container.textContent ?? "").not.toContain(at);
  });

  it("这个方向上缺什么，只给人数不给名字", async () => {
    const calls = mockApi();
    render(<WaitingScreen />);

    const box = within(await screen.findByRole("region", { name: "现在缺什么" }));
    // 缺口要按你在等的那件事的方向问，不然拿回来的是全校混在一起的数。
    expect(calls.some((c) => c.url === "/api/me/waiting?action_kind=creative_work")).toBe(true);
    expect(box.getByText("剪辑")).toBeVisible();
    expect(box.getByText("12 个人要，3 个人会")).toBeVisible();
    expect(box.getByText("还缺 9 个")).toBeVisible();
    // 说的是"看不到是谁"以及"你会的话该干什么"——**不是**在跟用户解释
    // 我们决定不显示名字。他要知道的不是我们定了什么，是他能做什么。
    expect(box.getByText(/看不到是谁/)).toBeVisible();
    // 不缺的那样不该被标成缺口。
    expect(box.queryByText("还缺 -3 个")).toBeNull();
  });

  it("说清现在有多少人也在等", async () => {
    mockApi({ waitingCount: 12 });
    render(<WaitingScreen />);

    expect(await screen.findByText(/现在有 12 个人在等/)).toBeVisible();
  });
});

describe("等待期间仍然可以改", () => {
  it("改完我缺，这件事仍然留在队里等下一轮", async () => {
    const calls = mockApi();
    render(<WaitingScreen />);

    const field = await screen.findByLabelText("我缺");
    await userEvent.clear(field);
    await userEvent.type(field, "拍摄、剪辑、配乐");
    await userEvent.click(screen.getByRole("button", { name: "改好了" }));

    await waitFor(() => {
      expect(patched(calls)?.content.needs).toEqual(["拍摄", "剪辑", "配乐"]);
    });
    // 改动会把这条打回草稿，不补这一步用户就悄无声息地退出了配队。
    expect(calls.some((c) => c.url.endsWith(":confirm"))).toBe(true);
    expect(await screen.findByText("改好了，下一轮按新的来。")).toBeVisible();
  });

  it("最难找的那一样可以一键自己顶上", async () => {
    const calls = mockApi();
    render(<WaitingScreen />);

    // 只对缺口大的那一样给这个快捷动作——不缺的那样不该建议你自己来。
    expect(await screen.findByRole("button", { name: "「剪辑」这一样我自己来" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "「拍摄」这一样我自己来" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "「剪辑」这一样我自己来" }));

    await waitFor(() => {
      expect(patched(calls)?.content.needs).toEqual(["拍摄"]);
    });
    expect(patched(calls)?.content.offers).toEqual(["写脚本", "剪辑"]);
  });

  it("改不上的时候说清楚，不假装改上了", async () => {
    mockApi({ patchStatus: 500 });
    render(<WaitingScreen />);

    const field = await screen.findByLabelText("我缺");
    await userEvent.type(field, "、配乐");
    await userEvent.click(screen.getByRole("button", { name: "改好了" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("没改上");
    expect(screen.getByLabelText("我缺")).toHaveValue("拍摄、剪辑、配乐");
  });
});

describe("五态", () => {
  it("首次：还没有在等的事，给一条路，不是一片空白", async () => {
    mockApi({ intents: [] });
    render(<WaitingScreen />);

    expect(await screen.findByText("你还没有正在等配队的事。")).toBeVisible();
    expect(screen.getByRole("link", { name: "去说一件事" })).toBeVisible();
  });

  it("加载：给骨架，不是一片空白", () => {
    mockApi({ hang: true });
    render(<WaitingScreen />);

    expect(screen.getByLabelText("加载中")).toBeVisible();
  });

  it("空：没人写下缺什么时，说清为什么空并指一条路", async () => {
    mockApi({ gaps: [] });
    render(<WaitingScreen />);

    expect(await screen.findByText(/还没有人写下自己缺什么/)).toBeVisible();
    expect(within(gaps()).getByText(/下一轮就有人能对上/)).toBeVisible();
  });

  it("错误：说清哪里断了，并说明你说过的事还在", async () => {
    mockApi({ waitingStatus: 500 });
    render(<WaitingScreen />);

    expect(await screen.findByRole("alert")).toHaveTextContent("查不到下次什么时候配队");
    expect(screen.getByRole("button", { name: "再看一次" })).toBeVisible();
  });

  it("降级：调不出你在等的事时，下次配队时间和缺口照常显示", async () => {
    mockApi({ intentsStatus: 503 });
    render(<WaitingScreen />);

    expect(await screen.findByText(/调不出你在等的那几件事/)).toBeVisible();
    expect(screen.getByRole("heading", { name: /开始配队/ })).toBeVisible();
    expect(within(gaps()).getByText("剪辑")).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("语言", () => {
  it("界面上不出现领域词汇", async () => {
    mockApi();
    const { container } = render(<WaitingScreen />);

    await screen.findByRole("heading", { name: /开始配队/ });
    await screen.findByLabelText("我缺");
    const text = container.textContent ?? "";
    for (const term of [
      "意图",
      "主体",
      "切面",
      "共域",
      "匹配信封",
      "成局提案",
      "成局证明",
      "稳定性",
      "漏斗",
      "召回",
      "求解",
      "约束",
      "撮合窗口",
      "智能体",
      "代理",
    ]) {
      expect(text).not.toContain(term);
    }
  });

  it("不出现任何百分比或分数", async () => {
    mockApi();
    render(<WaitingScreen />);

    await screen.findByRole("heading", { name: /开始配队/ });
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/%|％|百分|匹配度|得分|评分|\d+\s*分(?!钟)/);
  });
});

describe("这事不找了", () => {
  it("一条发出去的需求收得回来", async () => {
    // 在这之前它没有任何办法收回：会一直待在池子里，一轮一轮占着
    // 会这一样的人，还不停给本人推他早就不想要的小队。
    const calls = mockApi();
    render(<WaitingScreen />);

    await userEvent.click(await screen.findByRole("button", { name: "这事不找了" }));

    await waitFor(() =>
      expect(
        calls.some((c) => c.url.endsWith(":withdraw") && c.method === "POST"),
      ).toBe(true),
    );
    expect(await screen.findByText("你还没有正在等配队的事。")).toBeVisible();
  });

  it("收回是一步完成的：不问为什么，不再确认一次", async () => {
    // 和「我不参加」同一条。退出要和加入一样便宜，否则人会用"不理它"
    // 来代替退出，而不理它的代价由其他等着的人付。
    mockApi();
    render(<WaitingScreen />);

    await userEvent.click(await screen.findByRole("button", { name: "这事不找了" }));

    expect(screen.queryByText(/确定|真的要|为什么/)).toBeNull();
  });
});
