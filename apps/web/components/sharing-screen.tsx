"use client";

/**
 * 第二屏：这次让他们看到我的。
 *
 * 三条产品判断决定了这一屏长成现在这样：
 *
 * 1. **默认什么都不给。** 进来时一项都没勾——不是"全勾上让你去关"。
 *    最少露出必须是默认值，否则它只是写在文档里的一句话。
 * 2. **勾一下就生效，没有"保存"按钮。** 有保存按钮就会出现一段"界面已经改了、
 *    对方那边还没改"的空档，而这一屏唯一的承诺就是两边一致。收回同理：
 *    取消勾选就是收回，不需要再确认一次（权利要顺手，不能庄严）。
 * 3. **右边那张卡由服务端算。** 前端自己照勾选投影一遍会更快，但那样它就成了
 *    前端的猜测；服务端的投影和真正发给对方走的是同一条路径，所以这里显示
 *    什么，对方就真的只看到什么。
 *
 * 界面文案不使用领域词汇（见 docs/07 语言映射表）。
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  CANDIDATES,
  SOLVER_ONLY,
  envelopeForIntent,
  fetchPreview,
  grantableFields,
  putEnvelope,
  revokeEnvelope,
  type Envelope,
  type GrantableField,
  type Preview,
} from "@/lib/envelopes";

/** field_name → 这次给谁看。不在表里 = 这次不给。 */
type Picks = Record<string, string>;

/**
 * 每一项为什么要它。
 *
 * 用户不是在给字段打勾，是在决定"要不要为了这件事多露一点"——不说清换来什么，
 * 理性的选择永远是都不给。
 *
 * `label` 是兜底：后端还没给某个字段中文标签时会把字段名原样发回来，
 * 英文字段名不能出现在界面上。
 */
const WHY: Record<string, { why: string; label?: string }> = {
  goal: { why: "说清要做什么，才可能有人一眼认出这正是他想干的事" },
  offers: { why: "你能出什么，是别人愿意来的理由" },
  needs: { why: "说了缺什么，才有人来补" },
  time_window: { why: "知道你哪天有空，才排得出大家都在的时间" },
  location_scope: { why: "知道你常在哪个校区，才不会给你配一个跑不过来的人" },
  team_size: { why: "几个人算齐，决定了这个组什么时候能开工" },
  boundaries: { why: "你不接受的事先说清楚，省得到一半才发现不合适" },
  open_questions: { why: "还没定的事摆出来，愿意一起定的人才会来" },
  portfolio_link: { why: "有东西可看，别人更容易相信你真的干得了" },
  self_intro: {
    label: "我自己写的那段话",
    why: "用你的原话去找想法接近的人，比按标签找准得多",
  },
};

function labelOf(field: GrantableField): string {
  // 后端没给中文标签时会原样返回 field_name，这时用兜底名字。
  const fallback = WHY[field.field_name]?.label;
  return field.label === field.field_name && fallback ? fallback : field.label;
}

export function SharingScreen({ intentId }: { intentId: string }) {
  const [fields, setFields] = useState<GrantableField[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [picks, setPicks] = useState<Picks>({});
  const [envelope, setEnvelope] = useState<Envelope | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewDown, setPreviewDown] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  // 连点时只认最后一次的结果，否则先发的响应可能后到、把界面写回旧状态。
  const turn = useRef(0);

  const reloadPreview = useCallback(async () => {
    try {
      setPreview(await fetchPreview(intentId));
      setPreviewDown(false);
    } catch {
      // 降级：看不到对方那边的样子，但勾选和保存照常。
      setPreviewDown(true);
    }
  }, [intentId]);

  const load = useCallback(async () => {
    setLoadFailed(false);
    setFields(null);
    void reloadPreview();
    try {
      const [list, existing] = await Promise.all([
        grantableFields(intentId),
        // 读不到"已经给出过什么"不该拦住整屏——最坏情况是从零开始重勾一遍。
        envelopeForIntent(intentId).catch(() => null),
      ]);
      setFields(list);
      setEnvelope(existing);
      setPicks(
        existing
          ? Object.fromEntries(existing.grants.map((g) => [g.field_name, g.audience]))
          : {},
      );
    } catch {
      setLoadFailed(true);
    }
  }, [intentId, reloadPreview]);

  useEffect(() => {
    void load();
  }, [load]);

  async function commit(next: Picks) {
    const before = picks;
    setPicks(next); // 勾选要立刻有反馈，不能等网络回来才动
    setSaving(true);
    setSaveFailed(false);
    const mine = ++turn.current;
    try {
      const saved = await putEnvelope(
        intentId,
        Object.entries(next).map(([field_name, audience]) => ({ field_name, audience })),
      );
      if (mine !== turn.current) return;
      setEnvelope(saved);
      await reloadPreview();
    } catch {
      if (mine !== turn.current) return;
      setPicks(before); // 没存上就不能让界面假装存上了
      setSaveFailed(true);
    } finally {
      if (mine === turn.current) setSaving(false);
    }
  }

  function toggle(fieldName: string, on: boolean) {
    const next = { ...picks };
    // 新勾上的一项默认只用来配对——最少露出是默认值，不是用户改出来的结果。
    if (on) next[fieldName] = SOLVER_ONLY;
    else delete next[fieldName];
    void commit(next);
  }

  function setAudience(fieldName: string, audience: string) {
    void commit({ ...picks, [fieldName]: audience });
  }

  async function revokeAll() {
    if (!envelope) return;
    const mine = ++turn.current;
    setSaving(true);
    setSaveFailed(false);
    try {
      await revokeEnvelope(envelope.id);
      if (mine !== turn.current) return;
      setEnvelope(null);
      setPicks({});
      await reloadPreview();
    } catch {
      if (mine === turn.current) setSaveFailed(true);
    } finally {
      if (mine === turn.current) setSaving(false);
    }
  }

  const live = envelope?.state === "active" ? envelope : null;
  const writable = fields?.filter((f) => f.present) ?? [];
  const blank = fields?.filter((f) => !f.present) ?? [];

  return (
    <main className="mx-auto w-full max-w-4xl px-5 py-10 sm:py-16">
      <header className="mb-8">
        <h1 className="text-[20px] font-semibold tracking-tight">
          这次让他们看到什么？
        </h1>
        <p className="mt-1 text-[13px] text-ink-soft">
          默认谁都看不到。你勾一项，才露一项。
        </p>
        <p className="mt-3 text-[13px] text-ink-faint">
          {live ? `到 ${fmt(live.expires_at)} 自动失效` : "你还没给出任何东西"}
        </p>
      </header>

      {loadFailed && <LoadFailed onRetry={() => void load()} />}

      {!loadFailed && fields === null && <Loading />}

      {!loadFailed && fields !== null && writable.length === 0 && <Nothing />}

      {!loadFailed && fields !== null && writable.length > 0 && (
        <div className="grid gap-6 md:grid-cols-[1fr_18rem] md:items-start">
          <section className="space-y-3">
            {writable.map((field) => (
              <Row
                key={field.field_name}
                field={field}
                audience={picks[field.field_name]}
                onToggle={(on) => toggle(field.field_name, on)}
                onAudience={(a) => setAudience(field.field_name, a)}
              />
            ))}

            {blank.length > 0 && (
              <p className="pt-1 text-[13px] text-ink-faint">
                这次没写的还有 {blank.map(labelOf).join("、")}
                。写了才谈得上要不要给。
              </p>
            )}

            <div className="flex flex-wrap items-center gap-4 pt-2">
              <span
                role="status"
                className="text-[13px] text-ink-faint"
                aria-live="polite"
              >
                {saving ? "保存中…" : live ? "已经生效" : "还没给出任何东西"}
              </span>
              {live && (
                <button
                  type="button"
                  onClick={() => void revokeAll()}
                  className="text-[14px] text-ink-soft underline underline-offset-4 hover:text-ink"
                >
                  全部收回
                </button>
              )}
            </div>

            {saveFailed && (
              <p role="alert" className="text-[13px] text-clash">
                这一下没存上，刚才那项已经退回原样，再点一次试试。
              </p>
            )}
          </section>

          <PreviewCard preview={preview} down={previewDown} />
        </div>
      )}
    </main>
  );
}

/**
 * 一项 = 一个独立的决定：给不给，以及给谁看。
 *
 * 没有"全部同意"。一次点下去只改这一项，因为用户被一次问两件事时，
 * 两件都不会认真答。
 */
function Row({
  field,
  audience,
  onToggle,
  onAudience,
}: {
  field: GrantableField;
  audience: string | undefined;
  onToggle: (on: boolean) => void;
  onAudience: (audience: string) => void;
}) {
  const label = labelOf(field);
  const on = audience !== undefined;
  return (
    <fieldset
      aria-label={label}
      className="rounded-[16px] border border-line bg-card p-4"
    >
      <div className="flex items-start justify-between gap-4">
        <label className="flex items-start gap-2.5">
          <input
            type="checkbox"
            checked={on}
            onChange={(e) => onToggle(e.target.checked)}
            className="mt-1 size-4 accent-accent"
          />
          <span className="text-[15px]">{label}</span>
        </label>

        {on && (
          <div className="flex shrink-0 gap-1 rounded-[8px] bg-paper p-0.5">
            <Choice
              name={label}
              text="只用来配对"
              checked={audience !== CANDIDATES}
              onPick={() => onAudience(SOLVER_ONLY)}
            />
            <Choice
              name={label}
              text="他们能看到"
              checked={audience === CANDIDATES}
              onPick={() => onAudience(CANDIDATES)}
            />
          </div>
        )}
      </div>

      <p className="mt-1.5 pl-[26px] text-[13px] text-ink-soft">
        {WHY[field.field_name]?.why ?? "这一项会帮着找到更合适的人"}
      </p>
      {on && audience !== CANDIDATES && (
        <p className="mt-1 pl-[26px] text-[13px] text-ink-faint">
          这一项只拿去配对，对方看不到。
        </p>
      )}
    </fieldset>
  );
}

function Choice({
  name,
  text,
  checked,
  onPick,
}: {
  name: string;
  text: string;
  checked: boolean;
  onPick: () => void;
}) {
  return (
    <label
      className={`cursor-pointer rounded-[8px] px-2.5 py-1 text-[13px] ${
        checked ? "bg-card text-ink shadow-sm" : "text-ink-soft"
      }`}
    >
      <input
        type="radio"
        name={`${name}-给谁看`}
        checked={checked}
        onChange={onPick}
        className="sr-only"
      />
      {text}
    </label>
  );
}

/**
 * 对方那边的样子。
 *
 * 这张卡是这一屏存在的理由：最少披露只有在用户能自己检查的时候才算数。
 */
function PreviewCard({ preview, down }: { preview: Preview | null; down: boolean }) {
  const shown = Object.entries(preview?.visible ?? {});
  return (
    <aside
      aria-label="他们会看到"
      className="rounded-[16px] border border-line bg-card p-4 md:sticky md:top-6"
    >
      <h2 className="text-[13px] text-ink-soft">他们会看到</h2>

      {down ? (
        // 降级：预览拿不到，但这一屏的其他事一件都不少。
        <p className="mt-3 text-[14px] text-ink-soft">
          现在调不出他们那边的样子。你照常勾，勾了就已经生效；等会儿再回来就能看到了。
        </p>
      ) : preview === null ? (
        <div className="mt-3 space-y-2" aria-label="加载中">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-8 animate-pulse rounded-[8px] bg-line" />
          ))}
        </div>
      ) : shown.length === 0 ? (
        <p className="mt-3 text-[14px] text-ink-soft">
          现在他们什么都看不到。往左边勾一项，这里就会多一行。
        </p>
      ) : (
        <dl className="mt-3 space-y-2.5">
          {shown.map(([label, value]) => (
            <div key={label}>
              <dt className="text-[11px] text-ink-faint">{label}</dt>
              <dd className="text-[14px]">{show(value)}</dd>
            </div>
          ))}
        </dl>
      )}

      {!down && preview !== null && preview.withheld.length > 0 && (
        <p className="mt-4 border-t border-line pt-3 text-[13px] text-ink-faint">
          看不到：{preview.withheld.join("、")}
        </p>
      )}
    </aside>
  );
}

function Loading() {
  return (
    <div className="space-y-3" aria-label="加载中">
      {[...Array(4)].map((_, i) => (
        <div key={i} className="h-20 animate-pulse rounded-[16px] bg-line" />
      ))}
    </div>
  );
}

/** 错误态：说清哪里断了、下一步做什么，不出现错误码。 */
function LoadFailed({ onRetry }: { onRetry: () => void }) {
  return (
    <section role="alert" className="rounded-[16px] border border-line bg-card p-5">
      <p className="text-[15px]">没能把这次可以给的东西调出来。</p>
      <p className="mt-1 text-[13px] text-ink-soft">
        在这之前谁都看不到你——没连上的时候不会有任何东西发出去。
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white"
      >
        再试一次
      </button>
    </section>
  );
}

/** 空态：说明为什么空，并给一个能走的下一步。 */
function Nothing() {
  return (
    <section className="rounded-[16px] border border-line bg-card p-5">
      <p className="text-[15px]">这件事你还没写下任何内容，所以现在没什么可给的。</p>
      <p className="mt-1 text-[13px] text-ink-soft">
        回去把要做什么、缺什么补上，再回来决定给谁看。
      </p>
      <a
        href="/"
        className="mt-4 inline-block rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white"
      >
        回去补上
      </a>
    </section>
  );
}

/** 预览里的值是原样的领域数据，这里按人话显示。 */
function show(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.join("、");
  if (typeof value === "object") {
    const v = value as Record<string, unknown>;
    if (typeof v.deadline === "string") return `${fmt(v.deadline)} 前`;
    if (typeof v.minimum === "number") return `${v.minimum}–${v.maximum} 人`;
    return Object.values(v).join("、");
  }
  return String(value);
}

function fmt(iso: string): string {
  const d = new Date(iso);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日 ${hh}:${mm}`;
}
