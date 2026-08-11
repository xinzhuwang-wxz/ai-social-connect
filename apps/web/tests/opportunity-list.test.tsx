/**
 * 学生侧的产品行为：现在有谁在招人。
 *
 * 断言的是学生看到什么、据此能判断出什么，不是组件内部长什么样。这一屏的
 * 每一条断言背后都有一个具体的失败：读不出缺口就不知道自己算不算，看不到
 * 核没核过就分不出这是不是一个用来收集信息的假项目，看不到负责人就没人可问。
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OpportunityList } from "@/components/opportunity-list";

const ME = "33333333-3333-4333-8333-333333333333";
const ORG = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString();

const FILM = {
  id: "11111111-1111-4111-8111-111111111111",
  organization_id: ORG,
  organization_name: "青影社",
  organization_verified: true,
  kind_key: "creative_work",
  title: "校园流浪猫 60 秒短片",
  goal: "周五前出一支能发出去的成片",
  seats: [
    { role: "剪辑", capacity: 3, filled: 1, gap: 2 },
    { role: "拍摄", capacity: 2, filled: 1, gap: 1 },
    { role: "策划", capacity: 1, filled: 1, gap: 0 },
  ],
  total_gap: 3,
  deadline: inHours(60),
  location_scope: "东校区",
  qualifications: ["必须：能到东校区", "加分：拍过一次短片", "自带设备更好"],
  state: "open",
  steward_name: "陈牧",
};

const ROBOT = {
  id: "22222222-2222-4222-8222-222222222222",
  organization_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  organization_name: "机器人队",
  organization_verified: true,
  kind_key: "competition",
  title: "机器人赛前调试",
  goal: "两周内跑完全场",
  seats: [{ role: "机械", capacity: 2, filled: 0, gap: 2 }],
  total_gap: 2,
  deadline: inHours(20),
  location_scope: null,
  qualifications: [],
  state: "open",
  steward_name: "苏晚",
};

const MY_INTENT = {
  id: "44444444-4444-4444-8444-444444444444",
  principal_id: ME,
  state: "active",
  raw_expression: "想剪片子",
  content: {
    goal: "想练剪辑",
    offers: ["剪辑"],
    needs: [],
    time_window: null,
    location_scope: null,
    team_size: null,
    boundaries: [],
    open_questions: [],
    uncertain_fields: [],
  },
  created_at: inHours(-2),
  expires_at: inHours(48),
  is_matchable: true,
  action_kind: "creative_work",
};

type Options = {
  list?: unknown[];
  listStatus?: number;
  intentsStatus?: number;
  intents?: unknown[];
  hang?: boolean;
};

function mockApi(opts: Options = {}) {
  const reply = (body: unknown, status = 200) => ({
    ok: status < 300,
    status,
    json: async () => body,
  });

  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (opts.hang) return new Promise(() => {});
      if (url === "/api/me/intents") {
        return opts.intentsStatus
          ? reply({ detail: "没连上" }, opts.intentsStatus)
          : reply(opts.intents ?? [MY_INTENT]);
      }
      if (url === "/api/opportunities") {
        return opts.listStatus
          ? reply({ detail: "没连上" }, opts.listStatus)
          : reply(opts.list ?? [FILM, ROBOT]);
      }
      return reply(null, 404);
    }),
  );
}

const cardFor = (name: string) => screen.findByRole("article", { name });

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.localStorage.setItem("cofield.principal", ME);
});

describe("这条招募缺什么", () => {
  it("缺口是具体的角色和数量，不是一个总数", async () => {
    mockApi();
    render(<OpportunityList />);

    const gaps = within(await screen.findByRole("article", { name: FILM.title })).getByRole(
      "region",
      { name: "还缺什么" },
    );
    expect(within(gaps).getByText("剪辑")).toBeVisible();
    expect(within(gaps).getByText("还缺 2 个")).toBeVisible();
    expect(within(gaps).getByText("拍摄")).toBeVisible();
    expect(within(gaps).getByText("还缺 1 个")).toBeVisible();
    // 已经满的那一档照样列出来，学生才知道这个角色不用再问。
    expect(within(gaps).getByText("策划 已经满了")).toBeVisible();
    // 三个缺口不能被压成一句"还缺 3 个人"——那句话读完还是不知道自己算不算。
    expect(document.body.textContent ?? "").not.toContain("还缺 3 个");
  });

  it("缺口一行里同时有要几个和已经有几个", async () => {
    mockApi();
    render(<OpportunityList />);

    expect(
      within(await screen.findByRole("article", { name: FILM.title })).getByText(
        "一共要 3 个，已经有 1 个",
      ),
    ).toBeVisible();
  });

  it("一条都没写角色时明说看不出你能不能补上", async () => {
    mockApi({ list: [{ ...FILM, seats: [], total_gap: 0 }] });
    render(<OpportunityList />);

    expect(await screen.findByText(/没写缺哪些角色，看不出你能不能补上/)).toBeVisible();
  });
});

describe("这是不是一个假项目", () => {
  it("核过的组织把这件事说出来", async () => {
    mockApi();
    render(<OpportunityList />);

    const who = within(await screen.findByRole("article", { name: FILM.title }));
    expect(who.getByText("青影社")).toBeVisible();
    expect(who.getByText("校园核过这个组织")).toBeVisible();
  });

  it("没核过的组织标得很显眼，并说清该怎么办", async () => {
    mockApi({ list: [{ ...FILM, organization_verified: false }] });
    render(<OpportunityList />);

    const notice = within(await screen.findByRole("article", { name: FILM.title })).getByRole(
      "alert",
    );
    expect(within(notice).getByText("校园没核过这个组织")).toBeVisible();
    expect(within(notice).getByText(/别先交学号、手机号这些/)).toBeVisible();
  });
});

describe("谁负责", () => {
  it("负责人一定显示，并说清有问题找谁", async () => {
    mockApi();
    render(<OpportunityList />);

    expect(
      within(await screen.findByRole("article", { name: FILM.title })).getByText(
        "这件事由 陈牧 负责，有问题找他。",
      ),
    ).toBeVisible();
  });

  it("没写负责人时不留白，直接说这件事会烂在那里", async () => {
    mockApi({ list: [{ ...FILM, steward_name: null }] });
    render(<OpportunityList />);

    const shown = within(await cardFor(FILM.title));
    expect(shown.getByText(/没写谁负责/)).toBeVisible();
    expect(shown.getByText(/烂在那里/)).toBeVisible();
  });
});

describe("要求分得清硬软", () => {
  it("必须满足的、会加分的、没说清的分三堆", async () => {
    mockApi();
    render(<OpportunityList />);

    const asked = within(await screen.findByRole("article", { name: FILM.title })).getByRole(
      "region",
      { name: "什么样的人能来" },
    );
    expect(within(asked).getByText("必须满足的")).toBeVisible();
    expect(within(asked).getByText("能到东校区")).toBeVisible();
    expect(within(asked).getByText("会加分的")).toBeVisible();
    expect(within(asked).getByText("拍过一次短片")).toBeVisible();
    // 没带前缀的旧数据不擅自当成硬要求——读错一条就是把够格的人挡在外面。
    expect(within(asked).getByText("这几条没说清是必须还是加分")).toBeVisible();
    expect(within(asked).getByText("自带设备更好")).toBeVisible();
  });
});

describe("排序与截止期", () => {
  it("我能补上的缺口排前面，不按发布时间", async () => {
    // 机器人那条截止得更急，但我会的是剪辑——能上的那条才该排第一。
    mockApi();
    render(<OpportunityList />);

    await screen.findByRole("article", { name: FILM.title });
    const titles = screen.getAllByRole("article").map((el) => el.getAttribute("aria-label"));
    expect(titles).toEqual([FILM.title, ROBOT.title]);
    expect(screen.getByText("你说过你能做剪辑，这里正缺。")).toBeVisible();
  });

  it("对不上任何一条时按截止得急的排", async () => {
    mockApi({ intents: [] });
    render(<OpportunityList />);

    await screen.findByRole("article", { name: ROBOT.title });
    const titles = screen.getAllByRole("article").map((el) => el.getAttribute("aria-label"));
    expect(titles).toEqual([ROBOT.title, FILM.title]);
  });

  it("截止期说人话，不是一串时间戳", async () => {
    mockApi();
    render(<OpportunityList />);

    const when = within(await screen.findByRole("article", { name: ROBOT.title })).getByText(
      /截止，还有约 20 小时/,
    );
    expect(when).toBeVisible();
    expect(when.textContent ?? "").not.toMatch(/\d{4}-\d{2}-\d{2}T/);
  });
});

describe("五态", () => {
  it("首次：说清这一屏按什么排、每条会给什么", async () => {
    mockApi();
    render(<OpportunityList />);

    expect(await screen.findByText(/能补上你缺口的排在前面/)).toBeVisible();
    expect(screen.getByText(/还缺什么、缺几个、谁负责/)).toBeVisible();
  });

  it("加载：给骨架，不是一片空白", () => {
    mockApi({ hang: true });
    render(<OpportunityList />);

    expect(screen.getByLabelText("加载中")).toBeVisible();
  });

  it("空：不是一句「暂无」，而是给一条自己发起的路", async () => {
    mockApi({ list: [] });
    render(<OpportunityList />);

    expect(await screen.findByText("现在没有正在招人的事。")).toBeVisible();
    expect(screen.getByText(/你也可以自己发起一件/)).toBeVisible();
    const start = screen.getByRole("link", { name: "发一份招募" });
    expect(start).toHaveAttribute("href", "/opportunities/new");
    expect(screen.getByRole("link", { name: "先说说我想做什么" })).toHaveAttribute("href", "/");
  });

  it("错误：说清哪里断了，并说明你说过的事还在", async () => {
    mockApi({ listStatus: 500 });
    render(<OpportunityList />);

    expect(await screen.findByRole("alert")).toHaveTextContent("调不出正在招人的事");
    expect(screen.getByRole("button", { name: "再看一次" })).toBeVisible();
  });

  it("降级：读不到组织信息时，这条招募照常显示", async () => {
    mockApi({
      list: [{ ...FILM, organization_name: "未知组织", organization_verified: false }],
    });
    render(<OpportunityList />);

    const shown = within(await cardFor(FILM.title));
    expect(shown.getByText("这个组织的信息暂时调不出来。")).toBeVisible();
    // 招募本身照常：缺口、负责人、截止期一样不少。
    expect(shown.getByText("剪辑")).toBeVisible();
    expect(shown.getByText("这件事由 陈牧 负责，有问题找他。")).toBeVisible();
    // 调不出来不等于"没核过"，不能吓唬人。
    expect(shown.queryByText("校园没核过这个组织")).toBeNull();
  });

  it("降级：读不到我说过的事时，列表照常，只是顺序说清换了", async () => {
    mockApi({ intentsStatus: 503 });
    render(<OpportunityList />);

    expect(await screen.findByText(/先按截止得急的排/)).toBeVisible();
    expect(screen.getAllByRole("article")).toHaveLength(2);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("错误之后能再试一次", async () => {
    mockApi({ listStatus: 500 });
    render(<OpportunityList />);

    await screen.findByRole("alert");
    mockApi();
    await userEvent.click(screen.getByRole("button", { name: "再看一次" }));

    await waitFor(() => {
      expect(screen.getByRole("article", { name: FILM.title })).toBeVisible();
    });
  });
});

describe("语言", () => {
  it("这一屏不出现领域词汇", async () => {
    mockApi();
    const { container } = render(<OpportunityList />);

    await screen.findByRole("article", { name: FILM.title });
    expectNoDomainWords(container.textContent ?? "");
  });

  it("空态和错误态也不出现领域词汇", async () => {
    mockApi({ list: [] });
    const { container } = render(<OpportunityList />);

    await screen.findByText("现在没有正在招人的事。");
    expectNoDomainWords(container.textContent ?? "");
  });

  it("后端的英文标识符不会原样露出来", async () => {
    mockApi();
    render(<OpportunityList />);

    await screen.findByRole("article", { name: FILM.title });
    for (const raw of ["creative_work", "competition", "open", "organization_verified"]) {
      expect(document.body.textContent ?? "").not.toContain(raw);
    }
  });

  it("不出现任何百分比或分数", async () => {
    mockApi();
    render(<OpportunityList />);

    await screen.findByRole("article", { name: FILM.title });
    expect(document.body.textContent ?? "").not.toMatch(/%|％|百分|匹配度|得分|评分/);
  });
});

function expectNoDomainWords(text: string) {
  for (const term of [
    "行动机会",
    "席位",
    "主体",
    "意图",
    "共域",
    "切面",
    "提案",
    "求解",
    "召回",
    "约束",
    "智能体",
    "代理",
    "组织者",
    "撮合",
    "授权",
    "信封",
    "凭证",
    "稳定性",
    "回声",
    "素材",
    "行动类别",
  ]) {
    expect(text).not.toContain(term);
  }
}
