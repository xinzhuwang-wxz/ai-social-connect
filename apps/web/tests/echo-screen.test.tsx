/**
 * 「这次留下了什么」的产品行为。
 *
 * 这里的 fetch 桩是**有状态的**：点过头的、收回过的真的改变后续取数的结果。
 * 一个每次都返回同一份数据的桩，会让"收回即时生效"这条断言变成走过场。
 *
 * 三条断言是这一屏的底线，其余都是围着它们转的：
 * 界面上**没有一个位置能给人打分**、**没点过头的写着还不算数**、
 * **收回之后它立刻不再显示在被用着**。
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EchoScreen } from "@/components/echo-screen";
import type { Echo, Intent } from "@/lib/invitations";
import type { MyRecord, MyRecords } from "@/lib/me";

const EVENT = "11111111-1111-4111-8111-111111111111";
const ME = "33333333-3333-4333-8333-333333333333";
const GUESS = "22222222-2222-4222-8222-222222222222";
const KEPT = "44444444-4444-4444-8444-444444444444";
const FILM = "77777777-7777-4777-8777-777777777777";
const BOARD = "88888888-8888-4888-8888-888888888888";
const WRITTEN = "99999999-9999-4999-8999-999999999999";
const SU_ID = "55555555-5555-4555-8555-555555555555";
const INTENT_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";

const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString();

/** 已确认的、可参与配队的需求。上次那几个人就靠它被问到。 */
const MATCHABLE_INTENT: Intent = {
  id: INTENT_ID,
  principal_id: ME,
  state: "confirmed",
  raw_expression: "再拍一支短片",
  content: {
    goal: "再拍一支短片",
    offers: [],
    needs: [],
    boundaries: [],
    open_questions: [],
    uncertain_fields: [],
  },
  created_at: inHours(-1),
  expires_at: null,
  is_matchable: true,
  action_kind: null,
  reach: "campus",
};

const GUESS_TEXT = "他在这次里做了剪辑和调色";
const KEPT_TEXT = "他做完过一支 60 秒短片，负责剪辑";
const RECAP_TEXT = "三个人用两周拍完了一支 60 秒短片，苏晚拍摄，陈牧剪辑。";

const ECHO: Echo = {
  event_title: "檐下",
  evidence: [
    {
      id: FILM,
      kind: "artifact",
      title: "成片 檐下.mp4",
      body: "最终版，2 分 03 秒",
      uri: null,
      uploaded_by: ME,
    },
    {
      id: BOARD,
      kind: "photo",
      title: "拍摄当天的返图",
      body: null,
      uri: "https://example.invalid/a.jpg",
      uploaded_by: ME,
    },
  ],
  recap: { text: RECAP_TEXT, grounded_in: ["成片 檐下.mp4", "拍摄当天的返图"] },
  confirmed: [],
  to_confirm: [
    {
      facet_id: GUESS,
      text: GUESS_TEXT,
      grounded_in: ["成片 檐下.mp4"],
      hint: "这是我猜的，你看对不对",
      drafted_by_agent: true,
    },
  ],
};

const KEPT_RECORD: MyRecord = {
  id: KEPT,
  text: KEPT_TEXT,
  state: "confirmed",
  drafted_by_agent: false,
  created_at: inHours(-70),
  confirmed_at: inHours(-69),
  revoked_at: null,
  event_id: EVENT,
  event_title: "檐下",
  sources: [
    { evidence_id: FILM, kind: "artifact", title: "成片 檐下.mp4", added_at: inHours(-70) },
  ],
  in_use: 1,
};

/** 别的事情上的记录。它不该出现在这一屏上。 */
const ELSEWHERE: MyRecord = {
  ...KEPT_RECORD,
  id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  text: "他在另一件事里做过策展",
  event_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  event_title: "另一件事",
};

const RECORDS: MyRecords = {
  to_confirm: [],
  confirmed: [KEPT_RECORD, ELSEWHERE],
  revoked: [],
};

const NOTHING: MyRecords = { to_confirm: [], confirmed: [], revoked: [] };

const EMPTY_ECHO: Echo = {
  event_title: "檐下",
  evidence: [],
  recap: null,
  confirmed: [],
  to_confirm: [],
};

type Call = { url: string; method: string; body: unknown };

type Options = {
  echo?: Echo;
  records?: MyRecords;
  echoStatus?: number;
  recordsStatus?: number;
  writeStatus?: number;
  /** 不传表示没有可用需求（InviteSection 不显示）。 */
  intents?: Intent[];
  askAgainStatus?: number;
  hang?: boolean;
};

function mockApi(opts: Options = {}): Call[] {
  const calls: Call[] = [];
  const echo: Echo = JSON.parse(JSON.stringify(opts.echo ?? ECHO));
  const records: MyRecords = JSON.parse(JSON.stringify(opts.records ?? RECORDS));
  const reply = (body: unknown, status = 200) => ({
    ok: status < 300,
    status,
    json: async () => body,
  });

  const find = (id: string): MyRecord => {
    const known = [...records.to_confirm, ...records.confirmed, ...records.revoked].find(
      (r) => r.id === id,
    );
    if (known) return known;
    // 等你点头的那几条只在 echo 里，取数时还不是 MyRecord。
    const draft = echo.to_confirm?.find((d) => d.facet_id === id);
    return {
      ...KEPT_RECORD,
      id,
      text: draft?.text ?? "",
      state: "draft",
      drafted_by_agent: draft?.drafted_by_agent ?? false,
      sources: (draft?.grounded_in ?? []).map((title) => ({
        evidence_id: FILM,
        kind: "artifact",
        title,
        added_at: inHours(-70),
      })),
      in_use: 0,
    };
  };

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

      // 每次都发一份新的：真实的 HTTP 不会让界面和桩共用同一个数组，
      // 共用的话"界面自己加进去的那一条"和"桩里已经有的那一条"会变成同一条，
      // 于是一个本该抓到重复的断言反而通过了。
      if (url === `/api/events/${EVENT}/again`) {
        return reply({
          goal: "拍一支 60 秒短片",
          offers: ["写脚本"],
          needs: [],
          team_min: 2,
          team_max: 2,
          last_time_with: [
            { principal_id: SU_ID, display_name: "苏晚" },
          ],
        });
      }
      // POST /api/events/{id}:again（注意冒号，不是斜杠）——问上次那几个人
      if (url === `/api/events/${EVENT}:again` && method === "POST") {
        return opts.askAgainStatus
          ? reply({ detail: "没发出去" }, opts.askAgainStatus)
          : reply({ asked: 1 });
      }
      // 我发过的、可参与配队的需求。不传 intents 表示没有（InviteSection 不显示）。
      if (url === "/api/me/intents") {
        return reply(opts.intents ?? []);
      }
      if (url === `/api/events/${EVENT}/echo`) {
        return opts.echoStatus
          ? reply({ detail: "没连上" }, opts.echoStatus)
          : reply(JSON.parse(JSON.stringify(echo)));
      }
      if (url === "/api/me/facets") {
        return opts.recordsStatus
          ? reply({ detail: "没连上" }, opts.recordsStatus)
          : reply(JSON.parse(JSON.stringify(records)));
      }

      if (opts.writeStatus) return reply({ detail: "没连上" }, opts.writeStatus);

      if (url === `/api/events/${EVENT}/evidence`) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        const item = { id: crypto.randomUUID(), uploaded_by: ME, ...body };
        echo.evidence = [...echo.evidence, item as (typeof echo.evidence)[number]];
        return reply(item, 201);
      }

      if (url === `/api/events/${EVENT}/records`) {
        const body = JSON.parse(String(init?.body)) as { text: string };
        return reply(
          {
            facet_id: WRITTEN,
            text: body.text,
            grounded_in: [],
            hint: "这是你自己写的，点一下才会开始被用到。",
            drafted_by_agent: false,
          },
          201,
        );
      }

      const confirming = url.match(/\/api\/facets\/(.+):confirm$/);
      if (confirming) {
        const kept: MyRecord = {
          ...find(confirming[1]!),
          state: "confirmed",
          confirmed_at: inHours(0),
          in_use: 0,
        };
        records.confirmed = [kept, ...records.confirmed];
        return reply(kept);
      }

      const revoking = url.match(/\/api\/facets\/(.+):revoke$/);
      if (revoking) {
        const gone: MyRecord = {
          ...find(revoking[1]!),
          state: "revoked",
          revoked_at: inHours(0),
          in_use: 0,
        };
        records.confirmed = records.confirmed.filter((r) => r.id !== gone.id);
        records.revoked = [gone, ...records.revoked];
        return reply(gone);
      }

      return reply(null, 404);
    }),
  );
  return calls;
}

const posts = (calls: Call[], match: string) =>
  calls.filter((c) => c.method === "POST" && c.url.includes(match));

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.localStorage.setItem("cofield.principal", ME);
});

describe("留下的东西", () => {
  it("先出现的是留下来的东西，不是一个空输入框", async () => {
    mockApi();
    render(<EchoScreen eventId={EVENT} />);

    const film = within(await screen.findByRole("article", { name: "成片 檐下.mp4" }));
    expect(film.getByText("最终版，2 分 03 秒")).toBeVisible();

    const shot = within(screen.getByRole("article", { name: "拍摄当天的返图" }));
    expect(shot.getByRole("link", { name: "打开看看" })).toHaveAttribute(
      "href",
      "https://example.invalid/a.jpg",
    );
  });

  it("留下一件东西之后它立刻在列表里", async () => {
    const calls = mockApi();
    render(<EchoScreen eventId={EVENT} />);

    const form = within(await screen.findByRole("region", { name: "留下一件东西" }));
    await userEvent.click(form.getByRole("radio", { name: "一段记录" }));
    await userEvent.type(form.getByLabelText("一句话说清这是什么"), "当天的排期");
    await userEvent.type(form.getByLabelText("多写几句"), "周三晚上七点南门集合");
    await userEvent.click(form.getByRole("button", { name: "留下" }));

    expect(await screen.findByRole("article", { name: "当天的排期" })).toBeVisible();
    expect(posts(calls, "/evidence")[0]?.body).toEqual({
      kind: "note",
      title: "当天的排期",
      body: "周三晚上七点南门集合",
      uri: null,
    });
  });

  it("一句话都没写就发不出去", async () => {
    mockApi();
    render(<EchoScreen eventId={EVENT} />);

    const form = within(await screen.findByRole("region", { name: "留下一件东西" }));
    expect(form.getByRole("button", { name: "留下" })).toBeDisabled();
  });

  it("只记发生过什么，没有一个位置能给人打分", async () => {
    mockApi();
    const { container } = render(<EchoScreen eventId={EVENT} />);

    await screen.findByRole("article", { name: "成片 檐下.mp4" });
    expect(screen.getByText("只记发生过什么，不记谁做得好不好。")).toBeVisible();
    expect(container.textContent ?? "").not.toMatch(/评分|打分|星|分数|得分|好评|差评/);
    // 表单上能填的只有"这是什么"和它的内容，没有一个字段是关于人的。
    const form = within(screen.getByRole("region", { name: "留下一件东西" }));
    expect(form.getAllByRole("textbox")).toHaveLength(2);
    expect(form.queryByRole("slider")).toBeNull();
    for (const name of ["苏晚", "陈牧", "队友", "表现"]) {
      expect(form.queryByLabelText(new RegExp(name))).toBeNull();
    }
  });
});

describe("这次一起做成了什么", () => {
  it("点开能看它照着什么写的", async () => {
    mockApi();
    render(<EchoScreen eventId={EVENT} />);

    expect(await screen.findByText(RECAP_TEXT)).toBeVisible();
    expect(screen.queryByText("· 成片 檐下.mp4")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "这段是照着什么写的" }));
    const said = within(screen.getByRole("region", { name: "这次一起做成了什么" }));
    expect(said.getByText("· 成片 檐下.mp4")).toBeVisible();
    expect(said.getByText("· 拍摄当天的返图")).toBeVisible();
  });
});

describe("等你点头", () => {
  it("每条带来源、带那句常驻的话，并且明确标着还不算数", async () => {
    mockApi();
    render(<EchoScreen eventId={EVENT} />);

    const one = within(await screen.findByRole("article", { name: GUESS_TEXT }));
    expect(one.getByText("还不算数")).toBeVisible();
    expect(one.getByText("这是我猜的，你看对不对")).toBeVisible();
    expect(one.getByText("照着这些写的：成片 檐下.mp4")).toBeVisible();
    expect(
      screen.getByText(/没点过头的，任何人都看不到，也不会出现在给别人看的说明里/),
    ).toBeVisible();
  });

  it("说不出来源的那条如实说，并建议删掉", async () => {
    mockApi({
      echo: { ...ECHO, to_confirm: [{ ...ECHO.to_confirm![0]!, grounded_in: [] }] },
    });
    render(<EchoScreen eventId={EVENT} />);

    expect(
      await screen.findByText("这条说不出是照着什么写的。拿不准就删掉它"),
    ).toBeVisible();
  });

  it("点过头之后它挪到「已经在用的」那一堆", async () => {
    mockApi();
    render(<EchoScreen eventId={EVENT} />);

    await userEvent.click(await screen.findByRole("button", { name: "对，是这样" }));

    await waitFor(() => {
      const inUse = within(screen.getByRole("region", { name: "已经在用的" }));
      expect(inUse.getByRole("article", { name: GUESS_TEXT })).toBeVisible();
    });
    const waiting = within(screen.getByRole("region", { name: "等你点头" }));
    expect(waiting.queryByRole("article", { name: GUESS_TEXT })).toBeNull();
    expect(waiting.getByText("没有等你点头的。")).toBeVisible();
  });

  it("自己写一条，写完它也在等你点头那一堆里", async () => {
    const calls = mockApi();
    render(<EchoScreen eventId={EVENT} />);

    const form = within(await screen.findByRole("region", { name: "自己写一条" }));
    await userEvent.type(form.getByLabelText("你想记下什么？"), "我负责了这次的剪辑");
    await userEvent.click(form.getByRole("button", { name: "记下来" }));

    await waitFor(() => {
      const waiting = within(screen.getByRole("region", { name: "等你点头" }));
      expect(waiting.getByRole("article", { name: "我负责了这次的剪辑" })).toBeVisible();
    });
    expect(posts(calls, "/records")[0]?.body).toEqual({ text: "我负责了这次的剪辑" });
    expect(
      within(screen.getByRole("article", { name: "我负责了这次的剪辑" })).getByText(
        "还不算数",
      ),
    ).toBeVisible();
  });
});

describe("收回", () => {
  it("一步完成：不再确认一次，也不问为什么", async () => {
    const calls = mockApi();
    render(<EchoScreen eventId={EVENT} />);

    const card = within(await screen.findByRole("article", { name: KEPT_TEXT }));
    await userEvent.click(card.getByRole("button", { name: "收回" }));

    await screen.findByRole("region", { name: "你收回过的" });
    expect(posts(calls, ":revoke")).toHaveLength(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(
      screen.queryByRole("button", { name: /确定|确认|再想想|为什么|取消/ }),
    ).toBeNull();
  });

  it("收回之后界面立刻不再显示它在被使用", async () => {
    mockApi();
    render(<EchoScreen eventId={EVENT} />);

    // 收回之前，它确实正被一处用着。
    expect(await screen.findByText("现在有 1 处正在用这句话")).toBeVisible();

    await userEvent.click(
      within(screen.getByRole("article", { name: KEPT_TEXT })).getByRole("button", {
        name: "收回",
      }),
    );

    const gone = within(await screen.findByRole("region", { name: "你收回过的" }));
    expect(gone.getByText("你收回了这句话，它不会再被用到。")).toBeVisible();
    expect(screen.queryByText("现在有 1 处正在用这句话")).toBeNull();
    expect(gone.queryByRole("button", { name: "收回" })).toBeNull();
  });

  it("别的事情上的记录不出现在这一屏上", async () => {
    mockApi();
    render(<EchoScreen eventId={EVENT} />);

    await screen.findByRole("article", { name: KEPT_TEXT });
    expect(screen.queryByText(ELSEWHERE.text)).toBeNull();
  });
});

describe("五态", () => {
  it("首次：标题说的是这次留下了什么，副标题是这件事的名字", async () => {
    mockApi();
    render(<EchoScreen eventId={EVENT} />);

    expect(
      await screen.findByRole("heading", { name: "这次留下了什么" }),
    ).toBeVisible();
    expect(screen.getByText("檐下")).toBeVisible();
  });

  it("加载：给骨架，不是一片空白", () => {
    mockApi({ hang: true });
    render(<EchoScreen eventId={EVENT} />);

    expect(screen.getByLabelText("加载中")).toBeVisible();
  });

  it("空：还没有任何东西时，说清留下点什么、以后你自己也会想看", async () => {
    mockApi({ echo: EMPTY_ECHO, records: NOTHING });
    render(<EchoScreen eventId={EVENT} />);

    expect(await screen.findByText("这次还没留下任何东西。")).toBeVisible();
    expect(screen.getByText(/以后你自己也会想看/)).toBeVisible();
    // 空态要带一个能用的入口，不是一句"暂无内容"。
    expect(screen.getByRole("region", { name: "留下一件东西" })).toBeVisible();
    expect(screen.getByRole("region", { name: "自己写一条" })).toBeVisible();
  });

  it("空：从空态留下第一件东西，这一屏立刻长出来", async () => {
    mockApi({ echo: EMPTY_ECHO, records: NOTHING });
    render(<EchoScreen eventId={EVENT} />);

    const form = within(await screen.findByRole("region", { name: "留下一件东西" }));
    await userEvent.type(form.getByLabelText("一句话说清这是什么"), "拍摄当天的返图");
    await userEvent.click(form.getByRole("button", { name: "留下" }));

    expect(await screen.findByRole("article", { name: "拍摄当天的返图" })).toBeVisible();
    expect(screen.queryByText("这次还没留下任何东西。")).toBeNull();
  });

  it("错误：说清哪里断了，并说明什么都没被改动", async () => {
    mockApi({ echoStatus: 500 });
    render(<EchoScreen eventId={EVENT} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("调不出这次留下的东西");
    expect(screen.getByText(/什么都不会被改动/)).toBeVisible();
    expect(screen.getByRole("button", { name: "再试一次" })).toBeVisible();
  });

  it("降级：那段回顾取不到时，留下的东西和自己写一条照常", async () => {
    const calls = mockApi({ echo: { ...ECHO, recap: null } });
    render(<EchoScreen eventId={EVENT} />);

    expect(await screen.findByText(/这一段现在写不出来/)).toBeVisible();
    // 留下的东西照常看得到。
    expect(screen.getByRole("article", { name: "成片 檐下.mp4" })).toBeVisible();
    // 等你点头的那几条也照常。
    expect(screen.getByRole("article", { name: GUESS_TEXT })).toBeVisible();
    // 自己写一条照常能写。
    const form = within(screen.getByRole("region", { name: "自己写一条" }));
    await userEvent.type(form.getByLabelText("你想记下什么？"), "我负责了这次的剪辑");
    await userEvent.click(form.getByRole("button", { name: "记下来" }));
    await waitFor(() => {
      expect(posts(calls, "/records")).toHaveLength(1);
    });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("降级：调不出点过头的那几条时，这一屏其余部分照常", async () => {
    mockApi({ recordsStatus: 503 });
    render(<EchoScreen eventId={EVENT} />);

    expect(await screen.findByText(/现在调不出你点过头的那几条/)).toBeVisible();
    expect(screen.getByText(/这一屏其余的照常能用/)).toBeVisible();
    expect(screen.getByRole("article", { name: "成片 檐下.mp4" })).toBeVisible();
    expect(screen.getByRole("article", { name: GUESS_TEXT })).toBeVisible();
  });

  it("降级：留下的东西没发出去时说清它还没留下", async () => {
    mockApi({ writeStatus: 503 });
    render(<EchoScreen eventId={EVENT} />);

    const form = within(await screen.findByRole("region", { name: "留下一件东西" }));
    await userEvent.type(form.getByLabelText("一句话说清这是什么"), "当天的排期");
    await userEvent.click(form.getByRole("button", { name: "留下" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("这件东西还没留下");
  });
});

describe("语言", () => {
  it("这一屏不出现领域词汇", async () => {
    mockApi();
    const { container } = render(<EchoScreen eventId={EVENT} />);

    await screen.findByText(RECAP_TEXT);
    await userEvent.click(screen.getByRole("button", { name: "这段是照着什么写的" }));
    expectNoDomainWords(container.textContent ?? "");
  });

  it("什么都还没有的那一屏也不出现领域词汇", async () => {
    mockApi({ echo: EMPTY_ECHO, records: NOTHING });
    const { container } = render(<EchoScreen eventId={EVENT} />);

    await screen.findByText("这次还没留下任何东西。");
    expectNoDomainWords(container.textContent ?? "");
  });

  it("英文标识符不会原样露出来", async () => {
    mockApi();
    render(<EchoScreen eventId={EVENT} />);

    await screen.findByText(RECAP_TEXT);
    for (const raw of [
      "artifact",
      "photo",
      "note",
      "draft",
      "confirmed",
      "revoked",
      "facet_id",
      "grounded_in",
    ]) {
      expect(document.body.textContent ?? "").not.toContain(raw);
    }
  });

  it("不出现任何百分比或分数", async () => {
    mockApi();
    render(<EchoScreen eventId={EVENT} />);

    await screen.findByText(RECAP_TEXT);
    expect(document.body.textContent ?? "").not.toMatch(/%|％|百分|匹配度|得分|评分/);
  });
});

function expectNoDomainWords(text: string) {
  for (const term of [
    "意图",
    "主体",
    "切面",
    "共域",
    "记忆切面",
    "匹配信封",
    "同意凭证",
    "成局提案",
    "成局证明",
    "行动回声",
    "共同事件",
    "共同素材",
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
    "证据",
  ]) {
    expect(text).not.toContain(term);
  }
}

describe("再来一次", () => {
  it("看完这次留下什么，给一条通往下一次的路", async () => {
    // PRD 的最后一段：第一次行动完成后进入下一轮 Loop。
    // 在它之前，森林里的一株点进去只能看。
    mockApi();
    render(<EchoScreen eventId={EVENT} />);

    const card = await screen.findByRole("region", { name: "再来一次" });
    expect(within(card).getByText(/上次是和苏晚一起做的/)).toBeVisible();
    expect(
      within(card).getByRole("link", { name: "照这个再来一次" }),
    ).toHaveAttribute("href", expect.stringContaining("again="));
  });
});

describe("问上次的人", () => {
  it("按了之后屏上说的是等他们答复，不是他们已经回来了", async () => {
    // 不变量 3：成局前只有提案，没有关系。
    // 「问」发出去的是一条待答复，每个人要自己点头——不是把人拉进来。
    const calls = mockApi({ intents: [MATCHABLE_INTENT] });
    render(<EchoScreen eventId={EVENT} />);

    const card = await screen.findByRole("region", { name: "再来一次" });
    const select = await within(card).findByRole("combobox", { name: "选一条需求" });
    await userEvent.selectOptions(select, "再拍一支短片");
    await userEvent.click(within(card).getByRole("button", { name: "问他们" }));

    expect(await within(card).findByText(/问过了，等他们各自答复/)).toBeVisible();
    // 界面上不出现「他们回来了」「已加入」这类意味着承诺已成立的话
    expect(within(card).queryByText(/他们回来了|已加入|已经加入/)).toBeNull();

    // 请求里带了正确的 intent_id 和 invite 列表
    const askCall = calls.find((c) => c.url.includes(":again") && c.method === "POST");
    expect(askCall?.body).toEqual({ intent_id: INTENT_ID, invite: [SU_ID] });
  });

  it("按过一次之后按钮不再出现，不能重复发给同一批人", async () => {
    mockApi({ intents: [MATCHABLE_INTENT] });
    render(<EchoScreen eventId={EVENT} />);

    const card = await screen.findByRole("region", { name: "再来一次" });
    const select = await within(card).findByRole("combobox", { name: "选一条需求" });
    await userEvent.selectOptions(select, "再拍一支短片");
    await userEvent.click(within(card).getByRole("button", { name: "问他们" }));

    await within(card).findByText(/问过了/);
    // 按钮消失，没有路径能再发一次
    expect(within(card).queryByRole("button", { name: "问他们" })).toBeNull();
  });

  it("失败时说清没发出去，按钮还在，能再试", async () => {
    mockApi({ intents: [MATCHABLE_INTENT], askAgainStatus: 500 });
    render(<EchoScreen eventId={EVENT} />);

    const card = await screen.findByRole("region", { name: "再来一次" });
    const select = await within(card).findByRole("combobox", { name: "选一条需求" });
    await userEvent.selectOptions(select, "再拍一支短片");
    await userEvent.click(within(card).getByRole("button", { name: "问他们" }));

    expect(await within(card).findByRole("alert")).toHaveTextContent("没发出去");
    // 失败不是终点，按钮还在能重试
    expect(within(card).getByRole("button", { name: "问他们" })).toBeEnabled();
  });
});
