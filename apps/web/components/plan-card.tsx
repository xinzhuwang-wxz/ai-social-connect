"use client";

/**
 * 行动确认卡。
 *
 * PRD 称它是**最重要的中间转化节点**：从一句模糊的"有空一起"，变成一项
 * 明确的共同承诺。在它之前，成局之后就直接掉进一堆待办，中间没有任何东西
 * 钉死"我们要做的到底是什么"。
 *
 * ## 三条产品判断决定了它长成这样
 *
 * 1. **缺什么要说得出是哪一样。** 「信息不全」等于让人自己去找；
 *    「还没写什么时候」直接就是下一步动作。
 * 2. **改了就得重新点头，而且要说出来。** 后端按内容摘要记点头，所以
 *    改动会让所有人的确认一起失效——界面必须**在他改之前**就说清这件事，
 *    否则他会以为自己只是改了个错别字。
 * 3. **等谁要指名道姓。** 「还差 2 个人」催不动任何人。
 *
 * ## 它长得比别的卡片正式一点，这是规格要求的
 *
 * PRD 的原话：「视觉比普通卡片稍正式……不要做得过于可爱」。正式感在这里
 * 是三条具体的做法，不是一种氛围：
 *
 * - **暖白底、深绿标题、极浅绿分区**——规格点名的三样
 * - **分成三段**：头（这是什么、还差谁）／明细（时间地点带什么）／
 *   承诺（那个按钮）。一张连成一片的卡读起来像便签，分了段才像一份约定
 * - **明细用 dt/dd 排成表**，一行一项、标签左对齐。它要看着像一份可以
 *   照着执行的东西，而不是一段话
 *
 * 界面文案不使用领域词汇（见 docs/07 语言映射表）。
 */

import { useEffect, useState } from "react";

import {
  confirmPlan,
  fetchPlan,
  savePlan,
  type Plan,
} from "@/lib/space";

/**
 * 手机上的点击区。规范给的按钮高度是 44–52px；这一屏最重的那一下
 * （「就这么办」）取上半段，并且在手机上占满一行——它是这张卡存在的理由。
 */
const PRIMARY =
  "inline-flex min-h-[48px] w-full items-center justify-center rounded-[16px] bg-accent px-5 text-[15px] font-medium text-paper disabled:opacity-40 sm:w-auto";
/** 只有文字的那一类。下划线常在，不靠 hover——手机上没有 hover。 */
const QUIET =
  "inline-flex min-h-[44px] items-center text-[15px] text-ink-soft underline underline-offset-4 hover:text-ink active:text-ink";
/**
 * 输入框。**16px 不是审美，是功能**：iOS Safari 对小于 16px 的输入框
 * 会在聚焦时自动放大整页，而且缩不回去——用户会以为页面坏了。
 * `datetime-local` 尤其，它是这张卡上最常被点开的一个。
 */
const FIELD =
  "min-h-[48px] w-full rounded-[10px] border border-line bg-paper px-3 py-3 text-[16px] outline-none placeholder:text-ink-faint focus:border-accent";

/** 「2026-08-15T14:00」——`datetime-local` 认这个，ISO 带时区它不认。 */
function forInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

function readable(iso: string | null | undefined): string {
  if (!iso) return "还没定";
  const d = new Date(iso);
  const week = "日一二三四五六"[d.getDay()];
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日 周${week} ${d.getHours()}:${String(
    d.getMinutes(),
  ).padStart(2, "0")}`;
}

export function PlanCard({
  spaceId,
  names,
  me,
  onChanged,
}: {
  spaceId: string;
  /** 身份 → 名字。等谁点头要指名道姓。 */
  names: Map<string, string>;
  /** 我自己。**"还差谁"里不该有我自己**——我该看到的是一个可以点的按钮，
   *  不是一句催我自己的话。 */
  me: string;
  onChanged?: () => void;
}) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [draft, setDraft] = useState({
    title: "",
    starts_at: "",
    place: "",
    bring: "",
    budget: "",
    change_note: "",
  });

  useEffect(() => {
    fetchPlan(spaceId).then(setPlan, () => setFailed(true));
  }, [spaceId]);

  function edit(current: Plan | null) {
    setDraft({
      title: current?.title ?? "",
      starts_at: forInput(current?.starts_at),
      place: current?.place ?? "",
      bring: current?.bring ?? "",
      budget: current?.budget ?? "",
      change_note: current?.change_note ?? "",
    });
    setEditing(true);
  }

  async function save() {
    setBusy(true);
    setFailed(false);
    try {
      setPlan(
        await savePlan(spaceId, {
          title: draft.title.trim() || "这次一起做的事",
          starts_at: draft.starts_at ? new Date(draft.starts_at).toISOString() : null,
          place: draft.place.trim() || null,
          bring: draft.bring.trim() || null,
          budget: draft.budget.trim() || null,
          change_note: draft.change_note.trim() || null,
        }),
      );
      setEditing(false);
      onChanged?.();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  async function nod() {
    setBusy(true);
    setFailed(false);
    try {
      setPlan(await confirmPlan(spaceId));
      onChanged?.();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  if (plan === null && !failed) {
    return <div aria-label="加载中" className="h-28 animate-pulse rounded-[16px] bg-line" />;
  }

  if (editing) {
    return (
      <section
        aria-label="这次怎么办"
        className="overflow-hidden rounded-[16px] border border-line bg-card shadow-[var(--shadow-card)]"
      >
        {/* 头一段：极浅绿的分区底，深绿标题。 */}
        <div className="border-b border-line-soft bg-accent-soft/45 px-4 py-4 sm:px-5">
          <h2 className="text-[18px] font-semibold text-brand">这次怎么办</h2>
          {plan?.nodded?.length ? (
            // **在他改之前就说清楚。** 事后才说，他会以为自己只是改了个错别字。
            <p className="mt-1 text-[13px] text-pending">
              已经有 {plan.nodded.length} 个人确认过了。改完要请他们再确认一次。
            </p>
          ) : null}
        </div>

        <div className="space-y-4 px-4 py-4 sm:px-5">
          <Field label="这次做什么">
            <input
              aria-label="这次做什么"
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              placeholder="周六去后山拍流浪猫"
              className={FIELD}
            />
          </Field>
          <Field label="什么时候">
            <input
              aria-label="什么时候"
              type="datetime-local"
              value={draft.starts_at}
              onChange={(e) => setDraft({ ...draft, starts_at: e.target.value })}
              className={FIELD}
            />
          </Field>
          <Field label="在哪集合">
            <input
              aria-label="在哪集合"
              value={draft.place}
              onChange={(e) => setDraft({ ...draft, place: e.target.value })}
              placeholder="北门地铁口"
              className={FIELD}
            />
          </Field>
          <Field label="要带什么" hint="不用带就空着">
            <input
              aria-label="要带什么"
              value={draft.bring}
              onChange={(e) => setDraft({ ...draft, bring: e.target.value })}
              placeholder="相机、充电宝"
              className={FIELD}
            />
          </Field>
          <Field label="大概多少钱" hint="说不清就空着，编一个数比不说更糟">
            <input
              aria-label="大概多少钱"
              value={draft.budget}
              onChange={(e) => setDraft({ ...draft, budget: e.target.value })}
              placeholder="车费 AA，大概 20"
              className={FIELD}
            />
          </Field>
          <Field label="有变怎么办" hint="临时变更是最常见的翻车方式">
            <input
              aria-label="有变怎么办"
              value={draft.change_note}
              onChange={(e) => setDraft({ ...draft, change_note: e.target.value })}
              placeholder="下雨就改到下周同一时间"
              className={FIELD}
            />
          </Field>
        </div>

        <div className="flex flex-wrap items-center gap-3 border-t border-line-soft bg-accent-soft/25 px-4 py-4 sm:px-5">
          <button
            type="button"
            disabled={busy}
            onClick={() => void save()}
            className={PRIMARY}
          >
            {busy ? "存着…" : "存下来"}
          </button>
          <button type="button" onClick={() => setEditing(false)} className={QUIET}>
            先不改了
          </button>
          {failed && (
            <span role="alert" className="text-[14px] text-clash">
              没存上，再试一次——你填的还在。
            </span>
          )}
        </div>
      </section>
    );
  }

  if (!plan?.exists) {
    return (
      <section
        aria-label="这次怎么办"
        className="rounded-[16px] border border-dashed border-line bg-card p-4 sm:p-5"
      >
        <h2 className="text-[18px] font-semibold text-brand">这次怎么办</h2>
        <p className="mt-1 text-[14px] text-ink-soft">
          把时间、地点、带什么写下来，大家各自点个头——从"有空一起"变成
          "就这么定了"。
        </p>
        <button type="button" onClick={() => edit(null)} className={PRIMARY + " mt-4"}>
          写一张
        </button>
      </section>
    );
  }

  const waiting = (plan.waiting_on ?? []).filter((id) => id !== me);

  return (
    <section
      aria-label="这次怎么办"
      className={
        "overflow-hidden rounded-[16px] border bg-card shadow-[var(--shadow-card)] " +
        (plan.confirmed ? "border-settled/40" : "border-line")
      }
    >
      {/* 第一段：这是什么，以及还差谁。**极浅绿的分区底 + 深绿标题**——
          全员确认之后底色转成实打实的那一档绿：这件事成了。 */}
      <div
        className={
          "px-4 py-4 sm:px-5 " +
          (plan.confirmed ? "bg-settled-soft" : "bg-accent-soft/45")
        }
      >
        <h2 className="text-[18px] font-semibold text-brand">{plan.title}</h2>
        <p className="mt-1 text-[13px] text-ink-soft">
          {plan.confirmed
            ? "都确认了，就这么办。"
            : waiting.length > 0
              ? `还差${waiting.map((id) => names.get(id) ?? "一个人").join("、")}确认。`
              : plan.i_nodded
                ? "就等那天了。"
                : "写好了，等你点头。"}
        </p>
      </div>

      {/* 第二段：明细。一行一项，标签左对齐——它要看着像一份能照着执行的
          东西，而不是一段话。 */}
      <dl className="divide-y divide-line-soft border-t border-line-soft px-4 sm:px-5">
        <Row term="什么时候" value={readable(plan.starts_at)} />
        <Row term="在哪集合" value={plan.place || "还没定"} />
        {plan.bring && <Row term="要带什么" value={plan.bring} />}
        {plan.budget && <Row term="大概多少钱" value={plan.budget} />}
        {plan.change_note && <Row term="有变怎么办" value={plan.change_note} />}
      </dl>

      {(plan.missing ?? []).length > 0 && (
        // 说得出缺的是哪一样。「信息不全」等于让人自己去找。
        <p className="px-4 pt-3 pb-1 text-[13px] text-pending sm:px-5">
          还差{(plan.missing ?? []).join("、")}没写。写清了才能确认。
        </p>
      )}

      {/* 第三段：承诺。**自己一块地**，不和明细挤在一起——
          这一下按下去就是一句"我答应了"。 */}
      <div className="flex flex-wrap items-center gap-3 border-t border-line-soft bg-accent-soft/25 px-4 py-4 sm:px-5">
        {plan.i_nodded ? (
          <span className="text-[15px] font-medium text-settled">你确认过了</span>
        ) : (
          <button
            type="button"
            disabled={busy || (plan.missing ?? []).length > 0}
            onClick={() => void nod()}
            className={PRIMARY}
          >
            就这么办
          </button>
        )}
        <button type="button" onClick={() => edit(plan)} className={QUIET}>
          改一改
        </button>
        {failed && (
          <span role="alert" className="text-[14px] text-clash">
            没成，再试一次。
          </span>
        )}
      </div>
    </section>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-[13px] text-ink-soft">{label}</span>
      {hint && <span className="ml-2 text-[12px] text-ink-faint">{hint}</span>}
      <div className="mt-1.5">{children}</div>
    </label>
  );
}

function Row({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex gap-4 py-3">
      <dt className="w-[68px] shrink-0 text-[13px] text-ink-faint sm:w-20">{term}</dt>
      <dd className="min-w-0 flex-1 text-[16px]">{value}</dd>
    </div>
  );
}
