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
