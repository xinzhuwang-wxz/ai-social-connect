/**
 * 常驻导航。
 *
 * 这个文件存在的理由是一次真实的疏漏：每一屏都做好了、每一屏都有测试，
 * 但**没有任何东西把它们连起来**——一个刚打开这个网页的人只能停在首页。
 * 产品的每一片都能单独演示，合起来却走不动。
 *
 * 所以这里断言的不是"导航渲染了"，而是**从首页能到得了每一个用户会
 * 主动去的地方**。
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SiteNav } from "@/components/site-nav";

let here = "/";
let waiting = 0;
vi.mock("next/navigation", () => ({ usePathname: () => here }));
vi.mock("@/lib/inbox", () => ({ pendingInvitations: async () => waiting }));

describe("常驻导航", () => {
  beforeEach(() => {
    here = "/";
    waiting = 0;
  });

  it("从任何一页都到得了四个主要去处", () => {
    render(<SiteNav />);
    for (const label of ["说一件事", "等配队", "有哪些招募", "我的记录"]) {
      expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    }
  });

  it("每个入口都真的指向一个页面，不是空链接", () => {
    render(<SiteNav />);
    for (const [label, href] of [
      ["说一件事", "/"],
      ["等配队", "/waiting"],
      ["有哪些招募", "/opportunities"],
      ["我的记录", "/me"],
    ] as const) {
      expect(screen.getByRole("link", { name: label })).toHaveAttribute(
        "href",
        href,
      );
    }
  });

  it("说得出「我现在在哪」", () => {
    here = "/waiting";
    render(<SiteNav />);

    expect(screen.getByRole("link", { name: "等配队" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    // 首页只在完全相等时高亮：否则它在每一页上都亮着，
    // 等于没有"我现在在哪"这个信息。
    expect(screen.getByRole("link", { name: "说一件事" })).not.toHaveAttribute(
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

  it("有人在等你答复时，那一条出现在最显眼的位置", async () => {
    // 这是「被邀请的那一侧」唯一的入口。没有它，被邀请的人不知道有这回事，
    // 那一整屏等于不存在——他只能自己想起来去翻，而没人会。
    waiting = 2;
    render(<SiteNav />);

    const entry = await screen.findByRole("link", { name: /2 件事等你答复/ });
    expect(entry).toHaveAttribute("href", "/invitations");
  });

  it("没人等的时候不显示它", async () => {
    // 常驻一个「0」比不显示更差：它每天提醒你这里什么都没有。
    render(<SiteNav />);
    await screen.findByRole("link", { name: "说一件事" });

    expect(screen.queryByText(/件事等你答复/)).toBeNull();
  });

  it("入口不超过四个", () => {
    render(<SiteNav />);
    // 导航栏的长度是一种判断：每多一项，前面那些就少被看见一点。
    // 十个页面里只有四个是用户会主动去的地方，其余都是从这四个里走进去的。
    const links = screen.getAllByRole("link");
    expect(links.length).toBeLessThanOrEqual(5); // 四个去处 + 一个品牌位
  });
});
