"use client";

/**
 * 第一次打开时的欢迎屏。
 *
 * ## 这一屏解决的是什么问题
 *
 * 系统静默给每个新人分配一个占位名（「同学f2a1」），
 * 别人在候选里看到的是那串字母——这条信息量约等于零，
 * 没有人会因为「同学f2a1会剪辑」而去找他。
 *
 * 这一屏只做一件事：让他告诉我们他叫什么。
 * 填完就能进去，没有其他门槛。
 *
 * ## 已经起过名的人
 *
 * `named_self` 是服务端的判断：这个人有没有主动告诉过我们他叫什么。
 * true = 已经填过，直接跳走，不再问。
 *
 * ## 界面文案不使用领域词汇（见 docs/07 语言映射表）
 */

import { useEffect, useState } from "react";

import { api, type Profile } from "@/lib/api";

type Phase = "loading" | "ready" | "saving" | "failed";

export function WelcomeScreen() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [displayName, setDisplayName] = useState("");
  /** 名字为空时点了「进去」，告诉他缺什么，而不是静默拒绝。 */
  const [nameError, setNameError] = useState<string | null>(null);

  useEffect(() => {
    api
      .profile()
      .then((profile: Profile) => {
        if (profile.named_self) {
          // 已经起过名，不再打扰他——直接进首页。
          window.location.replace("/");
          return;
        }
        setPhase("ready");
      })
      .catch(() => setPhase("failed"));
  }, []);

  async function save() {
    const trimmed = displayName.trim();
    if (!trimmed) {
      setNameError("先告诉我你叫什么");
      return;
    }
    setPhase("saving");
    setNameError(null);
    try {
      // display_name 最长 20 字，超出部分截断。
      await api.saveProfile({ display_name: trimmed.slice(0, 20) });
      window.location.replace("/");
    } catch {
      setPhase("failed");
    }
  }

  if (phase === "loading") {
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 py-16">
        <div className="space-y-3" aria-label="加载中">
          <div className="h-8 w-48 animate-pulse rounded-[10px] bg-line" />
          <div className="h-4 w-72 animate-pulse rounded-[10px] bg-line" />
        </div>
      </main>
    );
  }

  if (phase === "failed" && displayName === "") {
    // 初始加载失败：Profile 请求本身没回来。
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 py-16">
        <p className="text-[15px]">现在打不开这一页。</p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="mt-4 inline-flex min-h-[44px] items-center rounded-[16px] border border-line px-5 text-[15px]"
        >
          再试一次
        </button>
      </main>
    );
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6 py-16">
      <header className="mb-10">
        {/* 一句话说清来这里能得到什么，不用技术词汇，不用感叹号。 */}
        <h1 className="text-[28px] font-bold leading-tight tracking-tight text-brand">
          找到一起做事的人
        </h1>
        <p className="mt-3 text-[16px] leading-relaxed text-ink-soft">
          说一件想做的事，我们帮你找同学来组队。
          先告诉我你叫什么，别人认识你才知道找到了谁。
        </p>
      </header>

      <section>
        <label className="block">
          <span className="text-[14px] text-ink-soft">你叫什么名字</span>
          <input
            type="text"
            aria-label="你叫什么名字"
            value={displayName}
            onChange={(e) => {
              setDisplayName(e.target.value);
              if (nameError) setNameError(null);
            }}
            maxLength={20}
            placeholder="比如：陈小木"
            autoComplete="nickname"
            className="mt-2 w-full rounded-[16px] border border-line bg-card px-4 py-3 text-[16px] outline-none placeholder:text-ink-faint focus:border-accent"
          />
        </label>
        {/* 校验错误放在输入框正下方，触屏上别让用户找报错在哪。 */}
        {nameError && (
          <p role="alert" className="mt-2 text-[14px] text-clash">
            {nameError}
          </p>
        )}
      </section>

      <button
        type="button"
        onClick={save}
        disabled={phase === "saving"}
        className="mt-6 inline-flex min-h-[52px] w-full items-center justify-center rounded-[16px] bg-accent px-5 text-[16px] font-semibold text-paper disabled:opacity-50 active:opacity-80"
      >
        {phase === "saving" ? "正在进入…" : "就叫这个，进去"}
      </button>

      {/* 存失败的错误和校验错误是两件事，分开显示，不要合并。 */}
      {phase === "failed" && displayName !== "" && (
        <p role="alert" className="mt-4 text-[14px] text-clash">
          没能存下来，再试一次——你填的名字还在。
        </p>
      )}
    </main>
  );
}
