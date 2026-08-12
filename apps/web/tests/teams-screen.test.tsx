/**
 * 第四屏与第五屏的产品行为：给你找的人 / 还差这几件事。
 *
 * 这两屏是同一个入口的两种结果，所以放在一个文件里测：凑出来了看小队，
 * 凑不出来看还差什么。断言的是用户看到什么、能做什么，不是组件内部长什么样。
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TeamsScreen } from "@/components/teams-screen";

const INTENT_ID = "11111111-1111-4111-8111-111111111111";
const PROPOSAL_ID = "22222222-2222-4222-8222-222222222222";
const ME = "33333333-3333-4333-8333-333333333333";
const SU = "44444444-4444-4444-8444-444444444444";
const CHEN = "55555555-5555-4555-8555-555555555555";

const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString();

const TEAM = {
  proposal_id: PROPOSAL_ID,
  members: [
    { principal_id: ME, display_name: "你" },
    { principal_id: SU, display_name: "苏晚" },
    { principal_id: CHEN, display_name: "陈牧" },
  ],
  why_these_people: [
    { text: "陈牧之前剪过两支短片", source: "approved_facet" },
    { text: "周三晚上你们三个都有空", source: "solver_constraint" },
    { text: "你们都在东校区", source: "solver_constraint" },
    { text: "缺的拍摄由苏晚补上", source: "solver_constraint" },
    { text: "你说的周五截止，他们都赶得上", source: "user_statement" },
    { text: "三个人来自两个院系", source: "objective_contribution" },
  ],
  left_to_humans: [
    { text: "谁来定最后一版剪辑", source: "user_statement" },
    { text: "作品署名怎么算", source: "user_statement" },
  ],
  uncertainties: [{ text: "苏晚没拍过夜景，这块还没底", source: "unresolved_conflict" }],
  stability_note: "他们现在都没有更想去的组" as string | null,
  expires_at: inHours(40),
};

const WAITING_ON_ME = { verdict: "waiting", waiting_on: [ME, SU, CHEN], conditions: [] };

const BLOCKED = {
  stage: "recall",
  statement: "这个组暂时凑不出来：会做这几件事的人，同时限定在这个校区。",
  causes: ["会做这几件事的人", "限定在这个校区"],
  relaxations: [
    { field_name: "location_scope", invitation: "先不限校区", gains: 137, advisable: true, caution: "" },
    { field_name: "needs", invitation: "少要一样本事，自己补上其中一件", gains: 0, advisable: true, caution: "" },
    {
      field_name: "team_size",
      invitation: "少一个人也开始",
      gains: 4,
      advisable: false,
      caution: "这类活动人少的时候最容易出事，建议宁可等等。",
    },
  ],
  next_steps: [
    { kind: "wait_for_supply", invitation: "有人对上了就通知我" },
    { kind: "invite_someone", invitation: "我自己拉一个人进来" },
    { kind: "ask_organizers", invitation: "让社团帮忙找找" },
    { kind: "revise", invitation: "改一改再试" },
  ],
};

const INTENT = {
  id: INTENT_ID,
  principal_id: ME,
  state: "active",
  raw_expression: "想拍个短片",
  content: {
    goal: "周五前完成 60 秒校园流浪猫短片",
    offers: ["写脚本"],
    needs: ["拍摄", "剪辑"],
    time_window: { earliest: inHours(1), deadline: inHours(48) },
    location_scope: "东校区",
    team_size: { minimum: 3, maximum: 4 },
    boundaries: [],
    open_questions: [],
    uncertain_fields: [],
  },
  created_at: inHours(-2),
  expires_at: inHours(48),
  is_matchable: true,
  action_kind: "creative_work",
};

type Call = { url: string; method: string; body: unknown };

type Options = {
  teams?: (typeof TEAM)[];
  blocked?: typeof BLOCKED;
  status?: Record<string, unknown> | null;
  afterDecide?: Record<string, unknown>;
  teamsStatus?: number;
  blockedStatus?: number;
  statusStatus?: number;
  decideStatus?: number;
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
      calls.push({
        url,
        method,
        body: init?.body ? JSON.parse(String(init.body)) : null,
      });

      if (url.endsWith("/teams")) {
        return opts.teamsStatus
          ? reply({ detail: "没连上" }, opts.teamsStatus)
          : reply(opts.teams ?? [TEAM]);
      }
      if (url.endsWith("/blocked")) {
        return opts.blockedStatus
          ? reply({ detail: "没连上" }, opts.blockedStatus)
          : reply(opts.blocked ?? BLOCKED);
      }
      if (url.endsWith("/status")) {
        return opts.statusStatus
          ? reply({ detail: "没连上" }, opts.statusStatus)
          : reply(opts.status === undefined ? WAITING_ON_ME : opts.status);
      }
      if (url.endsWith(":decide")) {
        return opts.decideStatus
          ? reply({ detail: "没连上" }, opts.decideStatus)
          : reply(
              opts.afterDecide ?? {
                verdict: "waiting",
                waiting_on: [SU, CHEN],
                conditions: [],
              },
            );
      }
      if (url === `/api/intents/${INTENT_ID}`) return reply(INTENT);
      return reply(null, 404);
    }),
  );
  return calls;
}

const card = () => screen.getByRole("region", { name: "你、苏晚、陈牧" });
const decides = (calls: Call[]) => calls.filter((c) => c.url.endsWith(":decide"));
const lastDecide = (calls: Call[]) => decides(calls).at(-1)?.body;

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.localStorage.setItem("cofield.principal", ME);
});

describe("为什么是这几个人", () => {
  it("逐条给理由，点一行才展开它是从哪来的", async () => {
    mockApi();
    render(<TeamsScreen intentId={INTENT_ID} />);

    const line = await screen.findByRole("button", { name: "陈牧之前剪过两支短片" });
    expect(screen.getByText("周三晚上你们三个都有空")).toBeVisible();
    // 默认只有结论，来源折着——六条依据全摊开就没人读了。
    expect(screen.queryByText(/这条是他本人同意让你看到的经历/)).toBeNull();

    await userEvent.click(line);
    expect(screen.getByText(/这条是他本人同意让你看到的经历/)).toBeVisible();
  });

  it("留给人的那几件事说成是特意留的，不是没算出来", async () => {
    mockApi();
    render(<TeamsScreen intentId={INTENT_ID} />);

    expect(await screen.findByText("这几件事留给你们自己定")).toBeVisible();
    expect(screen.getByText(/有数据也不该由系统替你们定/)).toBeVisible();
    expect(screen.getByRole("button", { name: "作品署名怎么算" })).toBeVisible();
  });

  it("没底的地方自己说出来，不藏着", async () => {
    mockApi();
    render(<TeamsScreen intentId={INTENT_ID} />);

    expect(await screen.findByText("这几处我还没底")).toBeVisible();
    expect(screen.getByRole("button", { name: "苏晚没拍过夜景，这块还没底" })).toBeVisible();
  });

  it("稳不稳先给结论，过程收在后面", async () => {
    // 后端那句话是**可证伪**的完整论证（"任指一人一组都可以逐条核"），
    // 那是给要复核的人准备的，不是给正在挑队的人看的第一眼。
    // 摊开来占六行，而三张卡摊三遍——结论就此被淹掉。
    mockApi();
    render(<TeamsScreen intentId={INTENT_ID} />);

    expect(await screen.findAllByText("没有人更想去别的组")).not.toHaveLength(0);
    // 过程仍然到得了：一次点击，不是删掉。
    expect(screen.getAllByText(/他们现在都没有更想去的组/)[0]).toBeInTheDocument();
  });
});

describe("三个动作", () => {
  it("我加入之后，说清还在等谁", async () => {
    const calls = mockApi();
    render(<TeamsScreen intentId={INTENT_ID} />);

    await userEvent.click(await screen.findByRole("button", { name: "我加入" }));

    await waitFor(() => {
      expect(within(card()).getByText("还差苏晚、陈牧点头。")).toBeVisible();
    });
    expect(decides(calls)).toHaveLength(1);
    expect(lastDecide(calls)).toMatchObject({ answer: "accepted", condition: null });
  });

  it("拒绝是一步完成的，不再问一次，也不问为什么", async () => {
    const calls = mockApi();
    render(<TeamsScreen intentId={INTENT_ID} />);

    await userEvent.click(await screen.findByRole("button", { name: "我不参加" }));

    expect(await screen.findByText("知道了。这次就到这里。")).toBeVisible();
    expect(decides(calls)).toHaveLength(1);
    expect(lastDecide(calls)).toMatchObject({ answer: "declined", condition: null });
    // 没有二次确认，也没有追问理由的输入框。
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: /确定|确认|再想想|为什么/ })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("拒绝之后剩下的人已经被重新配过，不用干等下一轮", async () => {
    const calls = mockApi({
      afterDecide: { verdict: "declined", waiting_on: [], conditions: [], reformed_teams: 2 },
    });
    render(<TeamsScreen intentId={INTENT_ID} />);

    await userEvent.click(await screen.findByRole("button", { name: "我不参加" }));
    expect(await screen.findByText(/重新配了 2 个小队/)).toBeVisible();

    const before = calls.filter((c) => c.url.endsWith("/teams")).length;
    await userEvent.click(screen.getByRole("button", { name: "看看新配的" }));
    await waitFor(() => {
      expect(calls.filter((c) => c.url.endsWith("/teams")).length).toBe(before + 1);
    });
  });

  it("拒绝和加入摆在一起，不做成灰色小字", async () => {
    mockApi();
    render(<TeamsScreen intentId={INTENT_ID} />);

    const join = await screen.findByRole("button", { name: "我加入" });
    const no = screen.getByRole("button", { name: "我不参加" });
    expect(join.parentElement).toBe(no.parentElement);
    expect(no).toBeEnabled();
  });

  it("「我可以，但……」把原话原样带过去", async () => {
    const calls = mockApi({
      afterDecide: { verdict: "needs_revision", waiting_on: [], conditions: ["周四我要上课"] },
    });
    render(<TeamsScreen intentId={INTENT_ID} />);

    await userEvent.click(await screen.findByRole("button", { name: "我可以，但……" }));
    const box = screen.getByLabelText("你的条件是什么？");
    expect(screen.getByRole("button", { name: "就这么说" })).toBeDisabled();

    await userEvent.type(box, "周四我要上课，换成周三我就来");
    await userEvent.click(screen.getByRole("button", { name: "就这么说" }));

    await waitFor(() => {
      expect(lastDecide(calls)).toMatchObject({ answer: "conditional",
        condition: "周四我要上课，换成周三我就来",
      });
    });
    expect(await screen.findByText(/要改一版，改好会再来问你一次/)).toBeVisible();
    expect(screen.getByRole("button", { name: "看看改完的那版" })).toBeVisible();
  });
});

describe("五态", () => {
  it("首次：说清这是几个小队，以及都不选也可以", async () => {
    mockApi();
    render(<TeamsScreen intentId={INTENT_ID} />);

    expect(await screen.findByText(/选一个，或者都不选——不选不用解释/)).toBeVisible();
    expect(screen.getByText(/这一轮配给你的 1 个小队/)).toBeVisible();
  });

  it("加载：给骨架，不是一片空白", () => {
    mockApi({ hang: true });
    render(<TeamsScreen intentId={INTENT_ID} />);

    expect(screen.getByLabelText("加载中")).toBeVisible();
  });

  it("空：凑不出队时不是一句「暂无结果」，是还差这几件事", async () => {
    mockApi({ teams: [] });
    render(<TeamsScreen intentId={INTENT_ID} />);

    expect(await screen.findByRole("heading", { name: "还差这几件事" })).toBeVisible();
    expect(await screen.findByText(BLOCKED.statement)).toBeVisible();
    // 是哪几条**共同**卡住的，逐条列出来。
    const stuck = within(screen.getByRole("region", { name: "卡在哪" })).getByRole("list");
    expect(stuck).toHaveTextContent("会做这几件事的人");
    expect(stuck).toHaveTextContent("限定在这个校区");
  });

  it("错误：说清哪里断了，并说明没替你答复任何人", async () => {
    mockApi({ teamsStatus: 500 });
    render(<TeamsScreen intentId={INTENT_ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("调不出给你找的人");
    expect(screen.getByRole("button", { name: "再试一次" })).toBeVisible();
  });

  it("降级：看不到还在等谁时，照样能答复，并且明说看不到", async () => {
    mockApi({ statusStatus: 503 });
    render(<TeamsScreen intentId={INTENT_ID} />);

    expect(await screen.findByText(/现在看不到还有谁没回/)).toBeVisible();
    expect(screen.getByRole("button", { name: "我加入" })).toBeEnabled();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("降级：后端少给几段时，这一队其余部分照常显示", async () => {
    mockApi({
      teams: [{ ...TEAM, left_to_humans: [], uncertainties: [], stability_note: null }],
    });
    render(<TeamsScreen intentId={INTENT_ID} />);

    expect(await screen.findByText("周三晚上你们三个都有空")).toBeVisible();
    expect(screen.getByRole("button", { name: "我加入" })).toBeVisible();
    expect(screen.queryByText("这几件事留给你们自己定")).toBeNull();
    expect(screen.queryByText("这几处我还没底")).toBeNull();
  });
});

describe("还差这几件事", () => {
  const blockedScreen = async () => {
    render(<TeamsScreen intentId={INTENT_ID} />);
    await screen.findByRole("heading", { name: "还差这几件事" });
    // 这一屏是两次取数：先知道没凑出来，再知道卡在哪。等到第二次回来再断言。
    await screen.findByText(BLOCKED.statement);
  };

  it("每个可放宽项带真数字，最管用的那一项被标出来", async () => {
    mockApi({ teams: [] });
    await blockedScreen();

    const row = within(screen.getByRole("listitem", { name: "先不限校区" }));
    expect(row.getByText("能多出 137 个人")).toBeVisible();
    expect(row.getByText("这一项最管用")).toBeVisible();
  });

  it("算不出增量时如实说算不出，不估一个数", async () => {
    mockApi({ teams: [] });
    await blockedScreen();

    expect(
      within(screen.getByRole("listitem", { name: "少要一样本事，自己补上其中一件" })).getByText(
        "这一项现在算不出能多出多少人",
      ),
    ).toBeVisible();
  });

  it("不建议的那一项照样列出来，并说清担心什么", async () => {
    mockApi({ teams: [] });
    await blockedScreen();

    const row = within(screen.getByRole("listitem", { name: "少一个人也开始" }));
    expect(row.getByText("能多出 4 个人")).toBeVisible();
    expect(row.getByText(/不建议：这类活动人少的时候最容易出事/)).toBeVisible();
    // 不建议 ≠ 不给：不列等于替用户做了决定。
    expect(row.queryByText("这一项最管用")).toBeNull();
  });

  it("下一步每个都能点，点开都有真东西", async () => {
    mockApi({ teams: [] });
    await blockedScreen();

    await userEvent.click(screen.getByRole("button", { name: "有人对上了就通知我" }));
    expect(screen.getByText(/每一轮都会再试一次/)).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "我自己拉一个人进来" }));
    expect(screen.getByLabelText("可以直接发出去的话")).toHaveValue(
      "我在做：周五前完成 60 秒校园流浪猫短片。还缺拍摄、剪辑。你有空吗？或者认识合适的人吗？",
    );

    await userEvent.click(screen.getByRole("button", { name: "让社团帮忙找找" }));
    expect(screen.getByLabelText("可以直接发出去的话")).toHaveValue(
      "我在做：周五前完成 60 秒校园流浪猫短片。还缺拍摄、剪辑。社团里有合适的人吗？",
    );

    await userEvent.click(screen.getByRole("button", { name: "改一改再试" }));
    expect(screen.getByLabelText("我缺")).toHaveValue("拍摄、剪辑");
  });

  it("空：连卡在哪都说不出来时，仍然给一条能走的路", async () => {
    mockApi({
      teams: [],
      blocked: { ...BLOCKED, causes: [], relaxations: [], next_steps: [] },
    });
    await blockedScreen();

    expect(screen.getByText(/这次没看出是卡在哪一条上/)).toBeVisible();
    expect(screen.getByRole("link", { name: "去看下次什么时候配" })).toBeVisible();
  });

  it("错误：查不到卡在哪时说清楚，并说明这件事还在队里", async () => {
    mockApi({ teams: [], blockedStatus: 500 });
    render(<TeamsScreen intentId={INTENT_ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("查不到这次卡在哪");
    expect(screen.getByRole("button", { name: "再看一次" })).toBeVisible();
  });
});

describe("语言", () => {
  it("给你找的人这一屏不出现领域词汇", async () => {
    mockApi();
    const { container } = render(<TeamsScreen intentId={INTENT_ID} />);

    await screen.findByText("周三晚上你们三个都有空");
    for (const line of TEAM.why_these_people) {
      await userEvent.click(screen.getByRole("button", { name: line.text }));
    }
    expectNoDomainWords(container.textContent ?? "");
  });

  it("还差这几件事这一屏也不出现领域词汇", async () => {
    mockApi({ teams: [] });
    const { container } = render(<TeamsScreen intentId={INTENT_ID} />);

    await screen.findByRole("heading", { name: "还差这几件事" });
    await screen.findByText(BLOCKED.statement);
    for (const step of BLOCKED.next_steps) {
      await userEvent.click(screen.getByRole("button", { name: step.invitation }));
    }
    expectNoDomainWords(container.textContent ?? "");
  });

  it("来源的英文标识符不会原样露出来", async () => {
    mockApi();
    render(<TeamsScreen intentId={INTENT_ID} />);

    await userEvent.click(await screen.findByRole("button", { name: "陈牧之前剪过两支短片" }));
    for (const raw of [
      "approved_facet",
      "solver_constraint",
      "objective_contribution",
      "user_statement",
      "unresolved_conflict",
      "accepted",
      "declined",
      "conditional",
    ]) {
      expect(document.body.textContent ?? "").not.toContain(raw);
    }
  });

  it("不出现任何百分比或分数", async () => {
    mockApi();
    render(<TeamsScreen intentId={INTENT_ID} />);

    await screen.findByText("周三晚上你们三个都有空");
    expect(document.body.textContent ?? "").not.toMatch(
      /%|％|百分|匹配度|得分|评分|\d+\s*分(?!钟)/,
    );
  });
});

function expectNoDomainWords(text: string) {
  for (const term of [
    "意图",
    "主体",
    "切面",
    "共域",
    "匹配信封",
    "成局提案",
    "成局证明",
    "稳定性检查",
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
}
