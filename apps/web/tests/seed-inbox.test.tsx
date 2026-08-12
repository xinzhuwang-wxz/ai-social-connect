/**
 * 「信箱」这一屏的产品行为。
 *
 * 这一屏是投递制里被找到的那一侧：他看一眼这件事，决定参不参与。断言的重点
 * 不是"卡片能渲染"，是几条一旦破掉就会伤到人的规则：
 *
 * - **说了愿意不等于已经加入**这句话在屏上。没有它，没被挑中的人会觉得被放鸽子
 * - **不感兴趣一步完成**。拒绝一旦要走两步，它就不再和愿意等重
 * - **屏上没有百分比、没有分数、没有排名**。知道自己是第几个只会让人退出
 * - 网络出问题时**说清没有替他答复任何人**。他最怕的是"我刚才那一下算不算"
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { SeedInbox } from "@/components/seed-inbox";
import type { components } from "@/lib/api-types";

type Seed = components["schemas"]["SeedOut"];

const SEED: Seed = {
  intent_id: "11111111-1111-4111-8111-111111111111",
  goal: "周六去后山拍流浪猫",
  said: "想找个人周六一起去后山拍猫，我有相机但不会剪",
  needs: ["剪辑"],
  offers: ["拍摄", "相机"],
  when: "2026-08-15T14:00:00",
  where: "东校区后山",
  team_min: 3,
  team_max: 4,
  from_name: "陈牧",
  why: ["你说过想参与剪辑", "你也常在东校区"],
  state: "delivered",
  my_note: null,
};

type Call = { url: string; method: string; body: { [k: string]: unknown } | null };

type Options = {
  seeds?: Partial<Seed>[];
  listStatus?: number;
  respondStatus?: number;
  /** 请求永远不回：用来看"还在取"的那一态。 */
  hang?: boolean;
};

function mockApi(opts: Options = {}): Call[] {
  const calls: Call[] = [];
  const reply = (body: unknown, status = 200) => ({
    ok: status < 300,
    status,
    json: async () => body,
  });
  const seeds: Seed[] = (opts.seeds ?? [{}]).map((s) => ({ ...SEED, ...s }));

  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      calls.push({ url, method, body });

      if (opts.hang) return new Promise<never>(() => {});
      if (url === "/api/me/seeds") {
        return opts.listStatus
          ? reply({ detail: "没连上" }, opts.listStatus)
          : reply(seeds);
      }
      if (url.endsWith(":respond")) {
        if (opts.respondStatus) return reply({ detail: "没连上" }, opts.respondStatus);
        const seed = seeds.find((s) => url.includes(s.intent_id)) ?? SEED;
        return reply({
          ...seed,
          state: body?.willing ? "willing" : "passed",
          my_note: body?.note ?? null,
        });
      }
      return reply(null, 404);
    }),
  );
  return calls;
}

const answers = (calls: Call[]) => calls.filter((c) => c.url.endsWith(":respond"));

const card = () => screen.findByRole("region", { name: SEED.goal });

beforeEach(() => vi.unstubAllGlobals());

it("还在取的时候是骨架，不是白屏", async () => {
  mockApi({ hang: true });
  render(<SeedInbox />);

  expect(await screen.findByRole("status", { name: "加载中" })).toBeTruthy();
});

it("信箱空的时候说得出下一步", async () => {
  // 空信箱最常见的原因不是"没人发事"，是他从没说过自己能做什么。
  // 只说"暂时没有"等于让他回来刷，而刷不出东西的人不会回来第三次。
  mockApi({ seeds: [] });
  render(<SeedInbox />);

  expect(await screen.findByText("现在没有人找你。")).toBeTruthy();
  expect(screen.getByRole("link", { name: "填一下我这边" }).getAttribute("href")).toBe(
    "/me/about",
  );
});

it("打不开的时候说清没有替他答复任何人", async () => {
  mockApi({ listStatus: 500 });
  render(<SeedInbox />);

  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain("不会替你答复任何人");
  expect(screen.getByRole("button", { name: "再试一次" })).toBeTruthy();
});

it("卡上是这件事的全部：做什么、什么时候、在哪、要几个人、缺什么", async () => {
  // 他要判断的是这件事值不值得参与。少给一样，他就只能靠"这个人看着靠不靠谱"决定。
  mockApi();
  render(<SeedInbox />);

  const one = await card();
  expect(within(one).getByText(/8 月 15 日/)).toBeTruthy();
  expect(within(one).getByText("东校区后山")).toBeTruthy();
  expect(within(one).getByText(/3–4 个人/)).toBeTruthy();
  expect(within(one).getByText("剪辑")).toBeTruthy();
  expect(within(one).getByText(/陈牧/)).toBeTruthy();
});

it("「为什么找到你」逐条列出，不折成一个数", async () => {
  mockApi();
  render(<SeedInbox />);

  const one = await card();
  for (const line of SEED.why) expect(within(one).getByText(line)).toBeTruthy();
});

it("「说了愿意不等于已经加入」就在按钮旁边", async () => {
  // 不说的代价是他以为自己已经答应了，然后在没被挑中时觉得被放了鸽子。
  mockApi();
  render(<SeedInbox />);

  const one = await card();
  expect(within(one).getByText(/说了愿意不等于已经加入/)).toBeTruthy();
  expect(within(one).getByRole("button", { name: "我愿意" })).toBeTruthy();
});

it("「这次不感兴趣」一步完成，不问为什么", async () => {
  // 要用摩擦力换的是承诺，不是拒绝——反过来做就是在换同意率。
  const calls = mockApi();
  render(<SeedInbox />);

  const one = await card();
  await userEvent.click(within(one).getByRole("button", { name: "这次不感兴趣" }));

  await waitFor(() => expect(answers(calls)).toHaveLength(1));
  expect(answers(calls)[0]!.body).toMatchObject({ willing: false, remind_me: false });
  expect(await screen.findByText(/这次就到这里/)).toBeTruthy();
});

it("「以后类似的叫我」是不感兴趣加一条线索，不是第三种表态", async () => {
  const calls = mockApi();
  render(<SeedInbox />);

  const one = await card();
  await userEvent.click(within(one).getByRole("button", { name: "以后类似的叫我" }));

  await waitFor(() => expect(answers(calls)).toHaveLength(1));
  expect(answers(calls)[0]!.body).toMatchObject({ willing: false, remind_me: true });
  expect(await screen.findByText(/以后有类似的事会再来找你/)).toBeTruthy();
});

it("愿意可以不写留言", async () => {
  // 要求写一句理由才能说愿意，会让人不敢点愿意；
  // 而一个不敢表态的人，对发起人等于不存在。
  const calls = mockApi();
  render(<SeedInbox />);

  const one = await card();
  await userEvent.click(within(one).getByRole("button", { name: "我愿意" }));

  await waitFor(() => expect(answers(calls)).toHaveLength(1));
  expect(answers(calls)[0]!.body).toMatchObject({ willing: true, note: null });
});

it("写了留言就原样带过去", async () => {
  const calls = mockApi();
  render(<SeedInbox />);

  const one = await card();
  await userEvent.click(within(one).getByRole("button", { name: "想先说一句" }));
  await userEvent.type(within(one).getByLabelText("想说的话"), "我剪过两支短片");
  await userEvent.click(within(one).getByRole("button", { name: "就这么说，我愿意" }));

  await waitFor(() => expect(answers(calls)).toHaveLength(1));
  expect(answers(calls)[0]!.body).toMatchObject({
    willing: true,
    note: "我剪过两支短片",
  });
});

it("答过的那张卡显示自己答了什么，不再问第二次", async () => {
  mockApi({ seeds: [{ state: "willing", my_note: "我周六下午都有空" }] });
  render(<SeedInbox />);

  const one = await card();
  expect(within(one).getByText("你说了愿意。")).toBeTruthy();
  expect(within(one).getByText(/我周六下午都有空/)).toBeTruthy();
  expect(within(one).queryAllByRole("button")).toHaveLength(0);
});

it("说不出为什么找到你的时候，照样能答复", async () => {
  // 降级：排序和解释那一层不在时，挡住答复的代价是他什么都做不了，
  // 而这件事本身没有任何变化。
  mockApi({ seeds: [{ why: [] }] });
  render(<SeedInbox />);

  const one = await card();
  expect(within(one).getByText(/现在说不出为什么找到你/)).toBeTruthy();
  expect(within(one).getByRole("button", { name: "我愿意" })).toBeTruthy();
});

it("没送出去的时候说出来，不假装他答过了", async () => {
  // 他以为答过了而对方没收到，是这一屏最贵的一种错。
  mockApi({ respondStatus: 500 });
  render(<SeedInbox />);

  const one = await card();
  await userEvent.click(within(one).getByRole("button", { name: "我愿意" }));

  expect((await screen.findByRole("alert")).textContent).toContain("没送出去");
  expect(within(one).getByRole("button", { name: "我愿意" })).toBeTruthy();
});

it("屏上没有百分比、没有分数、没有排名、没有几个人在跟他抢", async () => {
  // 知道自己是第几个只会让人退出，而这里本来就没有评价。
  // 两张卡：一张还没答，一张答过了。这两态是最容易漏出"你排第几"的地方。
  mockApi({
    seeds: [
      {},
      {
        intent_id: "22222222-2222-4222-8222-222222222222",
        goal: "周三晚上一起改简历",
        state: "willing",
      },
    ],
  });
  render(<SeedInbox />);

  await screen.findByRole("region", { name: "周三晚上一起改简历" });
  const text = document.body.textContent ?? "";
  expect(text).not.toMatch(/%|％/);
  expect(text).not.toMatch(/\d+\s*分|得分|匹配度|相似度/);
  expect(text).not.toMatch(/排名|第\s*\d+\s*(名|个)|竞争|人在等着|也说了愿意/);
});
