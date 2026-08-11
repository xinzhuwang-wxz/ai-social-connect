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

import { useEffect, useState } from "react";
import {
  ApiError,
  api,
  toContentIn,
  type ActionKind,
  type CompileResult,
  type Conflict,
  type Intent,
} from "@/lib/api";

type Phase = "idle" | "compiling" | "checking" | "saving" | "done";

export default function Page() {
  const [kinds, setKinds] = useState<ActionKind[] | null>(null);
  const [kindsFailed, setKindsFailed] = useState(false);
  const [expression, setExpression] = useState("");
  const [compiled, setCompiled] = useState<CompileResult | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [saved, setSaved] = useState<Intent | null>(null);

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
    <main className="mx-auto w-full max-w-2xl px-5 py-10 sm:py-16">
      <header className="mb-8">
        <h1 className="text-[20px] font-semibold tracking-tight">想做点什么？</h1>
        <p className="mt-1 text-[13px] text-ink-soft">
          说一句就行，剩下的一起整理。
        </p>
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
        <textarea
          value={expression}
          onChange={(e) => setExpression(e.target.value)}
          placeholder={placeholder}
          rows={4}
          aria-label="你想做的事"
          className="w-full resize-none rounded-[16px] border border-line bg-card p-4 text-[15px] outline-none placeholder:text-ink-faint focus:border-accent"
        />
        <div className="mt-3 flex items-center gap-3">
          <button
            type="button"
            disabled={!expression.trim() || phase === "compiling"}
            onClick={() => void compile(expression)}
            className="rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white disabled:opacity-35"
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

      {error && (
        <p role="alert" className="mt-4 text-[13px] text-clash">
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
        />
      )}
    </main>
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
            className="h-8 w-24 animate-pulse rounded-[12px] bg-line"
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
          className="rounded-[12px] border border-line bg-card px-3 py-1.5 text-[13px] text-ink-soft transition-colors hover:border-accent hover:text-ink"
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
        <div key={i} className="h-10 animate-pulse rounded-[8px] bg-line" />
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
}: {
  result: CompileResult;
  conflicts: Conflict[];
  busy: boolean;
  onChange: (content: CompileResult["content"]) => void;
  onStart: () => void;
  onStash: () => void;
}) {
  const c = result.content;
  const uncertain = new Set(c.uncertain_fields);
  const clashing = new Set(conflicts.map((x) => x.field));

  return (
    <section className="mt-6 rounded-[16px] border border-line bg-card p-5">
      {result.fall_back_to_form && (
        <p className="mb-4 rounded-[8px] bg-draft-soft px-3 py-2 text-[13px] text-draft">
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
      />
      <Readonly
        label="在哪"
        value={c.location_scope ?? "还没说"}
        uncertain={uncertain.has("location_scope")}
      />
      <Readonly
        label="几个人"
        value={c.team_size ? `${c.team_size.minimum}–${c.team_size.maximum} 人` : "还没说"}
        uncertain={uncertain.has("team_size")}
        clash={clashing.has("team_size")}
      />

      {c.open_questions.length > 0 && (
        <div className="mt-4 border-t border-line pt-4">
          <p className="text-[13px] text-ink-soft">这几件事等组好了你们自己定：</p>
          <ul className="mt-1.5 space-y-1">
            {c.open_questions.map((q) => (
              <li key={q} className="text-[14px] text-ink">
                · {q}
              </li>
            ))}
          </ul>
        </div>
      )}

      {result.follow_ups.length > 0 && (
        <div className="mt-4 border-t border-line pt-4">
          {result.follow_ups.map((q) => (
            <p key={q.narrows} className="text-[14px] text-ink">
              {q.text}
              {q.options.length > 0 && (
                <span className="ml-2 text-[13px] text-ink-faint">
                  {q.options.join(" / ")}
                </span>
              )}
            </p>
          ))}
        </div>
      )}

      {conflicts.length > 0 && (
        <ul role="alert" className="mt-4 space-y-1 border-t border-line pt-4">
          {conflicts.map((x) => (
            <li key={x.field} className="text-[13px] text-clash">
              {x.detail}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={busy || conflicts.length > 0}
          onClick={onStart}
          className="rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white disabled:opacity-35"
        >
          {busy ? "保存中…" : "就这样，开始找人"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onStash}
          className="text-[14px] text-ink-soft underline underline-offset-4 hover:text-ink"
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
        className={`mt-1 w-full rounded-[8px] border px-3 py-2 text-[15px] outline-none focus:border-accent ${
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
        className={`mt-1 w-full rounded-[8px] border px-3 py-2 text-[15px] outline-none placeholder:text-ink-faint focus:border-accent ${
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
}: {
  label: string;
  value: string;
  uncertain?: boolean;
  clash?: boolean;
}) {
  return (
    <div className="mb-3">
      <Label text={label} uncertain={uncertain} />
      <p className={`mt-1 text-[15px] ${clash ? "text-clash" : "text-ink"}`}>{value}</p>
    </div>
  );
}

/** 不确定的字段要被看见——抽取器猜的东西不能默默当成事实。 */
function Label({ text, uncertain }: { text: string; uncertain?: boolean }) {
  return (
    <span className="flex items-center gap-1.5 text-[13px] text-ink-soft">
      {text}
      {uncertain && (
        <span className="rounded-[4px] bg-draft-soft px-1.5 py-0.5 text-[11px] text-draft">
          我猜的
        </span>
      )}
    </span>
  );
}

function Saved({ intent, onAgain }: { intent: Intent; onAgain: () => void }) {
  const stashed = intent.state === "stashed";
  return (
    <main className="mx-auto w-full max-w-2xl px-5 py-16">
      <h1 className="text-[20px] font-semibold">
        {stashed ? "记下了" : "开始找人了"}
      </h1>
      <p className="mt-2 text-[15px] text-ink-soft">
        {stashed
          ? "这条只有你看得到。等有合适的招募出现，我会提醒你一下。"
          : "下一次配队开始时会给你两三个小队，每个都会说清为什么是这几个人。"}
      </p>
      <p className="mt-6 rounded-[16px] border border-line bg-card p-4 text-[15px]">
        {intent.content.goal}
      </p>
      <button
        type="button"
        onClick={onAgain}
        className="mt-6 text-[14px] text-ink-soft underline underline-offset-4"
      >
        再说一件事
      </button>
    </main>
  );
}

function fmt(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日`;
}
