/**
 * 「这次你会得到什么」的产品行为：被邀请的那一侧。
 *
 * 断言的是用户看到什么、能做什么，不是组件内部长什么样。这一屏最容易做错的
 * 两件事各有一组断言盯着：**先说代价**（顺序），和**把拒绝做成一件麻烦事**
 * （零负担）。
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InvitationScreen, InvitationsScreen } from "@/components/invitation-screen";
import type { Invitation } from "@/lib/invitations";

const PROPOSAL = "22222222-2222-4222-8222-222222222222";
const OTHER = "99999999-9999-4999-8999-999999999999";
const EVENT = "66666666-6666-4666-8666-666666666666";
const ME = "33333333-3333-4333-8333-333333333333";
const SU = "44444444-4444-4444-8444-444444444444";
const CHEN = "55555555-5555-4555-8555-555555555555";

const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString();

const GET_ONE = "一起做成「周五前完成 60 秒校园流浪猫短片」，这件事会留在你的记录里";
const GET_TWO = "同队的人会「拍摄、剪辑」，你不用自己扛";
const GIVE_ONE = "你的「写脚本」";

const INVITATION: Invitation = {
  proposal_id: PROPOSAL,
  about: "周五前完成 60 秒校园流浪猫短片",
  with_others: ["苏晚", "陈牧"],
  i_get: [GET_ONE, GET_TWO],
  i_give: [GIVE_ONE],
  time_cost: "两个晚上，加周六下午",
  my_answer: "pending",
  answer_by: inHours(30),
};

const SECOND: Invitation = {
  ...INVITATION,
  proposal_id: OTHER,
  about: "办一场院系摄影展",
  i_get: ["一起做成「办一场院系摄影展」，这件事会留在你的记录里"],
  i_give: ["你的「策展」"],
  time_cost: null,
};

const WAITING_ON_ME = { verdict: "waiting", waiting_on: [ME, SU, CHEN], conditions: [] };

type Call = { url: string; method: string; body: unknown };

type Options = {
  ids?: string[];
  invitations?: Invitation[];
  status?: Record<string, unknown>;
  afterDecide?: Record<string, unknown>;
  idsStatus?: number;
  invitationStatus?: number;
  statusStatus?: number;
  decideStatus?: number;
  /** 只有这几个 id 取得出来，其余的坏掉。用来验证一条坏的不挡住其余的。 */
  onlyReadable?: string[];
  hang?: boolean;
};

function mockApi(opts: Options = {}): Call[] {
  const calls: Call[] = [];
  const all = opts.invitations ?? [INVITATION];
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

      if (url === "/api/me/proposals") {
        return opts.idsStatus
          ? reply({ detail: "没连上" }, opts.idsStatus)
          : reply(opts.ids ?? all.map((one) => one.proposal_id));
      }

      const asked = url.match(/\/api\/proposals\/(.+)\/invitation$/);
      if (asked) {
        if (opts.invitationStatus) {
          return reply({ detail: "找不到这个邀请" }, opts.invitationStatus);
        }
        if (opts.onlyReadable && !opts.onlyReadable.includes(asked[1]!)) {
          return reply({ detail: "没连上" }, 503);
        }
        const one = all.find((row) => row.proposal_id === asked[1]);
        return one ? reply(one) : reply({ detail: "找不到这个邀请" }, 404);
      }

      if (url.endsWith("/status")) {
        return opts.statusStatus
          ? reply({ detail: "没连上" }, opts.statusStatus)
          : reply(opts.status ?? WAITING_ON_ME);
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
      return reply(null, 404);
    }),
  );
  return calls;
}

const card = () => screen.getByRole("region", { name: INVITATION.about });
const decides = (calls: Call[]) => calls.filter((c) => c.url.endsWith(":decide"));
const lastDecide = (calls: Call[]) => decides(calls).at(-1)?.body;

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.localStorage.setItem("cofield.principal", ME);
});

describe("这次你会得到什么", () => {
  it("主语是我：先说我会得到什么，再说我要出什么", async () => {
    mockApi();
    const { container } = render(<InvitationScreen proposalId={PROPOSAL} />);

    expect(await screen.findByText(GET_ONE)).toBeVisible();
    expect(screen.getByText(GIVE_ONE)).toBeVisible();

    // 顺序不是排版偏好：先说代价的邀请没人会读完。
    const text = container.textContent ?? "";
    expect(text.indexOf("你会得到")).toBeLessThan(text.indexOf("你要出的"));
    expect(text.indexOf(GET_ONE)).toBeLessThan(text.indexOf(GIVE_ONE));
  });

  it("不写「你被选中了」，也不写谁挑了谁", async () => {
    mockApi();
    render(<InvitationScreen proposalId={PROPOSAL} />);

    await screen.findByText(GET_ONE);
    const text = document.body.textContent ?? "";
    for (const wrong of ["被选中", "被推荐", "挑中", "候选人", "入选"]) {
      expect(text).not.toContain(wrong);
    }
  });

  it("说清和谁一起、大概要花多少时间、到什么时候要答复", async () => {
    mockApi();
    render(<InvitationScreen proposalId={PROPOSAL} />);

    const one = within(await screen.findByRole("region", { name: INVITATION.about }));
    expect(one.getByText("和苏晚、陈牧一起")).toBeVisible();
    expect(one.getByText("大概要花：两个晚上，加周六下午")).toBeVisible();
    expect(one.getByText(/之前答复。过了这个点就不留着了/)).toBeVisible();
  });

  it("说不清要花多少时间就不说，不编一个数", async () => {
    mockApi({ ids: [OTHER], invitations: [SECOND] });
    render(<InvitationScreen proposalId={OTHER} />);

    await screen.findByRole("region", { name: SECOND.about });
    expect(screen.queryByText(/大概要花/)).toBeNull();
  });
});

describe("三个动作", () => {
  it("我加入之后，说清还差几个人", async () => {
    const calls = mockApi();
    render(<InvitationScreen proposalId={PROPOSAL} />);

    await userEvent.click(await screen.findByRole("button", { name: "我加入" }));

    await waitFor(() => {
      expect(within(card()).getByText("还差 2 个人点头。")).toBeVisible();
    });
    expect(decides(calls)).toHaveLength(1);
    expect(lastDecide(calls)).toEqual({ answer: "accepted", condition: null });
  });

  it("拒绝是一步完成的：不二次确认、不问理由", async () => {
    const calls = mockApi();
    render(<InvitationScreen proposalId={PROPOSAL} />);

    await userEvent.click(await screen.findByRole("button", { name: "我不参加" }));

    expect(await screen.findByText("知道了。这次就到这里。")).toBeVisible();
    expect(decides(calls)).toHaveLength(1);
    expect(lastDecide(calls)).toEqual({ answer: "declined", condition: null });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(
      screen.queryByRole("button", { name: /确定|确认|再想想|为什么|取消/ }),
    ).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("拒绝和加入摆在一起、同等重量，不做成灰色小字", async () => {
    mockApi();
    render(<InvitationScreen proposalId={PROPOSAL} />);

    const join = await screen.findByRole("button", { name: "我加入" });
    const no = screen.getByRole("button", { name: "我不参加" });
    expect(join.parentElement).toBe(no.parentElement);
    expect(no).toBeEnabled();
  });

  it("「我可以，但……」写不清就发不出去，写清了原样带过去", async () => {
    const calls = mockApi({
      afterDecide: { verdict: "needs_revision", waiting_on: [], conditions: ["周四我要上课"] },
    });
    render(<InvitationScreen proposalId={PROPOSAL} />);

    await userEvent.click(await screen.findByRole("button", { name: "我可以，但……" }));
    // 空条件不给发：对方无从回应的条件等于一次没人看得懂的沉默。
    expect(screen.getByRole("button", { name: "就这么说" })).toBeDisabled();

    await userEvent.type(
      screen.getByLabelText("你的条件是什么？"),
      "周四我要上课，换成周三我就来",
    );
    await userEvent.click(screen.getByRole("button", { name: "就这么说" }));

    await waitFor(() => {
      expect(lastDecide(calls)).toEqual({
        answer: "conditional",
        condition: "周四我要上课，换成周三我就来",
      });
    });
    expect(await screen.findByText(/要改一版，改好会再来问你一次/)).toBeVisible();
  });

  it("都点头之后，给一条通往「这次留下了什么」的路", async () => {
    mockApi({
      afterDecide: { verdict: "open", waiting_on: [], conditions: [], formed_event_id: EVENT },
    });
    render(<InvitationScreen proposalId={PROPOSAL} />);

    await userEvent.click(await screen.findByRole("button", { name: "我加入" }));

    expect(await screen.findByText("都点头了，这件事成了。")).toBeVisible();
    expect(
      screen.getByRole("link", { name: "去看这次留下了什么" }),
    ).toHaveAttribute("href", `/events/${EVENT}/echo`);
  });

  it("已经答过的人不再被问第二次", async () => {
    mockApi({ status: { verdict: "waiting", waiting_on: [SU, CHEN], conditions: [] } });
    render(<InvitationScreen proposalId={PROPOSAL} />);

    expect(await screen.findByText("还差 2 个人点头。")).toBeVisible();
    expect(screen.queryByRole("button", { name: "我加入" })).toBeNull();
    expect(screen.queryByRole("button", { name: "我不参加" })).toBeNull();
  });
});

describe("五态", () => {
  it("首次：说清有几件事在等你，以及先看得到什么再决定", async () => {
    mockApi();
    render(<InvitationsScreen />);

    expect(
      await screen.findByText(/有 1 件事在等你答复。先看这次你会得到什么，再决定去不去。/),
    ).toBeVisible();
  });

  it("加载：给骨架，不是一片空白", () => {
    mockApi({ hang: true });
    render(<InvitationsScreen />);

    expect(screen.getByLabelText("加载中")).toBeVisible();
  });

  it("空：说一句有用的话，加一个能点的入口", async () => {
    mockApi({ ids: [] });
    render(<InvitationsScreen />);

    expect(await screen.findByText("现在没有人在等你答复。")).toBeVisible();
    expect(screen.getByText(/不去也不用解释/)).toBeVisible();
    expect(screen.getByRole("link", { name: "说说想做点什么" })).toHaveAttribute(
      "href",
      "/",
    );
  });

  it("错误：说清哪里断了，并说明没替你答复任何人", async () => {
    mockApi({ idsStatus: 500 });
    render(<InvitationsScreen />);

    expect(await screen.findByRole("alert")).toHaveTextContent("调不出等你答复的事");
    expect(screen.getByText(/不会替你答复任何人/)).toBeVisible();
    expect(screen.getByRole("button", { name: "再试一次" })).toBeVisible();
  });

  it("降级：看不到还在等谁时照样能答复，并且明说看不到", async () => {
    mockApi({ statusStatus: 503 });
    render(<InvitationScreen proposalId={PROPOSAL} />);

    expect(await screen.findByText(/现在看不到还有谁没回/)).toBeVisible();
    expect(screen.getByRole("button", { name: "我加入" })).toBeEnabled();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("降级：一条取不出来时，其余几条照常出现", async () => {
    mockApi({ invitations: [INVITATION, SECOND], onlyReadable: [OTHER] });
    render(<InvitationsScreen />);

    expect(await screen.findByRole("region", { name: SECOND.about })).toBeVisible();
    expect(screen.queryByRole("region", { name: INVITATION.about })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("降级：说不清能得到什么时如实说，并且照样能不去", async () => {
    mockApi({ invitations: [{ ...INVITATION, i_get: [], i_give: [] }] });
    render(<InvitationScreen proposalId={PROPOSAL} />);

    expect(
      await screen.findByText("这次没说清你会得到什么。说不清的事你可以不去，不用解释。"),
    ).toBeVisible();
    expect(screen.getByText("这次没有要你专门出什么。")).toBeVisible();
    expect(screen.getByRole("button", { name: "我不参加" })).toBeEnabled();
  });

  it("空：这一件已经不在了的时候，给一条能走的路", async () => {
    mockApi({ invitationStatus: 404 });
    render(<InvitationScreen proposalId={PROPOSAL} />);

    expect(await screen.findByText("这件事已经不在了。")).toBeVisible();
    expect(
      screen.getByRole("link", { name: "看看还有谁在等你" }),
    ).toHaveAttribute("href", "/invitations");
  });
});

describe("语言", () => {
  it("这一屏不出现领域词汇", async () => {
    mockApi();
    const { container } = render(<InvitationsScreen />);

    await screen.findByText(GET_ONE);
    await userEvent.click(screen.getByRole("button", { name: "我可以，但……" }));
    expectNoDomainWords(container.textContent ?? "");
  });

  it("什么都没有的那一屏也不出现领域词汇", async () => {
    mockApi({ ids: [] });
    const { container } = render(<InvitationsScreen />);

    await screen.findByText("现在没有人在等你答复。");
    expectNoDomainWords(container.textContent ?? "");
  });

  it("英文标识符不会原样露出来", async () => {
    mockApi();
    render(<InvitationsScreen />);

    await screen.findByText(GET_ONE);
    for (const raw of ["accepted", "declined", "conditional", "proposal_id", "i_get"]) {
      expect(document.body.textContent ?? "").not.toContain(raw);
    }
  });

  it("没有任何给人打分的位置", async () => {
    mockApi();
    render(<InvitationsScreen />);

    await screen.findByText(GET_ONE);
    expect(document.body.textContent ?? "").not.toMatch(
      /评分|打分|星|分数|得分|匹配度|%|％/,
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
    "同意凭证",
    "成局提案",
    "成局证明",
    "行动回声",
    "记忆切面",
    "共同素材",
    "稳定性",
    "撮合",
    "求解",
    "召回",
    "约束",
    "智能体",
    "代理",
    "授权",
    "提案",
    "凭证",
    "信封",
    "回声",
    "素材",
  ]) {
    expect(text).not.toContain(term);
  }
}
