"use client";

/**
 * 到那天了，以及做完了没有。
 *
 * PRD 的「线下转化」这一段。产品能把人凑齐、能定下计划，然后到此为止——
 * 而 PRD 说得很清楚：这个产品不以"双方聊起来"为终点，以**真的一起完成了
 * 一次行动**为终点。
 *
 * ## 三条判断
 *
 * 1. **行动前一天才出现。** 一个常驻的"我出发了"按钮在事情还没定下来的
 *    时候只是噪音，而噪音会让人学会忽略这一整块。
 * 2. **不做持续定位。** PRD 自己写的：首版只要地址入口和必要状态。
 *    一个为了"看谁到了"常开的定位权限，换来的信息量还不如一句"我到了"。
 * 3. **完成要全员点头。** 一个人说做完了就标记完成，等于让他替所有人宣布，
 *    而这件事会写进每个人的森林。
 */

import { useEffect, useState } from "react";

import {
  fetchDayOf,
  markDone,
  setDayOf,
  unmarkDone,
  type DayOf as DayOfState,
} from "@/lib/space";

const STATES = [
  { key: "ready", label: "准备好了" },
  { key: "leaving", label: "出发了" },
  { key: "arrived", label: "到了" },
] as const;

/**
 * 手机上的点击区。规范给的按钮高度是 44–52px。
 *
 * 这一屏尤其不能小：用它的人正**站在路上、单手握着手机**——那是一天里
 * 手最不稳的时候，而这几个按钮偏偏是最需要一次点中的。
 */
const PRIMARY =
  "inline-flex min-h-[48px] w-full items-center justify-center rounded-[16px] bg-accent px-5 text-[15px] font-medium text-paper disabled:opacity-40 sm:w-auto";
const SECONDARY =
  "inline-flex min-h-[44px] items-center justify-center rounded-[16px] border border-line bg-card px-4 text-[15px] disabled:opacity-40";
/** 输入框 16px：iOS Safari 对更小的输入框会自动放大整页，而且缩不回去。 */
const FIELD =
  "mt-1.5 min-h-[48px] w-full rounded-[10px] border border-line bg-paper px-3 py-3 text-[16px] outline-none placeholder:text-ink-faint focus:border-accent";

export function DayOfCard({
  spaceId,
  names,
  onChanged,
}: {
  spaceId: string;
  names: Map<string, string>;
  onChanged?: () => void;
}) {
  const [day, setDay] = useState<DayOfState | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [saying, setSaying] = useState(false);
  const [note, setNote] = useState("");

  useEffect(() => {
    fetchDayOf(spaceId).then(setDay, () => setFailed(true));
  }, [spaceId]);

  async function run(work: () => Promise<DayOfState>) {
    setBusy(true);
    setFailed(false);
    try {
      setDay(await work());
      onChanged?.();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  // 还没到那天，或者已经全部说完做完了——这一块就不该占地方。
  if (!day || (!day.active && !day.i_marked_done && !day.all_done)) return null;

  const waiting = day.done_waiting_on ?? [];

  return (
    <section
      aria-label="到那天了"
      className="rounded-[16px] border border-line bg-card p-4 shadow-[var(--shadow-card)] sm:p-5"
    >
      <h2 className="text-[18px] font-semibold">到那天了</h2>
      <p className="mt-1 text-[14px] text-ink-soft">
        {day.where ? `在${day.where}集合。` : "集合地点还没写。"}
        {day.bring ? `记得带${day.bring}。` : ""}
      </p>
      {day.change_note && (
        <p className="mt-1 text-[13px] text-ink-faint">有变的话：{day.change_note}</p>
      )}

      {/* 三档排成等宽的三格：拇指不用瞄，落在哪一格都点得中。 */}
      <div className="mt-4 grid grid-cols-3 gap-2">
        {STATES.map((s) => (
          <button
            key={s.key}
            type="button"
            disabled={busy}
            aria-pressed={day.my_state === s.key}
            onClick={() => void run(() => setDayOf(spaceId, s.key))}
            className={
              "inline-flex min-h-[48px] items-center justify-center rounded-full border px-2 text-[15px] disabled:opacity-40 " +
              (day.my_state === s.key
                ? "border-accent bg-accent-soft font-medium text-accent"
                : "border-line text-ink-soft")
            }
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* 「临时有变」不和那三档并排：它不是一个进度，是一次插话。
          底色和边框常在，不靠 hover 才变色——手机上没有 hover，
          一个只在悬停时才认得出来的警示按钮等于没有警示。 */}
      <button
        type="button"
        disabled={busy}
        onClick={() => setSaying(!saying)}
        aria-expanded={saying}
        className={
          "mt-2 inline-flex min-h-[44px] w-full items-center justify-center rounded-full border px-4 text-[15px] disabled:opacity-40 sm:w-auto " +
          (saying
            ? "border-clash bg-pending-soft text-clash"
            : "border-line text-ink-soft active:border-clash active:text-clash")
        }
      >
        临时有变
      </button>

      {saying && (
        <div className="mt-3">
          <label className="block">
            <span className="text-[13px] text-ink-soft">怎么了？</span>
            {/* 一个不说原因的「临时有变」只会让所有人干着急。 */}
            <input
              aria-label="怎么了？"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="路上堵了，晚二十分钟"
              className={FIELD}
            />
          </label>
          <button
            type="button"
            disabled={busy || !note.trim()}
            onClick={() =>
              void run(() => setDayOf(spaceId, "changed", note.trim())).then(() => {
                setSaying(false);
                setNote("");
              })
            }
            className={SECONDARY + " mt-2 w-full sm:w-auto"}
          >
            告诉大家
          </button>
        </div>
      )}

      {(day.standings ?? []).length > 0 && (
        <ul className="mt-4 space-y-1.5 border-t border-line-soft pt-3">
          {(day.standings ?? []).map((s) => (
            <li key={s.principal_id} className="text-[15px]">
              <span className="text-ink-soft">{s.display_name}</span>
              <span className="ml-2">{s.word}</span>
              {s.note && <span className="ml-2 text-[13px] text-ink-faint">{s.note}</span>}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line-soft pt-4">
        {day.all_done ? (
          <span className="text-[15px] text-settled">大家都说做完了。</span>
        ) : day.i_marked_done ? (
          <>
            <span className="text-[15px] text-settled">
              你说做完了。还差
              {waiting.map((id) => names.get(id) ?? "一个人").join("、")}。
            </span>
            {/* 不给收回的路，人就不敢点——而不敢点会让这一步整个失效。
                所以它也得有 44px：一个点不中的后悔药等于没有后悔药。 */}
            <button
              type="button"
              disabled={busy}
              onClick={() => void run(() => unmarkDone(spaceId))}
              className="inline-flex min-h-[44px] items-center text-[14px] text-ink-faint underline underline-offset-4 hover:text-ink active:text-ink"
            >
              点错了
            </button>
          </>
        ) : (
          <button
            type="button"
            disabled={busy}
            onClick={() => void run(() => markDone(spaceId))}
            className={PRIMARY}
          >
            我这边做完了
          </button>
        )}
        {failed && (
          <span role="alert" className="text-[15px] text-clash">
            没成，再试一次。
          </span>
        )}
      </div>
    </section>
  );
}
