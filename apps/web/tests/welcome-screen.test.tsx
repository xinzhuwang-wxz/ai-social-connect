/**
 * 欢迎屏的产品行为。
 *
 * 这一屏是**被认识的起点**：不填名字，一个人在候选里永远只是「同学f2a1」，
 * 没有人知道找到了谁。所以这里断言的重点是：
 *
 * - 没填名字不能进去
 * - 填了名字，请求里真的带上了
 * - 已经起过名的人不再被问一遍
 * - 存不下来时屏上说得出话，名字还在
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { WelcomeScreen } from "@/components/welcome-screen";

type Call = { url: string; method: string; body: unknown };

type Options = {
  namedSelf?: boolean;
  saveStatus?: number;
  profileStatus?: number;
};

function mockApi(opts: Options = {}): Call[] {
  const calls: Call[] = [];
  const reply = (body: unknown, status = 200) => ({
    ok: status < 300,
    status,
    json: async () => body,
  });

  const profile = {
    display_name: "同学f2a1",
    named_self: opts.namedSelf ?? false,
    skills: [],
    open_to: [],
    self_intro: null,
    zone: null,
    major: null,
    not_recognised: [],
  };

  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      calls.push({ url, method, body });

      if (url === "/api/me/profile" && method === "GET") {
        return opts.profileStatus
          ? reply({ detail: "没连上" }, opts.profileStatus)
          : reply(profile);
      }
      if (url === "/api/me/profile" && method === "PUT") {
        return opts.saveStatus
          ? reply({ detail: "没连上" }, opts.saveStatus)
          : reply({ ...profile, display_name: body?.display_name ?? profile.display_name, named_self: true });
      }
      return reply(null, 404);
    }),
  );
  return calls;
}

const saved = (calls: Call[]) =>
  calls.filter((c) => c.url === "/api/me/profile" && c.method === "PUT");

beforeEach(() => vi.unstubAllGlobals());

it("没填名字不能继续", async () => {
  // 空名字穿过去，别人看到的还是「同学f2a1」，一个字都认不出来。
  const calls = mockApi();
  render(<WelcomeScreen />);

  await screen.findByRole("button", { name: "就叫这个，进去" });
  await userEvent.click(screen.getByRole("button", { name: "就叫这个，进去" }));

  // 没有 PUT 请求发出
  expect(saved(calls)).toHaveLength(0);
  // 屏上有提示——不能静默拒绝
  expect(screen.getByRole("alert").textContent).toBeTruthy();
});

it("填了名字之后，请求里真的带上了 display_name", async () => {
  const calls = mockApi();
  render(<WelcomeScreen />);

  await screen.findByLabelText("你叫什么名字");
  await userEvent.type(screen.getByLabelText("你叫什么名字"), "陈小木");
  await userEvent.click(screen.getByRole("button", { name: "就叫这个，进去" }));

  await waitFor(() => expect(saved(calls)).toHaveLength(1));
  expect(saved(calls)[0]!.body).toMatchObject({ display_name: "陈小木" });
});

it("已经起过名的人不会被再问一遍", async () => {
  // named_self = true 意味着他已经告诉过我们他叫什么，再问是烦扰。
  mockApi({ namedSelf: true });
  render(<WelcomeScreen />);

  // 加载完之后，名字输入框不出现——组件走了重定向路径而不是展示表单。
  await waitFor(() => {
    expect(screen.queryByLabelText("你叫什么名字")).toBeNull();
  });
});

it("存不下来时屏上有话说，填的名字还在", async () => {
  // 静默失败是最坏的结果：用户以为填成功了，结果下次打开还是占位名。
  const calls = mockApi({ saveStatus: 500 });
  render(<WelcomeScreen />);

  await screen.findByLabelText("你叫什么名字");
  await userEvent.type(screen.getByLabelText("你叫什么名字"), "陈小木");
  await userEvent.click(screen.getByRole("button", { name: "就叫这个，进去" }));

  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain("没能存下来");

  // 填过的名字还在输入框里，不要让他重填一遍
  expect(
    (screen.getByLabelText("你叫什么名字") as HTMLInputElement).value,
  ).toBe("陈小木");
});
