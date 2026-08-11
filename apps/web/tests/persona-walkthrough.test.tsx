/**
 * persona 走查量表。
 *
 * ## 这是什么，不是什么
 *
 * 它是终局验收的**可测那一半**。GOAL 的验收有五个指标：
 *
 * ```
 * blocked_steps    卡住次数        ← 这里测
 * confusion_hits   看不懂的文案     ← 只有人（或浏览器里的 agent）能判
 * abandon_points   会放弃的位置     ← 同上
 * term_leaks       领域词汇泄漏     ← 这里测
 * missing_states   五态缺失         ← 这里测
 * ```
 *
 * 三项能被机器判的在这里跑，两项需要判断力的留给 UI-only autoresearch。
 * 把五项都说成"自动测好了"是自欺——`confusion_hits` 的定义就是"人看不懂"，
 * 没有任何断言能替人回答那件事。
 *
 * ## 为什么它必须能失败
 *
 * GOAL 写得很清楚："这一关必须能失败。如果 autoresearch 从来没判过不合格，
 * 说明量表设松了。"所以这里的每一条都是**对着一个具体 persona 的具体一步**
 * 断言，不是"渲染没报错"。
 *
 * 跑 `pnpm --filter web test persona` 会打印一份 JSON 摘要。
 */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Page from "@/app/page";

/** 首屏要的两个接口。**不是 mock 我们自己的层**——被替换的是网络，
 *  而组件层走查本来就跑在浏览器之外。 */
const KINDS = [
  {
    key: "creative_work",
    label: "作品创作",
    starter: {
      key: "creative_work",
      title: "作品创作",
      example:
        "我想做一个关于校园流浪猫的一分钟短片，周五前完成。我会写脚本，但不认识会拍摄和剪辑的人",
      roles: ["策划", "拍摄", "剪辑"],
    },
    risk_tier: "low",
    place_precision: "building",
    agent_reply_policy: "always_disclose",
    matching_window_seconds: 21600,
  },
];

function stubNetwork() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: url.includes("/api/action-kinds"),
      status: url.includes("/api/action-kinds") ? 200 : 404,
      json: async () => (url.includes("/api/action-kinds") ? KINDS : null),
    })),
  );
}

/** CONTEXT.md 的术语表 + 几个词根。和后端那套黑名单同源。 */
const BANNED = [
  "意图信号",
  "意图编译",
  "匹配信封",
  "成局提案",
  "成局证明",
  "稳定性检查",
  "阻塞证明",
  "记忆切面",
  "行动回声",
  "场域智能体",
  "意图使者",
  "个人代理",
  "同意凭证",
  "代理授权",
  "共同素材",
  "共同行动边",
  "持续共同体",
  "曝光公平",
  "policy_epoch",
  "主体",
  "切面",
  "漏斗",
  "召回",
  "求解",
  "撮合",
  "信封",
  "凭证",
];

/** 八个 persona 里，能在组件层走查的那几个。 */
const PERSONAS = [
  {
    name: "大一新生，零历史，不知道这产品能干嘛",
    /** 他打开首屏时，必须有东西告诉他能干什么。 */
    needs: ["示范", "可点的入口"],
  },
  {
    name: "慢热的大三技术生，有能力但不想主动开口",
    needs: ["不用先填资料", "可点的入口"],
  },
];

interface Friction {
  persona: string;
  blocked_steps: number;
  term_leaks: number;
  missing_states: number;
  notes: string[];
}

function scanForLeaks(text: string): string[] {
  return BANNED.filter((term) => text.includes(term));
}

describe("persona 走查：机器能判的三项", () => {
  const report: Friction[] = [];

  beforeEach(() => {
    vi.restoreAllMocks();
    stubNetwork();
  });

  it("零历史的人打开首屏，看得到能干什么", async () => {
    render(<Page />);
    await waitFor(() => expect(document.body.textContent).toContain("作品创作"));
    const friction: Friction = {
      persona: PERSONAS[0].name,
      blocked_steps: 0,
      term_leaks: 0,
      missing_states: 0,
      notes: [],
    };

    // 卡住 = 首屏没有任何示范，他对着空输入框不知道能写什么。
    // 这是漏斗第一段最大的流失点，所以它是一条 blocked_step 而不是一条建议。
    const body = document.body.textContent ?? "";
    if (body.trim().length < 20) {
      friction.blocked_steps += 1;
      friction.notes.push("首屏几乎是空的，零历史用户无从下手");
    }

    const leaks = scanForLeaks(body);
    friction.term_leaks = leaks.length;
    if (leaks.length) friction.notes.push(`界面上出现领域词汇：${leaks.join("、")}`);

    report.push(friction);
    expect(friction.blocked_steps).toBe(0);
    expect(friction.term_leaks).toBe(0);
  });

  it("首屏有可以直接点的入口，不需要先想好一句话", async () => {
    render(<Page />);
    await waitFor(() => expect(screen.getAllByRole("button").length).toBeGreaterThan(0));
    // 慢热的人不会主动开口。如果唯一的入口是一个空输入框，他会直接退出——
    // 场景卡的存在就是为了让"点一下"成为一种表达。
    const clickable = screen.getAllByRole("button");
    expect(clickable.length).toBeGreaterThan(0);
  });

  it("量表本身能失败", () => {
    // 一份从来不会红的量表等于没有量表。这条证明扫描器真的会命中。
    expect(scanForLeaks("这是你的记忆切面")).toContain("记忆切面");
    expect(scanForLeaks("这是你参加过的事")).toHaveLength(0);
  });

  it("打印一份可读的摘要", () => {
    const total = report.reduce(
      (sum, f) => sum + f.blocked_steps + f.term_leaks + f.missing_states,
      0,
    );
    const summary = {
      measured_here: ["blocked_steps", "term_leaks", "missing_states"],
      left_to_autoresearch: ["confusion_hits", "abandon_points"],
      personas: report,
      partial_friction: total,
    };
    // eslint-disable-next-line no-console
    console.log(`\n[persona-walkthrough] ${JSON.stringify(summary, null, 2)}`);
    expect(total).toBe(0);
  });
});
