"use client";

/**
 * 首屏：想做点什么。
 *
 * 两条产品规则在这一屏上体现得最直接：
 *
 * 1. **首屏不是空输入框。** 场景卡来自行动类别注册表，新增类别时这里自动
 *    多一张卡。输入框的 placeholder 是一句完整的好例子，起示范作用。
 * 2. **抽取只产出草稿。** 整理出来的卡片是给用户校对的，用户不点"就这样"，
 *    什么都不会开始找人。
 *
 * 界面文案不使用领域词汇（见 docs/07 语言映射表）。
 */

import { useEffect, useState, type ReactNode } from "react";
import {
  ApiError,
  api,
  toContentIn,
  type ActionKind,
  type CompileResult,
  type Conflict,
  type Intent,
} from "@/lib/api";
import { myEvents } from "@/lib/me";
import type { components } from "@/lib/api-types";

/** 「这条给谁看见」的取值。**从契约派生**，不手写。 */
type Reach = components["schemas"]["Reach"];

type Phase = "idle" | "compiling" | "checking" | "saving" | "done";

/**
 * 主按钮。**最终形态是手机**，所以尺寸从拇指开始算：48px 高、窄屏独占一行。
 * 两个按钮并排挤在 390px 宽的屏上，点错的那一次没有撤销。
 */
const PRIMARY =
  "inline-flex min-h-[48px] w-full items-center justify-center rounded-[16px] bg-accent px-5 text-[15px] font-semibold text-paper active:opacity-80 disabled:bg-line-soft disabled:text-ink-faint sm:w-auto";

/**
 * 次按钮。下划线是**常态**而不是悬停才出现的东西——手机上没有 hover，
 * 靠 hover 才现形的可点性在触屏上等于不存在。
 */
const QUIET =
  "inline-flex min-h-[44px] items-center text-[15px] text-ink-soft underline underline-offset-4 active:text-ink hover:text-ink";

export default function Page() {
  const [kinds, setKinds] = useState<ActionKind[] | null>(null);
  const [kindsFailed, setKindsFailed] = useState(false);
  const [expression, setExpression] = useState("");
  const [compiled, setCompiled] = useState<CompileResult | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [saved, setSaved] = useState<Intent | null>(null);
  const [reach, setReach] = useState<Reach>("campus");
  /** 和我一起做过事的人有几个。**只用来判断"是不是零"**——
   *  零的时候「只问一起做过事的人」是一条走不通的路，要在他选之前说。 */
  const [knownCount, setKnownCount] = useState(0);
  /** 我叫什么。**刚在第一屏填完名字的人，第二屏应该认得他**——
   *  不认得的话，那一步会显得像一道没有用的手续。 */
  const [myName, setMyName] = useState("");

  useEffect(() => {
    // 从「照这个再来一次」过来的，把上次的目标预填进去。
    // **只预填，不自动整理**——他多半要改，而替他按下"整理一下"
    // 等于替他决定了这次要做的和上次一样。
    const again = new URLSearchParams(window.location.search).get("again");
    if (again) setExpression(again);
  }, []);

  useEffect(() => {
    // 名字拿不到就不叫名字，不影响这一屏能不能用。
    api.profile().then(
      (me) => setMyName(me.named_self ? me.display_name : ""),
      () => setMyName(""),
    );
  }, []);

  useEffect(() => {
    // 拿不到就当零：这一栏只影响一句提示，为它把整屏拦住不值得。
    myEvents()
      .then((events) => {
        const names = new Set(
          events.filter((e) => !e.left_at).flatMap((e) => e.with_others),
        );
        setKnownCount(names.size);
      })
      .catch(() => setKnownCount(0));
  }, []);

  useEffect(() => {
    api
      .actionKinds()
      .then(setKinds)
      .catch(() => setKindsFailed(true));
  }, []);

  const placeholder =
    kinds?.find((k) => k.key === "creative_work")?.starter.example ??
    "比如：我想做一个关于校园流浪猫的一分钟短片，周五前完成。我会写脚本，但不认识会拍摄和剪辑的人";

  async function compile(text: string) {
    setPhase("compiling");
    setError(null);
    setConflicts([]);
    try {
      const result = await api.compile(text);
      setCompiled(result);
      setConflicts(result.conflicts);
      setPhase("checking");
    } catch (e) {
      // 读不懂不能让人卡住——退回手填，原话保留。
      setError(
        e instanceof ApiError && e.status === 422
          ? "没能读懂这句话，你可以直接填下面这几项"
          : "没连上，稍后再试",
      );
      setPhase("idle");
    }
  }

  async function start() {
    if (!compiled) return;
    setPhase("saving");
    setError(null);
    try {
      const created = await api.create({
        expression,
        content: toContentIn(compiled.content),
        stash: false,
        // 默认问全校。**冷启动时缩小范围等于没有匹配**——「只问一起做过事的人」
        // 那一档要等他自己去选，不能是默认值。
        reach,
      });
      const confirmed = await api.confirm(created.id);
      setSaved(confirmed);
      setPhase("done");
    } catch (e) {
      if (e instanceof ApiError && e.conflicts.length) {
        setConflicts(e.conflicts);
        setPhase("checking");
        return;
      }
      setError("没能保存，稍后再试");
      setPhase("checking");
    }
  }

  async function stash() {
    if (!compiled) return;
    setPhase("saving");
    try {
      const created = await api.create({
        expression,
        content: toContentIn(compiled.content),
        stash: true,
        reach,
      });
      setSaved(created);
      setPhase("done");
    } catch {
      setError("没能保存，稍后再试");
      setPhase("checking");
    }
  }

  if (phase === "done" && saved) {
    return <Saved intent={saved} onAgain={() => location.reload()} />;
  }

  return (
    <main className="mx-auto w-full max-w-2xl px-4 pb-24 pt-6 sm:px-5 sm:pb-16 sm:pt-16">
      {/* 一个视觉重心。**不是装饰**：在它之前这一屏是一张表浮在半屏空白里，
          而这一屏要做的第一件事是让人愿意开口。
          种子对着这一步的含义——你说的这句话就是那颗种子（ADR 0009）。 */}
      <header className="mb-6 flex items-start gap-3 sm:mb-8 sm:gap-4">
        <span className="grid size-12 shrink-0 place-items-center rounded-full bg-accent-soft text-brand">
          <Seed />
        </span>
        <div>
          <h1 className="text-[28px] font-bold leading-tight tracking-tight sm:text-[30px]">
            {myName ? `${myName}，想做点什么？` : "想做点什么？"}
          </h1>
          <p className="mt-1.5 text-[15px] text-ink-soft">
            说一句就行，剩下的一起整理。说出来它就种下了。
          </p>
        </div>
      </header>

      {phase !== "checking" && (
        <Starters
          kinds={kinds}
          failed={kindsFailed}
          onPick={(example) => {
            setExpression(example);
            void compile(example);
          }}
        />
      )}

      <section className="mt-6">
        {/* 输入框不小于 16px。iOS Safari 对更小的输入框会自动放大整页，
            那一下会让人以为页面坏了。 */}
        <textarea
          value={expression}
          onChange={(e) => setExpression(e.target.value)}
          placeholder={placeholder}
          rows={4}
          aria-label="你想做的事"
          className="w-full resize-none rounded-[16px] border border-line bg-card p-4 text-[16px] outline-none placeholder:text-ink-faint focus:border-accent"
        />
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
          <button
            type="button"
            disabled={!expression.trim() || phase === "compiling"}
            onClick={() => void compile(expression)}
            className={PRIMARY}
          >
            {phase === "compiling" ? "整理中…" : compiled ? "重新整理" : "整理一下"}
          </button>
          {compiled && (
            <span className="text-[13px] text-ink-faint">
              下面这张卡你可以随便改
            </span>
          )}
        </div>
      </section>

      {!compiled && (
        // **不发起的那一侧。** 首屏只有一个"说一件事"的时候，一个不想
        // 主动开口的人在这个产品里无事可做——而他不是少数，他是大多数。
        <p className="mt-5 text-[14px] text-ink-soft">
          不想现在发起？
          <a
            href="/me/about"
            className="ml-1 inline-flex min-h-[44px] items-center text-accent underline underline-offset-4"
          >
            说说你能做什么，让别人来找你
          </a>
        </p>
      )}

      {error && (
        <p role="alert" className="mt-4 text-[14px] text-clash">
          {error}
        </p>
      )}

      {phase === "compiling" && <Skeleton />}

      {compiled && phase !== "compiling" && (
        <IntentCard
          result={compiled}
          conflicts={conflicts}
          busy={phase === "saving"}
          onChange={(content) => setCompiled({ ...compiled, content })}
          onStart={() => void start()}
          onStash={() => void stash()}
          reach={reach}
          onReach={setReach}
          knownCount={knownCount}
        />
      )}
    </main>
  );
}

/** 首屏那颗种子。和「我的森林」里那五株是同一套画法。 */
function Seed() {
  return (
    <svg width={30} height={30} viewBox="0 0 32 32" fill="none" aria-hidden>
      <path
        d="M6 24h20"
        stroke="currentColor"
        strokeWidth={2.1}
        strokeLinecap="round"
        opacity={0.35}
      />
      <ellipse cx="16" cy="19" rx="4.6" ry="5.4" fill="currentColor" opacity={0.55} />
      <path
        d="M16 13.4V9"
        stroke="currentColor"
        strokeWidth={2.1}
        strokeLinecap="round"
        opacity={0.5}
      />
    </svg>
  );
}

function Starters({
  kinds,
  failed,
  onPick,
}: {
  kinds: ActionKind[] | null;
  failed: boolean;
  onPick: (example: string) => void;
}) {
  if (failed) {
    // 降级：拿不到场景卡不影响直接说一句话。
    return null;
  }
  if (!kinds) {
    return (
      <div className="flex flex-wrap gap-2" aria-hidden>
        {Array.from({ length: 5 }).map((_, i) => (
          <span
            key={i}
            className="h-11 w-24 animate-pulse rounded-full bg-line"
          />
        ))}
      </div>
    );
  }
  return (
    <div className="flex flex-wrap gap-2">
      {kinds.map((kind) => (
        <button
          key={kind.key}
          type="button"
          onClick={() => onPick(kind.starter.example)}
          title={kind.starter.example}
          // 边框和实底是**常态**：这几张卡在触屏上要一眼看得出能点，
          // 不能等 hover 才亮起来。
          className="inline-flex min-h-[44px] items-center rounded-full border border-line bg-card px-4 text-[14px] text-ink transition-colors active:border-accent hover:border-accent"
        >
          {kind.starter.title}
        </button>
      ))}
    </div>
  );
}

function Skeleton() {
  return (
    <div className="mt-6 space-y-3" aria-label="整理中">
      {[...Array(4)].map((_, i) => (
        <div key={i} className="h-12 animate-pulse rounded-[10px] bg-line" />
      ))}
    </div>
  );
}

function IntentCard({
  result,
  conflicts,
  busy,
  onChange,
  onStart,
  onStash,
  reach,
  onReach,
  knownCount,
}: {
  result: CompileResult;
  conflicts: Conflict[];
  busy: boolean;
  reach: Reach;
  onReach: (r: Reach) => void;
  knownCount: number;
  onChange: (content: CompileResult["content"]) => void;
  onStart: () => void;
  onStash: () => void;
}) {
  const c = result.content;
  const uncertain = new Set(c.uncertain_fields);
  const clashing = new Set(conflicts.map((x) => x.field));

  /** 点一个选项 = 把那个值填进它指的那一栏。**不多走一轮请求**——
   *  这张卡本来就是用户在改的草稿。 */
  function answer(narrows: string, value: string) {
    if (narrows === "time_window") {
      onChange({
        ...c,
        // `earliest` 没说过就用"现在"：时间窗要的是一个区间，
        // 而用户答的是"什么时候之前"，起点本来就是此刻。
        time_window: value
          ? {
              earliest: c.time_window?.earliest ?? new Date().toISOString(),
              deadline: value,
            }
          : null,
      });
      return;
    }
    if (narrows === "location_scope") {
      onChange({ ...c, location_scope: value || null });
      return;
    }
    if (narrows === "team_size") {
      const [low, high] = value.split("-").map(Number);
      onChange({
        ...c,
        team_size: low && high ? { minimum: low, maximum: high } : null,
      });
    }
  }

  /** 已经答过的不再问。答过还挂在那儿，用户会以为自己没点上。 */
  const answered = (narrows: string) =>
    narrows === "time_window"
      ? c.time_window !== null
      : narrows === "location_scope"
        ? c.location_scope !== null
        : narrows === "team_size"
          ? c.team_size !== null
          : c.needs.length > 0;
  const open = result.follow_ups.filter((q) => !answered(q.narrows));

  return (
    <section className="mt-6 rounded-[16px] border border-line bg-card p-4 sm:p-5">
      {result.fall_back_to_form && (
        <p className="mb-4 rounded-[10px] bg-draft-soft px-3 py-2 text-[14px] text-draft">
          这句话我没太读懂，下面这些是我猜的，你直接改就行。
        </p>
      )}

      <Field
        label="要做什么"
        value={c.goal}
        uncertain={uncertain.has("goal")}
        clash={clashing.has("goal")}
        onChange={(goal) => onChange({ ...c, goal })}
      />
      <ListField
        label="我能出"
        items={c.offers}
        uncertain={uncertain.has("offers")}
        onChange={(offers) => onChange({ ...c, offers })}
      />
      <ListField
        label="我缺"
        items={c.needs}
        uncertain={uncertain.has("needs")}
        clash={clashing.has("needs")}
        onChange={(needs) => onChange({ ...c, needs })}
      />
      <Readonly
        label="什么时候"
        value={
          c.time_window
            ? `${fmt(c.time_window.deadline)} 前`
            : "还没说"
        }
        uncertain={uncertain.has("time_window")}
        clash={clashing.has("time_window")}
        ask={
          <Ask
            question={open.find((q) => q.narrows === "time_window")}
            onPick={(v) => answer("time_window", v)}
          />
        }
      />
      <Readonly
        label="在哪"
        value={c.location_scope ?? "还没说"}
        uncertain={uncertain.has("location_scope")}
        ask={
          <Ask
            question={open.find((q) => q.narrows === "location_scope")}
            onPick={(v) => answer("location_scope", v)}
          />
        }
      />
      <Readonly
        label="几个人"
        value={c.team_size ? `${c.team_size.minimum}–${c.team_size.maximum} 人` : "还没说"}
        uncertain={uncertain.has("team_size")}
        clash={clashing.has("team_size")}
        ask={
          <Ask
            question={open.find((q) => q.narrows === "team_size")}
            onPick={(v) => answer("team_size", v)}
          />
        }
      />

      {c.open_questions.length > 0 && (
        <div className="mt-4 border-t border-line pt-4">
          <p className="text-[14px] text-ink-soft">这几件事等组好了你们自己定：</p>
          <ul className="mt-1.5 space-y-1">
            {c.open_questions.map((q) => (
              <li key={q} className="text-[15px] text-ink">
                · {q}
              </li>
            ))}
          </ul>
        </div>
      )}

      {open.some((q) => q.narrows === "needs") && (
        // 「你最缺哪种人」没有可点的选项——答案在上面那一栏里。
        // 再造一个输入框会有两个地方能填同一件事。
        <p className="mt-4 border-t border-line pt-4 text-[14px] text-ink-soft">
          {open.find((q) => q.narrows === "needs")?.text}
          <span className="ml-1 text-ink-faint">在上面「我缺」那一栏里补一下就行。</span>
        </p>
      )}

      {conflicts.length > 0 && (
        <ul role="alert" className="mt-4 space-y-1 border-t border-line pt-4">
          {conflicts.map((x) => (
            <li key={x.field} className="text-[14px] text-clash">
              {x.detail}
            </li>
          ))}
        </ul>
      )}

      {/* **给谁看见。** 它和逐项授权是两件事：授权决定这次露出什么，
          范围决定给谁看见。分开问，因为它们分别会被后悔——
          "我不想让全校看到我的手机号"和"我只想问熟人"是两种顾虑。

          「一起做过事的人」这一档对第一次用的人是零个候选，所以这里
          当场说出来，而不是让他选完等六小时再看见一屏"没找到"。 */}
      <fieldset className="mt-5 border-t border-line pt-4">
        <legend className="text-[14px] text-ink-soft">这条给谁看见</legend>
        <div className="mt-2 flex flex-col gap-2">
          {(
            [
              ["campus", "全校都能看到", "认识的人最多，也最可能配得上"],
              [
                "known",
                "只问一起做过事的人",
                knownCount === 0
                  ? "你还没和谁一起做成过事——选它现在会一个人都问不到"
                  : "你和其他人一起做成过事，这一档只问他们",
              ],
            ] as const
          ).map(([value, label, hint]) => (
            <label
              key={value}
              className={
                "flex min-h-[48px] cursor-pointer items-start gap-3 rounded-[10px] border px-3 py-2.5 " +
                (reach === value ? "border-accent bg-accent-soft/40" : "border-line")
              }
            >
              <input
                type="radio"
                name="reach"
                checked={reach === value}
                onChange={() => onReach(value)}
                className="mt-1 h-4 w-4 accent-[var(--color-accent)]"
              />
              <span className="min-w-0">
                <span className="block text-[15px] text-ink">{label}</span>
                <span className="block text-[13px] text-ink-faint">{hint}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      {/* 手机上竖排：两个决定并排放，拇指会替人做选择。 */}
      <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-4">
        <button
          type="button"
          disabled={busy || conflicts.length > 0}
          onClick={onStart}
          className={PRIMARY}
        >
          {busy ? "保存中…" : "就这样，开始找人"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onStash}
          className={`${QUIET} justify-center sm:justify-start`}
        >
          还没想好，先记着
        </button>
      </div>
    </section>
  );
}

function Field({
  label,
  value,
  uncertain,
  clash,
  onChange,
}: {
  label: string;
  value: string;
  uncertain?: boolean;
  clash?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className="mb-3 block">
      <Label text={label} uncertain={uncertain} />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`mt-1 min-h-[48px] w-full rounded-[10px] border px-3 text-[16px] outline-none focus:border-accent ${
          clash ? "border-clash" : "border-line"
        }`}
      />
    </label>
  );
}

function ListField({
  label,
  items,
  uncertain,
  clash,
  onChange,
}: {
  label: string;
  items: string[];
  uncertain?: boolean;
  clash?: boolean;
  onChange: (items: string[]) => void;
}) {
  return (
    <label className="mb-3 block">
      <Label text={label} uncertain={uncertain} />
      <input
        value={items.join("、")}
        placeholder="用、隔开"
        onChange={(e) =>
          onChange(
            e.target.value
              .split(/[、,，]/)
              .map((s) => s.trim())
              .filter(Boolean),
          )
        }
        className={`mt-1 min-h-[48px] w-full rounded-[10px] border px-3 text-[16px] outline-none placeholder:text-ink-faint focus:border-accent ${
          clash ? "border-clash" : "border-line"
        }`}
      />
    </label>
  );
}

function Readonly({
  label,
  value,
  uncertain,
  clash,
  ask,
}: {
  label: string;
  value: string;
  uncertain?: boolean;
  clash?: boolean;
  /** 这一栏还没填时的追问。**答案要出现在缺口旁边**——
   *  把追问堆在卡片最下面，用户得先记住"哪一栏是空的"再滚下去回答。 */
  ask?: ReactNode;
}) {
  return (
    <div className="mb-3">
      <Label text={label} uncertain={uncertain} />
      <p className={`mt-1 text-[16px] ${clash ? "text-clash" : "text-ink"}`}>{value}</p>
      {ask}
    </div>
  );
}

/** 一条追问：一句话加几个可以点的答案。 */
function Ask({
  question,
  onPick,
}: {
  question: CompileResult["follow_ups"][number] | undefined;
  onPick: (value: string) => void;
}) {
  if (!question) return null;
  if (question.options.length === 0) {
    return (
      <p className="mt-1.5 text-[14px] text-ink-faint">{question.text}</p>
    );
  }
  return (
    <div className="mt-2">
      <p className="text-[14px] text-ink-soft">{question.text}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {question.options.map((o) => (
          <button
            key={o.label}
            type="button"
            onClick={() => onPick(o.value)}
            className="inline-flex min-h-[44px] items-center rounded-full border border-line bg-card px-4 text-[14px] text-ink active:border-accent hover:border-accent hover:text-accent"
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/** 不确定的字段要被看见——抽取器猜的东西不能默默当成事实。 */
function Label({ text, uncertain }: { text: string; uncertain?: boolean }) {
  return (
    <span className="flex items-center gap-1.5 text-[14px] text-ink-soft">
      {text}
      {uncertain && (
        <span className="rounded-full bg-draft-soft px-2 py-0.5 text-[12px] text-draft">
          我猜的
        </span>
      )}
    </span>
  );
}

function Saved({ intent, onAgain }: { intent: Intent; onAgain: () => void }) {
  const stashed = intent.state === "stashed";
  return (
    <main className="mx-auto w-full max-w-2xl px-4 pb-24 pt-6 sm:px-5 sm:pb-16 sm:pt-16">
      <h1 className="text-[28px] font-bold leading-tight tracking-tight sm:text-[30px]">
        {stashed ? "记下了" : "开始找人了"}
      </h1>
      <p className="mt-2 text-[15px] text-ink-soft">
        {stashed
          ? "这条只有你看得到。等有合适的招募出现，我会提醒你一下。"
          : "下一次配队开始时会给你两三个小队，每个都会说清为什么是这几个人。"}
      </p>
      <p className="mt-6 rounded-[16px] border border-line bg-card p-4 text-[16px]">
        {intent.content.goal}
      </p>
      <button type="button" onClick={onAgain} className={`${QUIET} mt-4`}>
        再说一件事
      </button>
    </main>
  );
}

function fmt(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日`;
}
