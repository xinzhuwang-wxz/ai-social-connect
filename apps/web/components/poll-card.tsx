"use client";

/**
 * 要选一个。
 *
 * PRD 把 AI 推进列为最核心的功能，而投票是它的主要手段：讨论停滞时给出
 * **明确而有限的选择**。在它之前助手只能把一件未定的事变成一张话题卡——
 * 它问得出问题，收不拢答案。
 *
 * ## 三条判断
 *
 * 1. **票数实时可见，而且指名道姓。** 藏着计票会让人觉得系统在操纵；
 *    而这是一个五六个人的组，藏起来他们也猜得到，猜出来的版本往往更伤人。
 * 2. **票不关门。** 票最多的那个不会自己变成"定了"——一次投票是表达，
 *    不是承诺（不变量 11）。关上它仍然要有人点头。
 * 3. **平票就说平票。** 替人破局等于替人做决定，而这一步的全部意义正是
 *    把决定交回给人。
 */

import { useEffect, useState } from "react";

import { castVote, fetchPolls, type Poll } from "@/lib/space";

export function Polls({
  spaceId,
  onChanged,
}: {
  spaceId: string;
  onChanged?: () => void;
}) {
  const [polls, setPolls] = useState<Poll[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetchPolls(spaceId).then(setPolls, () => setFailed(true));
  }, [spaceId]);

  async function pick(itemId: string, choice: number) {
    setBusy(true);
    setFailed(false);
    try {
      const next = await castVote(spaceId, itemId, choice);
      setPolls((all) =>
        (all ?? []).map((p) => (p.item_id === next.item_id ? next : p)),
      );
      onChanged?.();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  const open = (polls ?? []).filter((p) => !p.settled);
  if (open.length === 0) return null;

  return (
    <div className="space-y-4">
      {open.map((poll) => {
        const total = poll.tally.reduce((n, t) => n + t.votes, 0);
        return (
          <section
            key={poll.item_id}
            aria-label={poll.question}
            className="rounded-[16px] border border-line bg-card p-4 shadow-[var(--shadow-card)] sm:p-5"
          >
            <h2 className="text-[18px] font-semibold">{poll.question}</h2>
            <p className="mt-1 text-[14px] text-ink-soft">
              选一个。投票只是让大家先看清彼此想去哪，最后仍然要有人点这个头。
            </p>

            <ul className="mt-4 space-y-2">
              {poll.tally.map((t, i) => {
                const mine = poll.my_choice === i;
                return (
                  <li key={t.label}>
                    {/* 整行都是点击区，不是行尾一个小圆点。选中与否靠边框和
                        底色分——`hover:` 在手机上永远不发生，选中态不能只
                        活在悬停里；`active:` 才是拇指按下去时看得见的那一下。 */}
                    <button
                      type="button"
                      disabled={busy}
                      aria-pressed={mine}
                      onClick={() => void pick(poll.item_id, i)}
                      className={
                        "block min-h-[52px] w-full rounded-[10px] border px-4 py-3 text-left disabled:opacity-50 " +
                        (mine
                          ? "border-accent bg-accent-soft"
                          : "border-line active:border-accent active:bg-accent-soft/40 sm:hover:border-accent")
                      }
                    >
                      <span className="flex items-baseline justify-between gap-3">
                        <span className={"text-[16px] " + (mine ? "font-medium" : "")}>
                          {t.label}
                        </span>
                        <span className="shrink-0 text-[13px] text-ink-soft">
                          {t.votes > 0 ? `${t.votes} 票` : "还没人选"}
                        </span>
                      </span>
                      {/* 一条比例。**不写百分比**——五个人里两个人选它，
                          说"40%"不如画出来直观，也不会引出"凭什么是 40%"。 */}
                      <span
                        aria-hidden
                        className="mt-2 block h-1.5 rounded-full bg-line"
                      >
                        <span
                          className="block h-1.5 rounded-full bg-accent"
                          style={{
                            width: total ? `${(t.votes / total) * 100}%` : "0%",
                          }}
                        />
                      </span>
                      {(t.by ?? []).length > 0 && (
                        <span className="mt-1.5 block text-[13px] text-ink-faint">
                          {(t.by ?? []).join("、")}
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>

            <p className="mt-3 text-[14px] text-ink-soft">
              {(poll.waiting_on ?? []).length > 0
                ? `还差${(poll.waiting_on ?? []).join("、")}没选。`
                : poll.leading
                  ? `现在是「${poll.leading}」多。还要有人点头才算定下来。`
                  : "都选了，票数打平——你们自己定一个吧。"}
            </p>
            {failed && (
              <p role="alert" className="mt-2 text-[13px] text-clash">
                这一票没投上，再试一次。
              </p>
            )}
          </section>
        );
      })}
    </div>
  );
}
