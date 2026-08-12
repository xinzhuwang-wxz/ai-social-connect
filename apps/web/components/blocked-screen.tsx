"use client";

/**
 * 第五屏：还差这几件事。
 *
 * 这一屏最容易被做成一句"暂无结果"，而那正是用户流失的地方。四条判断：
 *
 * 1. **把挫败换成一个具体的下一步。** 不写"很遗憾"，那是安慰；也不写
 *    "未找到匹配结果"，那是报错。两种都没告诉用户接下来能做什么。
 * 2. **每个可放宽项带真数字。** "可以试试放宽条件"等于什么都没说；
 *    "先不限校区的话能多出 137 个人"才是一个能做的决定。后端算不出来时
 *    如实说算不出来——**不估**，一个编出来的数字会被用户当真去改需求。
 * 3. **不建议的项照样列出来。** 不列等于替用户做决定。列出来，同时说清
 *    担心的是什么，判断权还在他手上。
 * 4. **每个下一步都必须真的能做。** 列一个点了没反应的按钮，比不列更让人挫败。
 *
 * 界面文案不使用领域词汇（见 docs/07 语言映射表）。
 */

import { useCallback, useEffect, useState } from "react";

import type { Intent } from "@/lib/api";
import { blockedFor, fetchIntent, type Blocked, type NextStep, type Relaxation } from "@/lib/matching";

import { ReviseCard } from "./waiting-screen";

export function BlockedScreen({ intentId }: { intentId: string }) {
  const [blocked, setBlocked] = useState<Blocked | null>(null);
  const [failed, setFailed] = useState(false);
  // 拿不到这条需求本身不该拖垮整屏：卡在哪、放宽什么都还说得出来，
  // 只是"改一改"要退成一个链接。
  const [intent, setIntent] = useState<Intent | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async () => {
    setFailed(false);
    setBlocked(null);
    void fetchIntent(intentId)
      .then(setIntent)
      .catch(() => setIntent(null));
    try {
      setBlocked(await blockedFor(intentId));
    } catch {
      setFailed(true);
    }
  }, [intentId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (failed) {
    return (
      <section role="alert" className="rounded-[16px] border border-line bg-card p-5">
        <p className="text-[15px]">现在查不到这次卡在哪。</p>
        <p className="mt-1 text-[13px] text-ink-soft">
          这件事还在队里，下一轮照样会再试一次。
        </p>
        <button
          type="button"
          onClick={() => void load()}
          className="mt-4 rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-paper"
        >
          再看一次
        </button>
      </section>
    );
  }

  if (blocked === null) {
    return (
      <div className="space-y-3" aria-label="加载中">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-20 animate-pulse rounded-[16px] bg-line" />
        ))}
      </div>
    );
  }

  // 空态：后端连卡在哪都说不出来。仍然要给一条能走的路。
  if (blocked.causes.length === 0 && blocked.relaxations.length === 0) {
    return (
      <section className="rounded-[16px] border border-line bg-card p-5">
        <p className="text-[15px]">{blocked.statement || "这一轮没能凑出一个组。"}</p>
        <p className="mt-1 text-[13px] text-ink-soft">
          这次没看出是卡在哪一条上。人多起来以后往往就成了——这件事会留在队里。
        </p>
        <a
          href="/waiting"
          className="mt-4 inline-block rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-paper"
        >
          去看下次什么时候配
        </a>
      </section>
    );
  }

  const best = bestOf(blocked.relaxations);

  return (
    <div>
      <section aria-label="卡在哪" className="rounded-[16px] border border-line bg-card p-5">
        <p className="text-[15px]">{blocked.statement}</p>
        {blocked.causes.length > 0 && (
          <ul className="mt-3 space-y-1">
            {blocked.causes.map((cause) => (
              <li key={cause} className="text-[14px] text-ink-soft">
                · {cause}
              </li>
            ))}
          </ul>
        )}
      </section>

      {blocked.relaxations.length > 0 && (
        <section aria-label="改一改的话" className="mt-6">
          <h2 className="text-[16px] font-medium">改一改的话</h2>
          <ul className="mt-3 space-y-3">
            {blocked.relaxations.map((r) => (
              <RelaxationRow key={r.field_name} relaxation={r} best={r === best} />
            ))}
          </ul>
        </section>
      )}

      {blocked.next_steps.length > 0 && (
        <section aria-label="下一步" className="mt-6">
          <h2 className="text-[16px] font-medium">现在能做的</h2>
          <div className="mt-3 space-y-2">
            {blocked.next_steps.map((step) => (
              <StepRow
                key={step.kind}
                step={step}
                intent={intent}
                open={open === step.kind}
                onToggle={() => setOpen(open === step.kind ? null : step.kind)}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

/** 建议里收益最大的那一个。默认标出来——用户不该自己去比几个数字。 */
function bestOf(relaxations: Relaxation[]): Relaxation | null {
  return relaxations.reduce<Relaxation | null>(
    (best, r) =>
      r.advisable && r.gains > 0 && (best === null || r.gains > best.gains) ? r : best,
    null,
  );
}

function RelaxationRow({ relaxation, best }: { relaxation: Relaxation; best: boolean }) {
  const { invitation, gains, advisable, caution } = relaxation;
  return (
    <li
      aria-label={invitation}
      className={`rounded-[16px] border bg-card p-4 ${advisable ? "border-line" : "border-pending"}`}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[15px]">{invitation}</span>
        {best && (
          <span className="rounded-[4px] bg-accent-soft px-1.5 py-0.5 text-[11px] text-accent">
            这一项最管用
          </span>
        )}
      </div>
      <p className="mt-1 text-[14px] text-ink-soft">
        {gains > 0 ? `能多出 ${gains} 个人` : "这一项现在算不出能多出多少人"}
      </p>
      {!advisable && (
        <p className="mt-2 rounded-[8px] bg-paper px-3 py-2 text-[13px] text-pending">
          不建议：{caution || "这么改会让这件事更容易出问题。"}
        </p>
      )}
    </li>
  );
}

/**
 * 一个下一步。点开之后必须真的发生一件事。
 *
 * 「通知我」和「让社团找找」后端都还没有入口（见任务返回里的接口缺口）。
 * 与其做两个假按钮，不如给出这两件事眼下真实的样子：一条一直在队里等的记录，
 * 和一段可以自己发出去的话。
 */
function StepRow({
  step,
  intent,
  open,
  onToggle,
}: {
  step: NextStep;
  intent: Intent | null;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="rounded-[16px] border border-line bg-card">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="w-full px-4 py-3 text-left text-[15px] hover:text-accent"
      >
        {step.invitation}
      </button>
      {open && (
        <div className="border-t border-line px-4 py-3">
          <StepBody step={step} intent={intent} />
        </div>
      )}
    </div>
  );
}

function StepBody({ step, intent }: { step: NextStep; intent: Intent | null }) {
  if (step.kind === "revise") {
    if (intent === null) {
      // 降级：调不出这条需求的内容，就不假装能在这里改。
      return (
        <div>
          <p className="text-[14px] text-ink-soft">现在调不出这件事的内容，改不了。</p>
          <a href="/waiting" className="mt-2 inline-block text-[14px] underline underline-offset-4">
            去等下一轮
          </a>
        </div>
      );
    }
    return <ReviseCard intent={intent} />;
  }

  if (step.kind === "wait_for_supply") {
    return (
      <div>
        <p className="text-[14px] text-ink-soft">
          这件事已经在队里了，每一轮都会再试一次。你不用守着。
        </p>
        <a href="/waiting" className="mt-2 inline-block text-[14px] underline underline-offset-4">
          去看下次什么时候配
        </a>
      </div>
    );
  }

  return <Share text={message(step.kind, intent)} />;
}

function message(kind: string, intent: Intent | null): string {
  const goal = intent?.content.goal ?? "";
  const needs = intent?.content.needs.join("、") ?? "";
  const what = goal ? `我在做：${goal}。` : "我在攒一个小队。";
  const lack = needs ? `还缺${needs}。` : "";
  return kind === "ask_organizers"
    ? `${what}${lack}社团里有合适的人吗？`
    : `${what}${lack}你有空吗？或者认识合适的人吗？`;
}

/** 一段可以直接发出去的话。发给谁由用户自己决定——系统不替他联系任何人。 */
function Share({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const canCopy = typeof navigator !== "undefined" && !!navigator.clipboard;
  return (
    <div>
      <textarea
        readOnly
        value={text}
        rows={3}
        aria-label="可以直接发出去的话"
        className="w-full resize-none rounded-[8px] border border-line bg-paper p-3 text-[14px]"
      />
      {canCopy && (
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard.writeText(text).then(
              () => setCopied(true),
              () => setCopied(false),
            );
          }}
          className="mt-2 rounded-[12px] border border-line px-3 py-1.5 text-[13px] text-ink-soft hover:border-accent hover:text-ink"
        >
          {copied ? "复制好了" : "复制这段话"}
        </button>
      )}
    </div>
  );
}
