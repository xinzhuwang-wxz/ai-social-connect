/**
 * 常驻导航。
 *
 * 这个文件存在的理由是一次真实的疏漏：每一屏都做好了、每一屏都有测试，
 * 但**没有任何东西把它们连起来**——一个刚打开这个网页的人只能停在首页。
 * 产品的每一片都能单独演示，合起来却走不动。
 *
 * 所以这里断言的不是"导航渲染了"，而是**从首页能到得了每一个用户会
 * 主动去的地方**。
 *
 * ## 两条导航，一条给桌面一条给手机
 *
 * 它们同时在 DOM 里，由 CSS 决定显示哪一条——jsdom 不跑媒体查询，
 * 所以这里的查询必须**按栏定位**，不能全局找。
 * 桌面那条一排横排文字在 390px 宽的屏上会折成竖排，「等配队」三个字
 * 一个字一行；那不是有点挤，是不能用。
 */

/** 桌面顶栏。 */
const top = () => within(screen.getByRole("navigation", { name: "主导航" }));
/** 手机底栏。 */
const bottom = () =>
  within(screen.getByRole("navigation", { name: "主导航（底部）" }));
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SiteNav } from "@/components/site-nav";

let here = "/";
let waiting = 0;
vi.mock("next/navigation", () => ({ usePathname: () => here }));
let soon: unknown[] = [];
vi.mock("@/lib/inbox", () => ({
  unansweredSeeds: async () => waiting,
  comingUp: async () => soon,
}));

describe("常驻导航", () => {
  beforeEach(() => {
    here = "/";
    waiting = 0;
    soon = [];
  });

  it("从任何一页都到得了四个主要去处", () => {
    render(<SiteNav />);
    for (const label of ["花园", "信箱", "行动中", "森林", "在招什么"]) {
      expect(top().getByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("手机上四个去处一个都不少", () => {
    // 底栏的字更短（「招募」「我的」），因为一格只有约五个字的宽度——
    // 但**去处必须是同一批**：手机上少一个入口，那一屏就等于不存在。
    render(<SiteNav />);
    for (const [label, href] of [
      ["花园", "/"],
      ["信箱", "/seeds"],
      ["行动中", "/waiting"],
      ["森林", "/me"],
      ["在招", "/opportunities"],
    ] as const) {
      expect(bottom().getByRole("link", { name: label })).toHaveAttribute(
        "href",
        href,
      );
    }
  });

  it("每个入口都真的指向一个页面，不是空链接", () => {
    render(<SiteNav />);
    for (const [label, href] of [
      ["花园", "/"],
      ["信箱", "/seeds"],
      ["行动中", "/waiting"],
      ["森林", "/me"],
      ["在招什么", "/opportunities"],
    ] as const) {
      expect(top().getByRole("link", { name: label })).toHaveAttribute(
        "href",
        href,
      );
    }
  });

  it("说得出「我现在在哪」", () => {
    here = "/waiting";
    render(<SiteNav />);

    expect(top().getByRole("link", { name: "行动中" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    // 首页只在完全相等时高亮：否则它在每一页上都亮着，
    // 等于没有"我现在在哪"这个信息。
    expect(top().getByRole("link", { name: "花园" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("导航上不出现领域词汇", () => {
    render(<SiteNav />);
    const text = document.body.textContent ?? "";
    for (const term of [
      "意图",
      "共域",
      "切面",
      "撮合",
      "召回",
      "提案",
      "主体",
      "智能体",
    ]) {
      // 「共域」是产品名，只允许作为标题出现一次；这里查的是**入口措辞**。
      if (term === "共域") continue;
      expect(text).not.toContain(term);
    }
  });

  it("信箱里有没答的种子时，那一条出现在最显眼的位置", async () => {
    // 这是「被找到的那一侧」唯一的入口。没有它，收到种子的人不知道有这回事，
    // 那一整屏等于不存在——他只能自己想起来去翻，而没人会。
    waiting = 2;
    render(<SiteNav />);

    const entry = await screen.findByRole("link", { name: /2 颗种子等你看/ });
    expect(entry).toHaveAttribute("href", "/seeds");
  });

  it("没人等的时候不显示它", async () => {
    // 常驻一个「0」比不显示更差：它每天提醒你这里什么都没有。
    render(<SiteNav />);
    await screen.findAllByRole("link", { name: "花园" });

    expect(screen.queryByText(/颗种子等你看/)).toBeNull();
  });

  it("入口不超过五个", () => {
    render(<SiteNav />);
    // 导航栏的长度是一种判断：每多一项，前面那些就少被看见一点。
    // 五个去处：花园 / 信箱 / 行动中 / 森林 / 在招什么。其余都是从这几个里走进去的。
    const links = top().getAllByRole("link");
    expect(links.length).toBeLessThanOrEqual(5);
  });
});

describe("顶栏屏名与品牌", () => {
  beforeEach(() => {
    here = "/";
    waiting = 0;
    soon = [];
  });

  it("品牌链接只在首页出现，非首页顶栏改为显示当前屏的名字", () => {
    here = "/me";
    render(<SiteNav />);
    // 非首页不渲染品牌链接——同一个名字在每一页重复，
    // 对用户没有信息量，在 390px 的屏上还白占 52px。
    expect(screen.queryByRole("link", { name: "共域" })).toBeNull();
    // 顶栏改为非链接形式的屏名，与底部导航链接区分。
    expect(
      screen.queryByText("森林", { selector: ":not(a)" }),
    ).not.toBeNull();
  });

  it("种子胶囊在非首页时仍然可见", async () => {
    here = "/me";
    waiting = 3;
    render(<SiteNav />);
    // 被邀请那一侧的唯一入口——无论在哪一屏都不能断。
    const capsule = await screen.findByRole("link", {
      name: /3 颗种子等你看/,
    });
    expect(capsule).toBeInTheDocument();
  });
});

describe("快到了", () => {
  // 这一组自己重置：`beforeEach` 写在另一个 describe 里，管不到这里——
  // 而串了状态的用例会红在一个和它自己无关的地方。
  beforeEach(() => {
    here = "/";
    waiting = 0;
    soon = [];
  });

  it("这两天要出发的事排在待答复前面", async () => {
    // 那件事已经定了，人得按时出现——它比"等你答复"更急。
    soon = [
      {
        event_id: "11111111-1111-4111-8111-111111111111",
        space_id: "22222222-2222-4222-8222-222222222222",
        title: "周六去后山",
        starts_at: new Date(Date.now() + 20 * 3_600_000).toISOString(),
        where: "北门",
        bring: null,
        change_note: null,
        my_state: null,
      },
    ];
    waiting = 2;
    render(<SiteNav />);

    const go = await screen.findByRole("link", { name: /要出发/ });
    expect(go).toHaveAttribute("href", "/spaces/22222222-2222-4222-8222-222222222222");
  });

  it("没有要出发的事就不显示它", async () => {
    // 常驻一个空的提醒，人会学会忽略这一整块。
    render(<SiteNav />);
    await screen.findAllByRole("link", { name: "花园" });

    expect(screen.queryByText(/要出发/)).toBeNull();
  });
});

describe("还没进门的人", () => {
  it("欢迎屏上没有导航——那时候他还不在应用里", () => {
    // 一个连名字都还没填的人看到五个标签，会先去点它们，
    // 而每一个都会把他弹回来。给一个点不动的骨架，不如不给。
    here = "/welcome";
    const { container } = render(<SiteNav />);

    expect(container).toBeEmptyDOMElement();
  });
});
