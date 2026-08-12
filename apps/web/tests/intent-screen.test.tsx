/**
 * 首屏的产品行为。
 *
 * 断言的是用户能看到什么、能做什么，不是组件内部长什么样——
 * 换掉样式或拆分组件，这些用例都不该改。
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Page from "@/app/page";

const KINDS = [
  {
    key: "creative_work",
    label: "作品创作",
    starter: {
      key: "creative_work",
      title: "作品创作",
      example: "我想做一个关于校园流浪猫的一分钟短片，周五前完成。我会写脚本，但不认识会拍摄和剪辑的人",
      roles: ["策划", "拍摄", "剪辑"],
    },
    risk_tier: "low",
    place_precision: "building",
    agent_reply_policy: "always_disclose",
    matching_window_seconds: 21600,
  },
  {
    key: "study_buddy",
    label: "学习搭子",
    starter: {
      key: "study_buddy",
      title: "学习搭子",
      example: "想找人一起备考六级，每周三晚上在图书馆",
      roles: ["同学"],
    },
    risk_tier: "low",
    place_precision: "building",
    agent_reply_policy: "always_disclose",
    matching_window_seconds: 86400,
  },
];

const COMPILED = {
  content: {
    goal: "周五前完成 60 秒校园流浪猫短片",
    offers: ["写脚本"],
    needs: ["拍摄", "剪辑"],
    time_window: { earliest: "2026-08-12T09:00:00Z", deadline: "2026-08-14T23:59:00Z" },
    location_scope: null,
    team_size: { minimum: 3, maximum: 4 },
    boundaries: [],
    open_questions: ["是否公开发布"],
    uncertain_fields: ["team_size"],
  },
  follow_ups: [],
  conflicts: [],
  confidence: 1.0,
  fall_back_to_form: false,
};

function mockApi(overrides: Record<string, unknown> = {}) {
  const routes: Record<string, unknown> = {
    "/api/action-kinds": KINDS,
    "/api/intents:compile": COMPILED,
    ...overrides,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const key = Object.keys(routes).find((r) => url.startsWith(r));
      return {
        ok: key !== undefined,
        status: key === undefined ? 404 : 200,
        json: async () => routes[key ?? ""] ?? null,
      };
    }),
  );
}

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("首屏", () => {
  it("给的是具体场景，不是一个空输入框", async () => {
    mockApi();
    render(<Page />);

    expect(await screen.findByRole("button", { name: "作品创作" })).toBeVisible();
    expect(screen.getByRole("button", { name: "学习搭子" })).toBeVisible();
  });

  it("输入框的示例是一句完整的话，不是占位符", async () => {
    mockApi();
    render(<Page />);

    const box = await screen.findByLabelText("你想做的事");
    await waitFor(() => {
      const hint = box.getAttribute("placeholder") ?? "";
      expect(hint.length).toBeGreaterThan(10);
      expect(hint).not.toContain("请输入");
    });
  });

  it("场景卡拿不到时仍然能直接说一句话", async () => {
    mockApi({ "/api/action-kinds": undefined });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.startsWith("/api/action-kinds")
          ? { ok: false, status: 500, json: async () => null }
          : { ok: true, status: 200, json: async () => COMPILED },
      ),
    );
    render(<Page />);

    expect(await screen.findByLabelText("你想做的事")).toBeVisible();
  });
});

describe("整理出来的卡片", () => {
  it("点场景卡就直接整理出一张可改的卡", async () => {
    mockApi();
    render(<Page />);

    await userEvent.click(await screen.findByRole("button", { name: "作品创作" }));

    expect(await screen.findByDisplayValue("周五前完成 60 秒校园流浪猫短片")).toBeVisible();
    expect(screen.getByDisplayValue("拍摄、剪辑")).toBeVisible();
  });

  it("系统猜的字段会被标出来，不会默默当成事实", async () => {
    mockApi();
    render(<Page />);

    await userEvent.click(await screen.findByRole("button", { name: "作品创作" }));

    expect(await screen.findByText("我猜的")).toBeVisible();
  });

  it("待定的事会单独列出来给真人决定", async () => {
    mockApi();
    render(<Page />);

    await userEvent.click(await screen.findByRole("button", { name: "作品创作" }));

    expect(await screen.findByText(/是否公开发布/)).toBeVisible();
  });

  it("读不懂时明说是猜的，并让人直接改", async () => {
    mockApi({
      "/api/intents:compile": {
        ...COMPILED,
        confidence: 0.25,
        fall_back_to_form: true,
      },
    });
    render(<Page />);

    await userEvent.click(await screen.findByRole("button", { name: "作品创作" }));

    expect(await screen.findByText(/没太读懂/)).toBeVisible();
  });

  it("有两个出口：开始找人，或者先记着", async () => {
    mockApi();
    render(<Page />);

    await userEvent.click(await screen.findByRole("button", { name: "作品创作" }));

    expect(await screen.findByRole("button", { name: "就这样，开始找人" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "还没想好，先记着" })).toBeEnabled();
  });

  it("界面上不出现领域词汇", async () => {
    mockApi();
    const { container } = render(<Page />);

    await userEvent.click(await screen.findByRole("button", { name: "作品创作" }));

    const text = container.textContent ?? "";
    for (const term of [
      "意图信号",
      "匹配信封",
      "成局提案",
      "成局证明",
      "记忆切面",
      "同意凭证",
      "场域智能体",
      "稳定性检查",
    ]) {
      expect(text).not.toContain(term);
    }
  });
});

describe("追问要能答", () => {
  it("点一个选项就把它填进卡里，不用再打一遍字", async () => {
    // 原先选项是印出来的说明文字——用户读得到，答不了。
    // 一个答不了的追问比不问更糟：它明说了系统知道自己缺什么，然后什么也不做。
    mockApi({
      "/api/intents:compile": {
        ...COMPILED,
        content: {
          ...COMPILED.content,
          team_size: null,
          uncertain_fields: ["team_size"],
        },
        follow_ups: [
          {
            text: "希望找几个人？",
            narrows: "team_size",
            options: [
              { label: "就两个人", value: "2-2" },
              { label: "三四个", value: "3-4" },
            ],
          },
        ],
      },
    });
    render(<Page />);
    await userEvent.type(screen.getByLabelText("你想做的事"), "想找人一起做点事");
    await userEvent.click(screen.getByRole("button", { name: "整理一下" }));

    await userEvent.click(await screen.findByRole("button", { name: "三四个" }));

    expect(screen.getByText("3–4 人")).toBeVisible();
    // 答过的不再问：还挂在那儿，用户会以为自己没点上。
    expect(screen.queryByText("希望找几个人？")).toBeNull();
  });
});

describe("这条给谁看见", () => {
  /** 一个人的"熟人"由**共同做过的事**定义，所以它是从 `/me/events` 推出来的，
   *  不是一个可以随手填的字段。这里给它一份真实形状的回答。 */
  function withEvents(events: unknown[]) {
    return {
      "/api/me/events": events,
    };
  }

  it("一件事都没做成过的人，在他选之前就知道那一档现在问不到人", async () => {
    // 这一条是这个功能最容易出错的地方：范围收窄本身没坏，坏的是让人
    // 选完、等一轮、再看见一屏"没找到"——那时候他会以为是产品没人用。
    mockApi(withEvents([]));
    render(<Page />);

    await userEvent.click(await screen.findByRole("button", { name: "作品创作" }));

    expect(
      await screen.findByText(/你还没和谁一起做成过事/),
    ).toBeVisible();
  });

  it("一起做过事的人，那一档说的是另一句话", async () => {
    mockApi(
      withEvents([
        {
          event_id: "11111111-1111-4111-8111-111111111111",
          title: "拍流浪猫",
          goal: "拍流浪猫",
          state: "completed",
          formed_at: "2026-07-01T00:00:00Z",
          left_at: null,
          with_others: ["林知遥"],
          counts_as_done: true,
          growth: "bloom",
        },
      ]),
    );
    render(<Page />);

    await userEvent.click(await screen.findByRole("button", { name: "作品创作" }));

    expect(await screen.findByText(/这一档只问他们/)).toBeVisible();
  });

  it("默认是全校——冷启动时缩小范围等于没有匹配", async () => {
    mockApi(withEvents([]));
    render(<Page />);

    await userEvent.click(await screen.findByRole("button", { name: "作品创作" }));

    expect(await screen.findByRole("radio", { name: /全校都能看到/ })).toBeChecked();
  });

  it("选了哪一档，发出去的那条就带哪一档", async () => {
    // 屏上选了、请求里没带，是这一类功能最常见的假完成：界面看着对，
    // 而撮合那一侧收到的仍然是默认值。
    const calls: Array<[string, RequestInit | undefined]> = [];
    mockApi(withEvents([]));
    const real = global.fetch as unknown as (u: string, i?: RequestInit) => Promise<Response>;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push([url, init]);
        // **`/api/intents:compile` 也是 POST `/api/intents…` 开头**——
        // 用 startsWith 会把整理那一步一起拦掉，卡片根本不会出现。
        if (url === "/api/intents" && init?.method === "POST") {
          return {
            ok: true,
            status: 200,
            json: async () => ({ id: "22222222-2222-4222-8222-222222222222" }),
          } as unknown as Response;
        }
        return real(url, init);
      }),
    );
    render(<Page />);

    await userEvent.click(await screen.findByRole("button", { name: "作品创作" }));
    await userEvent.click(
      await screen.findByRole("radio", { name: /只问一起做过事的人/ }),
    );
    await userEvent.click(screen.getByRole("button", { name: "就这样，开始找人" }));

    await waitFor(() => {
      const created = calls.find(
        ([u, i]) => u === "/api/intents" && i?.method === "POST",
      );
      expect(created).toBeDefined();
      expect(JSON.parse(String(created?.[1]?.body)).reach).toBe("known");
    });
  });
});

describe("认得这个人", () => {
  it("填过名字的人，首页叫得出他的名字", async () => {
    // 上一屏刚让他填了名字。这一屏不认得他的话，那一步会显得
    // 像一道没有用的手续——而它其实决定了队友在群里看到的是谁。
    mockApi({
      "/api/me/profile": { display_name: "周叙", named_self: true, skills: [] },
    });
    render(<Page />);

    expect(
      await screen.findByRole("heading", { name: "周叙，想做点什么？" }),
    ).toBeVisible();
  });

  it("名字调不出来时照常能用，只是不叫名字", async () => {
    mockApi();
    render(<Page />);

    expect(await screen.findByRole("heading", { name: "想做点什么？" })).toBeVisible();
  });
});
