/**
 * 发布那一侧的产品行为：发一份招募。
 *
 * 这一屏的每一条断言背后都有一个具体的失败：缺口写不清就没人知道自己能不能
 * 补上，没写负责人的事最后会烂在那里，拦住却不说缺什么等于让人自己去找，
 * 发出去之前看不到学生会看到什么就只能靠猜。
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OpportunityForm } from "@/components/opportunity-form";

const ME = "33333333-3333-4333-8333-333333333333";
const ORG = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const OTHER_ORG = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString();

/** `datetime-local` 要的是本地时间文本，不是 ISO。 */
function localAt(hours: number): string {
  const t = new Date(Date.now() + hours * 3_600_000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}T${pad(
    t.getHours(),
  )}:${pad(t.getMinutes())}`;
}

const EXISTING = {
  id: "11111111-1111-4111-8111-111111111111",
  organization_id: ORG,
  organization_name: "青影社",
  organization_verified: true,
  kind_key: "creative_work",
  title: "已经在招的一件事",
  goal: "随便什么",
  seats: [{ role: "剪辑", capacity: 1, filled: 0, gap: 1 }],
  total_gap: 1,
  deadline: inHours(50),
  location_scope: null,
  qualifications: [],
  state: "open",
};

const UNVERIFIED = {
  ...EXISTING,
  id: "22222222-2222-4222-8222-222222222222",
  organization_id: OTHER_ORG,
  organization_name: "野队",
  organization_verified: false,
};

const KINDS = [
  {
    key: "creative_work",
    label: "一起做点东西",
    starter: {
      key: "creative_work",
      title: "做点东西",
      example: "我想拍个短片",
      roles: ["拍摄", "剪辑"],
    },
    risk_tier: "low",
    place_precision: "campus",
    agent_reply_policy: "disclose",
    matching_window_seconds: 21600,
  },
];

type Call = { url: string; method: string; body: Record<string, unknown> | null };

type Options = {
  list?: unknown[];
  listStatus?: number;
  kindsStatus?: number;
  createStatus?: number;
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

      if (url === "/api/action-kinds") {
        return opts.kindsStatus
          ? reply({ detail: "没连上" }, opts.kindsStatus)
          : reply(KINDS);
      }
      if (url === "/api/opportunities" && method === "POST") {
        if (opts.createStatus) {
          return reply(
            opts.createStatus === 403 ? "未验证的组织不能发布招募" : "没连上",
            opts.createStatus,
          );
        }
        const sent = JSON.parse(String(init?.body)) as Record<string, unknown>;
        return reply(
          {
            ...EXISTING,
            id: "33333333-3333-4333-8333-000000000000",
            ...sent,
            seats: (sent.seats as { role: string; capacity: number }[]).map((s) => ({
              ...s,
              filled: 0,
              gap: s.capacity,
            })),
            organization_name: "青影社",
            organization_verified: true,
            total_gap: 0,
            state: "open",
          },
          201,
        );
      }
      if (url === "/api/opportunities") {
        return opts.listStatus
          ? reply({ detail: "没连上" }, opts.listStatus)
          : reply(opts.list ?? [EXISTING]);
      }
      return reply(null, 404);
    }),
  );
  return calls;
}

const posted = (calls: Call[]) =>
  calls.filter((c) => c.url === "/api/opportunities" && c.method === "POST");

/** 把一份能通过的招募填完。单项测试再把其中一项挖掉。 */
async function fillEverything() {
  await screen.findByLabelText("这件事叫什么");
  await userEvent.type(screen.getByLabelText("这件事叫什么"), "校园流浪猫 60 秒短片");
  await userEvent.type(screen.getByLabelText("要做成什么样"), "周五前出一支成片");
  await userEvent.selectOptions(screen.getByLabelText("这是件什么事"), "creative_work");
  await userEvent.type(screen.getByLabelText("第 1 个角色"), "剪辑");
  await userEvent.clear(screen.getByLabelText("第 1 个角色要几个人"));
  await userEvent.type(screen.getByLabelText("第 1 个角色要几个人"), "2");
  await userEvent.type(screen.getByLabelText("谁负责这件事"), "陈牧");
  fireEvent.change(screen.getByLabelText("什么时候截止"), {
    target: { value: localAt(72) },
  });
}

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.localStorage.setItem("cofield.principal", ME);
});

describe("缺口是结构化的", () => {
  it("角色和数量分成两个格子，不是一个自由文本框", async () => {
    mockApi();
    render(<OpportunityForm />);

    expect(await screen.findByLabelText("第 1 个角色")).toBeVisible();
    expect(screen.getByLabelText("第 1 个角色要几个人")).toBeVisible();
    expect(screen.getByText(/写「招若干人」，谁都不知道自己能不能补上/)).toBeVisible();
  });

  it("能加第二个角色，也能删掉", async () => {
    mockApi();
    render(<OpportunityForm />);

    await userEvent.click(await screen.findByRole("button", { name: "再加一个角色" }));
    expect(screen.getByLabelText("第 2 个角色")).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "删掉第 2 行" }));
    expect(screen.queryByLabelText("第 2 个角色")).toBeNull();
  });

  it("选了类别之后给这一类常见的角色，点一下就成一行", async () => {
    mockApi();
    render(<OpportunityForm />);

    await userEvent.selectOptions(
      await screen.findByLabelText("这是件什么事"),
      "creative_work",
    );
    await userEvent.click(screen.getByRole("button", { name: "加「剪辑」" }));

    expect(screen.getByLabelText("第 1 个角色")).toHaveValue("剪辑");
  });

  it("角色和数量原样送出去，不是一句话", async () => {
    const calls = mockApi();
    render(<OpportunityForm />);

    await fillEverything();
    await userEvent.click(screen.getByRole("button", { name: "发出去" }));

    await waitFor(() => expect(posted(calls)).toHaveLength(1));
    expect(posted(calls)[0]?.body).toMatchObject({
      organization_id: ORG,
      kind_key: "creative_work",
      title: "校园流浪猫 60 秒短片",
      seats: [{ role: "剪辑", capacity: 2 }],
      steward_name: "陈牧",
    });
  });
});

describe("拦住的时候说清缺了什么", () => {
  it("没写角色会被拦住，并说清缺的是角色", async () => {
    const calls = mockApi();
    render(<OpportunityForm />);

    await fillEverything();
    await userEvent.clear(screen.getByLabelText("第 1 个角色"));
    await userEvent.click(screen.getByRole("button", { name: "发出去" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("还没写缺哪些角色");
    expect(posted(calls)).toHaveLength(0);
  });

  it("没写负责人会被拦住，并说清没人负责的后果", async () => {
    const calls = mockApi();
    render(<OpportunityForm />);

    await fillEverything();
    await userEvent.clear(screen.getByLabelText("谁负责这件事"));
    await userEvent.click(screen.getByRole("button", { name: "发出去" }));

    const stop = await screen.findByRole("alert");
    expect(stop).toHaveTextContent("还没写谁负责这件事");
    expect(stop).toHaveTextContent("事情会烂在那里");
    expect(posted(calls)).toHaveLength(0);
  });

  it("一次把缺的几样都列出来，不是一次挡一条", async () => {
    mockApi();
    render(<OpportunityForm />);

    await screen.findByLabelText("这件事叫什么");
    await userEvent.click(screen.getByRole("button", { name: "发出去" }));

    const stop = within(await screen.findByRole("alert"));
    expect(stop.getByText("还没写这件事叫什么。")).toBeVisible();
    expect(stop.getByText("还没写这件事要做成什么样。")).toBeVisible();
    expect(stop.getByText("还没选这是件什么事。")).toBeVisible();
    expect(stop.getByText(/还没写缺哪些角色/)).toBeVisible();
    expect(stop.getByText(/还没写谁负责这件事/)).toBeVisible();
    expect(stop.getByText("还没写什么时候截止。")).toBeVisible();
  });

  it("截止时间已经过了会被拦住", async () => {
    mockApi();
    render(<OpportunityForm />);

    await fillEverything();
    fireEvent.change(screen.getByLabelText("什么时候截止"), {
      target: { value: localAt(-24) },
    });
    await userEvent.click(screen.getByRole("button", { name: "发出去" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("截止时间已经过了");
  });

  it("同一个角色写两遍会被拦住", async () => {
    mockApi();
    render(<OpportunityForm />);

    await fillEverything();
    await userEvent.click(screen.getByRole("button", { name: "再加一个角色" }));
    await userEvent.type(screen.getByLabelText("第 2 个角色"), "剪辑");
    await userEvent.click(screen.getByRole("button", { name: "发出去" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("同一个角色写了两遍");
  });

  it("没核过的组织发不出去，并说清该先办哪一步", async () => {
    const calls = mockApi({ list: [UNVERIFIED] });
    render(<OpportunityForm />);

    await fillEverything();
    await userEvent.click(screen.getByRole("button", { name: "发出去" }));

    // 选中的那一刻就在下拉框旁边说了，拦住的时候再说一次该怎么办。
    expect(screen.getByText(/野队还没被校园核过，不能在这里招人/)).toBeVisible();
    expect(await screen.findByRole("alert", { name: "还差什么" })).toHaveTextContent(
      "换一个组织，或者先去把这一步办了",
    );
    expect(posted(calls)).toHaveLength(0);
  });
});

describe("要求写了就要说清是哪种", () => {
  it("每一条都要选必须还是加分，并按这个编码送出去", async () => {
    const calls = mockApi();
    render(<OpportunityForm />);

    await fillEverything();
    await userEvent.click(screen.getByRole("button", { name: "加一条要求" }));
    await userEvent.type(screen.getByLabelText("第 1 条要求"), "能到东校区");
    await userEvent.click(screen.getByRole("button", { name: "加一条要求" }));
    await userEvent.type(screen.getByLabelText("第 2 条要求"), "拍过一次短片");
    await userEvent.selectOptions(screen.getByLabelText("第 2 条是哪种"), "plus");
    await userEvent.click(screen.getByRole("button", { name: "发出去" }));

    await waitFor(() => expect(posted(calls)).toHaveLength(1));
    expect(posted(calls)[0]?.body).toMatchObject({
      qualifications: ["必须：能到东校区", "加分：拍过一次短片"],
    });
  });

  it("空着的那一条会被拦住，不会悄悄送出去", async () => {
    mockApi();
    render(<OpportunityForm />);

    await fillEverything();
    await userEvent.click(screen.getByRole("button", { name: "加一条要求" }));
    await userEvent.click(screen.getByRole("button", { name: "发出去" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("有一条要求是空的");
  });
});

describe("发出去之前先看一眼", () => {
  it("预览就是学生那一屏的同一张卡", async () => {
    mockApi();
    render(<OpportunityForm />);

    await fillEverything();
    await userEvent.click(screen.getByRole("button", { name: "看看学生会看到什么" }));

    const preview = within(
      screen.getByRole("article", { name: "校园流浪猫 60 秒短片" }),
    );
    expect(preview.getByText("剪辑")).toBeVisible();
    expect(preview.getByText("还缺 2 个")).toBeVisible();
    expect(preview.getByText("这件事由 陈牧 负责，有问题找他。")).toBeVisible();
    expect(preview.getByLabelText("校园核过这个组织")).toBeVisible();
  });

  it("预览里能看出还没写负责人会长什么样", async () => {
    mockApi();
    render(<OpportunityForm />);

    await fillEverything();
    await userEvent.clear(screen.getByLabelText("谁负责这件事"));
    await userEvent.click(screen.getByRole("button", { name: "看看学生会看到什么" }));

    expect(
      within(screen.getByRole("article", { name: "校园流浪猫 60 秒短片" })).getByText(
        /没写谁负责/,
      ),
    ).toBeVisible();
  });
});

describe("五态", () => {
  it("首次：空白表单，一行角色，四样必填说在最前面", async () => {
    mockApi();
    render(<OpportunityForm />);

    expect(await screen.findByLabelText("这件事叫什么")).toHaveValue("");
    expect(screen.getByText(/这四样缺一样，学生就判断不出自己能不能来/)).toBeVisible();
    expect(screen.getByLabelText("第 1 个角色")).toHaveValue("");
    expect(screen.queryByLabelText("第 2 个角色")).toBeNull();
  });

  it("加载：给骨架，不是一片空白", () => {
    mockApi({ hang: true });
    render(<OpportunityForm />);

    expect(screen.getByLabelText("加载中")).toBeVisible();
  });

  it("空：没有能招人的组织时，说清要先办哪一步", async () => {
    mockApi({ list: [] });
    render(<OpportunityForm />);

    expect(await screen.findByText("还没有哪个组织能在这里招人。")).toBeVisible();
    expect(screen.getByText(/校园那边要先核过/)).toBeVisible();
    expect(screen.getByRole("link", { name: "先看看别人在招什么" })).toHaveAttribute(
      "href",
      "/opportunities",
    );
  });

  it("错误：发不出去时说人话，填的东西一个都不丢", async () => {
    mockApi({ createStatus: 403 });
    render(<OpportunityForm />);

    await fillEverything();
    await userEvent.click(screen.getByRole("button", { name: "发出去" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "这个组织还没被校园核过，不能在这里招人。",
    );
    expect(screen.getByLabelText("这件事叫什么")).toHaveValue("校园流浪猫 60 秒短片");
    expect(screen.getByLabelText("第 1 个角色")).toHaveValue("剪辑");
  });

  it("降级：调不出类别时，别的照常填、照常预览，只有这一栏空着", async () => {
    mockApi({ kindsStatus: 503 });
    render(<OpportunityForm />);

    expect(await screen.findByText(/现在调不出可以选的类别/)).toBeVisible();
    expect(screen.queryByLabelText("这是件什么事")).toBeNull();

    await userEvent.type(screen.getByLabelText("这件事叫什么"), "先填着的一件事");
    await userEvent.click(screen.getByRole("button", { name: "看看学生会看到什么" }));
    expect(screen.getByRole("article", { name: "先填着的一件事" })).toBeVisible();

    // 拦住的时候仍然说清缺的是哪一样。
    await userEvent.click(screen.getByRole("button", { name: "发出去" }));
    expect(await screen.findByRole("alert", { name: "还差什么" })).toHaveTextContent(
      "还没选这是件什么事",
    );
  });

  it("错误：调不出可选组织时说清这一步跳不过去", async () => {
    mockApi({ listStatus: 500 });
    render(<OpportunityForm />);

    expect(await screen.findByRole("alert")).toHaveTextContent("调不出你能代表哪个组织发");
    expect(screen.getByRole("button", { name: "再看一次" })).toBeVisible();
  });
});

describe("发出去之后", () => {
  it("发完直接给出学生现在看到的那张卡", async () => {
    mockApi();
    render(<OpportunityForm />);

    await fillEverything();
    await userEvent.click(screen.getByRole("button", { name: "发出去" }));

    expect(await screen.findByRole("heading", { name: "发出去了" })).toBeVisible();
    const card = within(
      await screen.findByRole("article", { name: "校园流浪猫 60 秒短片" }),
    );
    expect(card.getByText("还缺 2 个")).toBeVisible();
    expect(card.getByText("这件事由 陈牧 负责，有问题找他。")).toBeVisible();
    expect(screen.getByRole("button", { name: "再发一份" })).toBeVisible();
  });
});

describe("语言", () => {
  it("这一屏不出现领域词汇", async () => {
    mockApi();
    const { container } = render(<OpportunityForm />);

    await fillEverything();
    await userEvent.click(screen.getByRole("button", { name: "加一条要求" }));
    await userEvent.click(screen.getByRole("button", { name: "看看学生会看到什么" }));
    expectNoDomainWords(container.textContent ?? "");
  });

  it("拦住那一段也不出现领域词汇", async () => {
    mockApi();
    const { container } = render(<OpportunityForm />);

    await screen.findByLabelText("这件事叫什么");
    await userEvent.click(screen.getByRole("button", { name: "发出去" }));
    await screen.findByRole("alert");
    expectNoDomainWords(container.textContent ?? "");
  });

  it("空态和错误态也不出现领域词汇", async () => {
    mockApi({ list: [] });
    const { container } = render(<OpportunityForm />);

    await screen.findByText("还没有哪个组织能在这里招人。");
    expectNoDomainWords(container.textContent ?? "");
  });

  it("后端的英文标识符不会原样露出来", async () => {
    mockApi();
    render(<OpportunityForm />);

    await fillEverything();
    for (const raw of ["creative_work", "kind_key", "organization_id", "steward"]) {
      expect(document.body.textContent ?? "").not.toContain(raw);
    }
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
