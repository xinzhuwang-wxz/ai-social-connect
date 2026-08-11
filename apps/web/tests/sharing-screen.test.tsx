/**
 * 第二屏的产品行为：这次让他们看到我的。
 *
 * 断言的是用户能勾什么、对方那边跟着变成什么样，不是组件内部长什么样。
 * 后端在这套用例里是有状态的——预览由"当前已保存的授权"算出来，
 * 否则"勾选立刻反映到预览"这条就成了对着写死的假数据自说自话。
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SharingScreen } from "@/components/sharing-screen";

const INTENT_ID = "11111111-1111-4111-8111-111111111111";
const ENVELOPE_ID = "22222222-2222-4222-8222-222222222222";
const EXPIRES_AT = "2026-08-15T10:00:00Z";

/** 后端 `_FIELD_LABELS` 的镜像。`self_intro` 那条后端还没给中文标签。 */
const LABELS: Record<string, string> = {
  boundaries: "我的底线",
  goal: "要做什么",
  location_scope: "在哪",
  needs: "我缺",
  offers: "我能出",
  open_questions: "还没定的事",
  portfolio_link: "作品链接",
  self_intro: "self_intro",
  team_size: "几个人",
  time_window: "什么时候",
};

/** 预览的 `withheld` 只覆盖后端有标签的那些字段。 */
const PREVIEW_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries(LABELS).filter(([name]) => name !== "self_intro"),
);

const VALUES: Record<string, unknown> = {
  goal: "周五前完成 60 秒校园流浪猫短片",
  offers: ["写脚本"],
  needs: ["拍摄", "剪辑"],
  time_window: { earliest: "2026-08-12T09:00:00Z", deadline: "2026-08-14T23:59:00Z" },
  team_size: { minimum: 3, maximum: 4 },
};

const WRITTEN = Object.keys(VALUES);

type Grant = { field_name: string; audience: string };
type Envelope = {
  id: string;
  intent_id: string;
  grants: (Grant & { purposes: string[]; purpose_label: string })[];
  cited_facet_ids: string[];
  state: string;
  expires_at: string;
};

function fieldsOf(written: string[] = WRITTEN) {
  return Object.entries(LABELS).map(([field_name, label]) => ({
    field_name,
    label,
    present: written.includes(field_name),
  }));
}

function envelopeOf(grants: Grant[]): Envelope {
  return {
    id: ENVELOPE_ID,
    intent_id: INTENT_ID,
    grants: grants.map((g) => ({
      ...g,
      purposes:
        g.audience === "candidates"
          ? ["formation_feasibility", "formation_proof"]
          : ["formation_feasibility"],
      purpose_label:
        g.audience === "candidates"
          ? "对方能在小队说明里看到"
          : "只给系统算，不展示给对方",
    })),
    cited_facet_ids: [],
    state: "active",
    expires_at: EXPIRES_AT,
  };
}

/** 服务端那条投影：只有标了"对方可见"的字段才会出现在对方眼里。 */
function previewOf(envelope: Envelope | null) {
  const open =
    envelope && envelope.state === "active"
      ? envelope.grants.filter((g) => g.audience === "candidates").map((g) => g.field_name)
      : [];
  const visible: Record<string, unknown> = {};
  for (const name of open) {
    if (VALUES[name] !== undefined) visible[PREVIEW_LABELS[name] ?? name] = VALUES[name];
  }
  const withheld = Object.entries(PREVIEW_LABELS)
    .filter(([name]) => !open.includes(name))
    .map(([, label]) => label)
    .sort();
  return { visible, withheld };
}

type Options = {
  written?: string[];
  envelope?: Envelope | null;
  fieldsStatus?: number;
  previewStatus?: number;
  putStatus?: number;
  hang?: boolean;
};

function mockApi(opts: Options = {}) {
  let envelope = opts.envelope ?? null;
  const reply = (body: unknown, status = 200) => ({
    ok: status < 300,
    status,
    json: async () => body,
  });

  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (opts.hang) return new Promise(() => {});

      if (url.endsWith("/grantable-fields")) {
        return opts.fieldsStatus
          ? reply({ detail: "没连上" }, opts.fieldsStatus)
          : reply(fieldsOf(opts.written));
      }
      if (url.endsWith("/preview")) {
        return opts.previewStatus
          ? reply({ detail: "没连上" }, opts.previewStatus)
          : reply(previewOf(envelope));
      }
      if (url === "/api/me/grants") {
        return reply(envelope && envelope.state === "active" ? [envelope] : []);
      }
      if (url.endsWith("/envelope") && init?.method === "PUT") {
        if (opts.putStatus) return reply({ detail: "没连上" }, opts.putStatus);
        const body = JSON.parse(String(init.body)) as { grants: Grant[] };
        envelope = envelopeOf(body.grants);
        return reply(envelope);
      }
      if (url.endsWith(":revoke")) {
        if (envelope) envelope = { ...envelope, state: "revoked" };
        return reply(envelope);
      }
      return reply(null, 404);
    }),
  );
}

const seen = () => screen.getByRole("complementary", { name: "他们会看到" });
const row = (label: string) => screen.getByRole("group", { name: label });

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("默认", () => {
  it("首次进来一项都没勾，对方什么都看不到", async () => {
    mockApi();
    render(<SharingScreen intentId={INTENT_ID} />);

    const boxes = await screen.findAllByRole("checkbox");
    expect(boxes).toHaveLength(WRITTEN.length);
    for (const box of boxes) expect(box).not.toBeChecked();

    expect(await within(seen()).findByText(/什么都看不到/)).toBeVisible();
    expect(screen.getByText("你还没给出任何东西")).toBeVisible();
  });

  it("新勾上的一项默认只拿去配对，不是直接给对方看", async () => {
    mockApi();
    render(<SharingScreen intentId={INTENT_ID} />);

    const box = await within(await screen.findByRole("group", { name: "什么时候" })).findByRole(
      "checkbox",
    );
    await userEvent.click(box);

    expect(within(row("什么时候")).getByRole("radio", { name: "只用来配对" })).toBeChecked();
    await waitFor(() => {
      expect(within(seen()).queryByText("什么时候")).toBeNull();
    });
  });
});

describe("勾选与预览", () => {
  it("改成对方可见，预览里立刻多出这一项", async () => {
    mockApi();
    render(<SharingScreen intentId={INTENT_ID} />);

    await userEvent.click(
      await within(await screen.findByRole("group", { name: "什么时候" })).findByRole("checkbox"),
    );
    await userEvent.click(within(row("什么时候")).getByRole("radio", { name: "他们能看到" }));

    await waitFor(() => {
      expect(within(seen()).getByText("什么时候")).toBeVisible();
    });
    expect(within(seen()).getByText(/8 月 15 日/)).toBeVisible();
  });

  it("每一项都说清为什么要它，不只是一个字段名", async () => {
    mockApi();
    render(<SharingScreen intentId={INTENT_ID} />);

    await screen.findByRole("group", { name: "什么时候" });
    for (const [label, why] of [
      ["要做什么", /才可能有人一眼认出/],
      ["我能出", /别人愿意来的理由/],
      ["我缺", /才有人来补/],
      ["什么时候", /排得出大家都在的时间/],
      ["几个人", /这个组什么时候能开工/],
    ] as const) {
      expect(within(row(label)).getByText(why)).toBeVisible();
    }
  });

  it("这次没写的项不给一个勾不动的空开关，只说一句", async () => {
    mockApi();
    render(<SharingScreen intentId={INTENT_ID} />);

    expect(await screen.findByText(/这次没写的还有/)).toHaveTextContent("作品链接");
    expect(screen.queryByRole("group", { name: "作品链接" })).toBeNull();
  });
});

describe("收回", () => {
  const GIVEN = envelopeOf([
    { field_name: "time_window", audience: "candidates" },
    { field_name: "goal", audience: "candidates" },
  ]);

  it("取消勾选就是收回，该项立刻从预览里消失", async () => {
    mockApi({ envelope: GIVEN });
    render(<SharingScreen intentId={INTENT_ID} />);

    await screen.findByRole("group", { name: "什么时候" });
    expect(await within(seen()).findByText("什么时候")).toBeVisible();

    await userEvent.click(within(row("什么时候")).getByRole("checkbox"));

    await waitFor(() => {
      expect(within(seen()).queryByText("什么时候")).toBeNull();
    });
    expect(within(seen()).getByText("要做什么")).toBeVisible();
  });

  it("全部收回之后对方那边就空了", async () => {
    mockApi({ envelope: GIVEN });
    render(<SharingScreen intentId={INTENT_ID} />);

    await userEvent.click(await screen.findByRole("button", { name: "全部收回" }));

    await waitFor(() => {
      expect(within(seen()).getByText(/什么都看不到/)).toBeVisible();
    });
    for (const box of screen.getAllByRole("checkbox")) expect(box).not.toBeChecked();
  });

  it("已经给出过的授权，回来时是勾着的，并写明什么时候失效", async () => {
    mockApi({ envelope: GIVEN });
    render(<SharingScreen intentId={INTENT_ID} />);

    expect(await within(await screen.findByRole("group", { name: "什么时候" })).findByRole(
      "checkbox",
    )).toBeChecked();
    expect(screen.getByText(/自动失效/)).toBeVisible();
  });
});

describe("五态", () => {
  it("加载：给骨架，不是一片空白", () => {
    mockApi({ hang: true });
    render(<SharingScreen intentId={INTENT_ID} />);

    expect(screen.getByLabelText("加载中")).toBeVisible();
  });

  it("空：这条需求还没写内容时，说清为什么空并指一条路", async () => {
    mockApi({ written: [] });
    render(<SharingScreen intentId={INTENT_ID} />);

    expect(await screen.findByText(/还没写下任何内容/)).toBeVisible();
    expect(screen.getByRole("link", { name: "回去补上" })).toBeVisible();
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
  });

  it("错误：说清哪里断了，并说明在这之前没人看得到你", async () => {
    mockApi({ fieldsStatus: 500 });
    render(<SharingScreen intentId={INTENT_ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("没能把这次可以给的东西调出来");
    expect(screen.getByRole("button", { name: "再试一次" })).toBeVisible();
  });

  it("错误：保存失败时那一项退回原样，不假装存上了", async () => {
    mockApi({ putStatus: 500 });
    render(<SharingScreen intentId={INTENT_ID} />);

    const box = await within(await screen.findByRole("group", { name: "什么时候" })).findByRole(
      "checkbox",
    );
    await userEvent.click(box);

    expect(await screen.findByRole("alert")).toHaveTextContent("没存上");
    expect(within(row("什么时候")).getByRole("checkbox")).not.toBeChecked();
  });

  it("降级：预览调不出来时照样能勾能存，并且明说看不到", async () => {
    mockApi({ previewStatus: 503 });
    render(<SharingScreen intentId={INTENT_ID} />);

    const box = await within(await screen.findByRole("group", { name: "什么时候" })).findByRole(
      "checkbox",
    );
    await userEvent.click(box);

    expect(within(seen()).getByText(/调不出他们那边的样子/)).toBeVisible();
    await waitFor(() => {
      expect(within(row("什么时候")).getByRole("checkbox")).toBeChecked();
    });
    expect(screen.getByText("已经生效")).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("语言", () => {
  it("界面上不出现领域词汇", async () => {
    mockApi({
      envelope: envelopeOf(WRITTEN.map((field_name) => ({ field_name, audience: "candidates" }))),
    });
    const { container } = render(<SharingScreen intentId={INTENT_ID} />);

    await screen.findByRole("group", { name: "什么时候" });
    await within(seen()).findByText("要做什么");

    const text = container.textContent ?? "";
    for (const term of [
      "意图",
      "主体",
      "切面",
      "共域",
      "匹配信封",
      "代理授权",
      "同意凭证",
      "漏斗",
      "召回",
      "求解",
      "约束",
      "提案",
      "稳定性",
      "智能体",
      "代理",
    ]) {
      expect(text).not.toContain(term);
    }
  });

  it("后端还没翻译的字段名不会以英文原样露出来", async () => {
    mockApi();
    render(<SharingScreen intentId={INTENT_ID} />);

    await screen.findByRole("group", { name: "什么时候" });
    for (const raw of ["self_intro", "solver_only", "candidates", "formation_proof"]) {
      expect(document.body.textContent ?? "").not.toContain(raw);
    }
  });
});
