"use client";

/**
 * 演示模式下的「现在就配一轮」。
 *
 * ## 为什么这不只是测试工具
 *
 * 这个产品的核心循环里有两处**要等**：撮合窗口六小时、记忆回流两周。
 * 演示的时候没人会真等——而"等不了所以看不到"意味着**产品的一半没法被
 * 展示给任何人看**，包括评审、包括第一批用户、包括自己。
 *
 * `SimulatedClock` 从第一天就注入着，缺的一直只是一个能推它的入口。
 *
 * ## 为什么它敢出现在界面上
 *
 * 因为它**在生产里根本不存在**：`COFIELD_DEMO_MODE` 关掉时，
 * `/api/clock:advance` 那条路由不注册，探测不到。所以这不是一个
 * "权限不够就点不动"的按钮，是一个后端没有对应能力时**自己消失**的按钮。
 *
 * 组件启动时问一次 `/api/health`；问不到就当作生产，不显示。
 * **默认不显示**是刻意的——一个演示按钮出现在真实校园里，
 * 比它不出现在演示里糟得多。
 */

import { useEffect, useState } from "react";

import { currentPrincipal } from "@/lib/session";

const HOUR = 3600;

async function inDemoMode(signal?: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch("/api/health", { signal });
    if (!response.ok) return false;
    const body: { demo_mode?: string } = await response.json();
    return body.demo_mode === "true";
  } catch {
    return false;
  }
}

export function DemoFastForward({ onDone }: { onDone: () => void }) {
  const [available, setAvailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const stop = new AbortController();
    void inDemoMode(stop.signal).then(setAvailable);
    return () => stop.abort();
  }, []);

  if (!available) return null;

  const headers = {
    "Content-Type": "application/json",
    "X-Principal-Id": currentPrincipal(),
  };

  async function runNow() {
    setBusy(true);
    setFailed(false);
    try {
      // 先把钟推过一个窗口，再结算。两步都做才看得到结果——
      // 只结算不推钟，攒着的需求还没到点，会得到一个"什么都没发生"。
      await fetch(`/api/clock:advance?seconds=${7 * HOUR}`, {
        method: "POST",
        headers,
      });
      await fetch("/api/clearing:run", { method: "POST", headers });
      onDone();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  // **它长得像工具，不像产品的一部分。**
  //
  // 原来它是一张虚线卡，摆在这一屏最上面、标题正下方——那个位置是留给
  // "这一屏在说什么"的。一个写着「现在是演示」的框子占着它，等于对每一个
  // 打开这一屏的人说这不是真东西。
  //
  // 现在它压到最底下、缩成一行、去掉卡片的样子。能力一点没少，
  // 但它不再是这一屏的主角——**它本来也不是**。
  return (
    <div className="mt-10 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line-soft pt-4 text-[12px] text-ink-faint">
      <span>调试</span>
      <button
        type="button"
        onClick={runNow}
        disabled={busy}
        className="inline-flex min-h-[44px] items-center underline underline-offset-4 hover:text-ink disabled:opacity-50"
      >
        {busy ? "正在配…" : "现在就配一轮"}
      </button>
      {failed && (
        <p role="alert" className="mt-2 text-[13px] text-clash">
          这一轮没跑起来。再点一次试试——你说过的那几件事都还在。
        </p>
      )}
    </div>
  );
}
