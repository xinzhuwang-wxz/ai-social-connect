/**
 * 「我这边」这一屏的产品行为。
 *
 * 这一屏是**被找到那一侧的全部入口**：不填它，一个真人永远不出现在
 * 任何人的候选里。所以这里断言的重点不是表单能用，是
 *
 * - 那些可点的词**来自服务端**（前端硬编码一份 = 屏上出现匹配零个人的词）
 * - 「我能做的」和「我想参与的」是**两栏**（合成一栏，想入门的人不敢勾）
 * - 服务端没认出来的词**说出来**，不静默丢掉
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { AboutMeScreen } from "@/components/about-me-screen";

const VOCAB = {
  skills: ["剪辑", "拍摄", "写文案"],
  zones: ["东校区", "西校区"],
  majors: ["新闻传播", "计算机"],
};

type Call = { url: string; method: string; body: unknown };

type Options = {
  profile?: Partial<{
    skills: string[];
    open_to: string[];
    self_intro: string | null;
    zone: string | null;
    major: string | null;
  }>;
  notRecognised?: string[];
  saveStatus?: number;
  vocabStatus?: number;
};

function mockApi(opts: Options = {}): Call[] {
  const calls: Call[] = [];
  const reply = (body: unknown, status = 200) => ({
    ok: status < 300,
    status,
    json: async () => body,
  });
  const mine = {
    display_name: "同学00aa",
    skills: [],
    open_to: [],
    self_intro: null,
    zone: null,
    major: null,
    not_recognised: [],
    ...opts.profile,
  };

  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      calls.push({ url, method, body });

      if (url === "/api/vocabulary") {
        return opts.vocabStatus
          ? reply({ detail: "没连上" }, opts.vocabStatus)
          : reply(VOCAB);
      }
      if (url === "/api/me/profile" && method === "GET") return reply(mine);
      if (url === "/api/me/profile" && method === "PUT") {
        if (opts.saveStatus) return reply({ detail: "没连上" }, opts.saveStatus);
        return reply({
          ...mine,
          skills: body?.skills ?? [],
          open_to: body?.open_to ?? [],
          self_intro: body?.self_intro ?? null,
          zone: body?.zone ?? null,
          major: body?.major ?? null,
          not_recognised: opts.notRecognised ?? [],
        });
      }
      return reply(null, 404);
    }),
  );
  return calls;
}

const saved = (calls: Call[]) =>
  calls.filter((c) => c.url === "/api/me/profile" && c.method === "PUT");

beforeEach(() => vi.unstubAllGlobals());

it("能做的和想参与的是两栏，不是一栏", async () => {
  // 合成一栏只剩两种坏选择：勾了「剪辑」被当成剪辑师，或者不敢勾。
  mockApi();
  render(<AboutMeScreen />);

  const can = await screen.findByRole("region", { name: "我能做的" });
  const want = screen.getByRole("region", { name: "我想参与的" });

  expect(within(can).getByRole("checkbox", { name: "剪辑" })).toBeTruthy();
  expect(within(want).getByRole("checkbox", { name: "剪辑" })).toBeTruthy();
});

it("可点的词来自服务端，不是写死在界面里的", async () => {
  const calls = mockApi();
  render(<AboutMeScreen />);

  await screen.findByRole("region", { name: "我能做的" });
  expect(calls.some((c) => c.url === "/api/vocabulary")).toBe(true);
  const can = screen.getByRole("region", { name: "我能做的" });
  expect(within(can).getAllByRole("checkbox")).toHaveLength(VOCAB.skills.length);
});

it("勾上并存下来之后，两栏分别送出去", async () => {
  const calls = mockApi();
  render(<AboutMeScreen />);

  const can = await screen.findByRole("region", { name: "我能做的" });
  const want = screen.getByRole("region", { name: "我想参与的" });
  await userEvent.click(within(can).getByRole("checkbox", { name: "剪辑" }));
  await userEvent.click(within(want).getByRole("checkbox", { name: "拍摄" }));
  await userEvent.click(screen.getByRole("button", { name: "存下来" }));

  await waitFor(() => expect(saved(calls)).toHaveLength(1));
  expect(saved(calls)[0]!.body).toMatchObject({
    skills: ["剪辑"],
    open_to: ["拍摄"],
  });
});

it("再点一次就取消——「我不想再参与拍摄了」得说得出口", async () => {
  const calls = mockApi({ profile: { open_to: ["拍摄", "剪辑"] } });
  render(<AboutMeScreen />);

  const want = await screen.findByRole("region", { name: "我想参与的" });
  await userEvent.click(within(want).getByRole("checkbox", { name: "拍摄" }));
  await userEvent.click(screen.getByRole("button", { name: "存下来" }));

  await waitFor(() => expect(saved(calls)).toHaveLength(1));
  expect(saved(calls)[0]!.body).toMatchObject({ open_to: ["剪辑"] });
});

it("已经填过的东西，打开时是勾着的", async () => {
  mockApi({ profile: { skills: ["剪辑"], self_intro: "拍东西比较野" } });
  render(<AboutMeScreen />);

  const can = await screen.findByRole("region", { name: "我能做的" });
  expect(
    within(can).getByRole("checkbox", { name: "剪辑" }).getAttribute("aria-checked"),
  ).toBe("true");
  expect(
    (screen.getByLabelText("我是什么样的人") as HTMLTextAreaElement).value,
  ).toBe("拍东西比较野");
});

it("没认出来的词会被说出来，不是悄悄丢掉", async () => {
  // 静默丢掉的代价是他永远不知道为什么没人找他。
  mockApi({ notRecognised: ["打杂"] });
  render(<AboutMeScreen />);

  await screen.findByRole("region", { name: "我能做的" });
  await userEvent.click(screen.getByRole("button", { name: "存下来" }));

  const note = await screen.findByRole("status");
  expect(note.textContent).toContain("打杂");
});

it("存失败的时候不吞掉，也不清空他填的东西", async () => {
  mockApi({ saveStatus: 500 });
  render(<AboutMeScreen />);

  const can = await screen.findByRole("region", { name: "我能做的" });
  await userEvent.click(within(can).getByRole("checkbox", { name: "剪辑" }));
  await userEvent.click(screen.getByRole("button", { name: "存下来" }));

  expect((await screen.findByRole("alert")).textContent).toContain("再点一次");
  expect(
    within(can).getByRole("checkbox", { name: "剪辑" }).getAttribute("aria-checked"),
  ).toBe("true");
});

it("「不填校区」是一个能选的选项，不是留空", async () => {
  // 不填不该让人被排除，而一个只有三个校区可选的界面说不出这件事。
  mockApi();
  render(<AboutMeScreen />);

  const where = await screen.findByRole("radiogroup", { name: "我常在哪" });
  expect(within(where).getByRole("checkbox", { name: "都行" })).toBeTruthy();
});

it("连不上的时候说得出话，不是白屏", async () => {
  mockApi({ vocabStatus: 500 });
  render(<AboutMeScreen />);

  expect(await screen.findByRole("button", { name: "再试一次" })).toBeTruthy();
});

it("院系也能填，不填是「不说」而不是没有这一项", async () => {
  // 跨专业那条软目标只认它。一个人不填，他就永远不会因为
  // "来自另一个院系"而被排进任何一个组——而屏上看不出任何异常。
  const calls = mockApi();
  render(<AboutMeScreen />);

  const which = await screen.findByRole("radiogroup", { name: "我是哪个院系的" });
  expect(within(which).getByRole("checkbox", { name: "不说" })).toBeTruthy();
  await userEvent.click(within(which).getByRole("checkbox", { name: "新闻传播" }));
  await userEvent.click(screen.getByRole("button", { name: "存下来" }));

  await waitFor(() => expect(saved(calls)).toHaveLength(1));
  expect(saved(calls)[0]!.body).toMatchObject({ major: "新闻传播" });
});
