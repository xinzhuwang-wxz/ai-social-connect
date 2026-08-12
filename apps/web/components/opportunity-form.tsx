"use client";

/**
 * 发布那一侧：发一份招募。
 *
 * 四条产品判断决定了这一屏长成现在这样：
 *
 * 1. **缺口是结构化的：角色 + 数量。** 一句"招若干人"发出去，学生判断不出
 *    自己能不能补上，系统也对不上任何人——那份招募等于没发。所以这里没有
 *    "需求描述"那样一个大文本框，只有一行行的角色和数字。
 * 2. **负责人是必填项，且是一个真人的名字。** 没人负责的事最后会烂在那里，
 *    而代价是来的那几个学生付的。
 * 3. **拦住的时候要说清缺的是哪一样。** "请填写完整"等于让人自己去找；
 *    "还没写谁负责这件事"直接就是下一步动作。
 * 4. **发出去之前能看到学生会看到的样子。** 预览用的是学生那一屏的同一个
 *    组件，不是另画一张示意图——另画一张，两边迟早对不上。
 *
 * 界面文案不使用领域词汇（见 docs/07 语言映射表）。
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { ApiError } from "@/lib/api";
import {
  actionKinds,
  asPreview,
  emptyDraft,
  missing,
  openOpportunities,
  organizationsIn,
  publish,
  toRequest,
  type ActionKind,
  type Draft,
  type DraftRequirement,
  type DraftSeat,
  type Opportunity,
  type Org,
} from "@/lib/opportunities";

import { OpportunityCard } from "./opportunity-list";

export function OpportunityForm() {
  const [orgs, setOrgs] = useState<Org[] | null>(null);
  const [orgsFailed, setOrgsFailed] = useState(false);
  const [kinds, setKinds] = useState<ActionKind[] | null>(null);
  // 降级：调不出可以选的类别时，别的照常填、照常预览，只有这一栏空着。
  const [kindsDown, setKindsDown] = useState(false);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [previewing, setPreviewing] = useState(false);
  const [gaps, setGaps] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [posted, setPosted] = useState<Opportunity | null>(null);

  const load = useCallback(async () => {
    setOrgsFailed(false);
    setOrgs(null);
    setKindsDown(false);
    setKinds(null);
    try {
      setKinds(await actionKinds());
    } catch {
      setKindsDown(true);
    }
    try {
      const found = organizationsIn(await openOpportunities());
      setOrgs(found);
      // 只有一个可选时替他选上：一个只有一项的下拉框不是选择，是负担。
      const [only] = found;
      if (only && found.length === 1) {
        setDraft((d) => (d.organizationId ? d : { ...d, organizationId: only.id }));
      }
    } catch {
      setOrgsFailed(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const change = (patch: Partial<Draft>) => {
    setDraft((d) => ({ ...d, ...patch }));
    setGaps([]);
    setFailure(null);
  };

  async function send() {
    const found = missing(draft, orgs ?? [], new Date());
    setGaps(found);
    if (found.length > 0) return;
    setBusy(true);
    setFailure(null);
    try {
      const created = await publish(toRequest(draft));
      // 后端目前不回负责人的名字（见 lib/opportunities 文件头），这里把刚填的那个
      // 补回去，好让这一屏显示的和学生将来看到的是同一件事。
      setPosted({ ...created, steward_name: draft.steward.trim() });
    } catch (e) {
      setFailure(whyNot(e));
    } finally {
      setBusy(false);
    }
  }

  if (posted) {
    return (
      <Shell title="发出去了">
        <p className="mb-6 text-[13px] text-ink-soft">
          下面这张就是学生现在看到的样子。有人对上缺口，下一轮配队会带上他。
        </p>
        <OpportunityCard row={{ opportunity: posted, fills: [] }} />
        <button
          type="button"
          onClick={() => {
            setPosted(null);
            setDraft(emptyDraft());
            setPreviewing(false);
          }}
          className="mt-6 text-[14px] text-ink-soft underline underline-offset-4 hover:text-ink"
        >
          再发一份
        </button>
      </Shell>
    );
  }

  if (orgsFailed) {
    return (
      <Shell title="发一份招募">
        <section role="alert" className="rounded-[16px] border border-line bg-card p-5">
          <p className="text-[15px]">现在调不出你能代表哪个组织发。</p>
          <p className="mt-1 text-[13px] text-ink-soft">
            这一步跳不过去：学生要靠组织核没核过来判断这不是假项目。
          </p>
          <button
            type="button"
            onClick={() => void load()}
            className="mt-4 rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-paper"
          >
            再看一次
          </button>
        </section>
      </Shell>
    );
  }

  if (orgs === null) {
    return (
      <Shell title="发一份招募">
        <div className="space-y-3" aria-label="加载中">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-14 animate-pulse rounded-[8px] bg-line" />
          ))}
        </div>
      </Shell>
    );
  }

  if (orgs.length === 0) {
    return (
      <Shell title="发一份招募">
        <section className="rounded-[16px] border border-line bg-card p-5">
          <p className="text-[15px]">还没有哪个组织能在这里招人。</p>
          <p className="mt-1 text-[13px] text-ink-soft">
            发招募之前，校园那边要先核过这个社团、院系或者实验室——学生就是靠这一条
            判断这不是一个用来收集信息的假项目。去问一下再回来。
          </p>
          <a
            href="/opportunities"
            className="mt-4 inline-block text-[14px] text-ink-soft underline underline-offset-4 hover:text-ink"
          >
            先看看别人在招什么
          </a>
        </section>
      </Shell>
    );
  }

  const chosen = orgs.find((o) => o.id === draft.organizationId);

  return (
    <Shell
      title="发一份招募"
      lead="写清缺哪些角色、各几个、谁负责、什么时候截止。这四样缺一样，学生就判断不出自己能不能来。"
    >
      <section className="space-y-5 rounded-[16px] border border-line bg-card p-5">
        <Row label="这件事叫什么">
          <input
            value={draft.title}
            onChange={(e) => change({ title: e.target.value })}
            aria-label="这件事叫什么"
            placeholder="比如：校园流浪猫 60 秒短片"
            className={inputClass}
          />
        </Row>

        <Row label="要做成什么样">
          <textarea
            value={draft.goal}
            onChange={(e) => change({ goal: e.target.value })}
            rows={2}
            aria-label="要做成什么样"
            placeholder="比如：周五前出一支能发出去的成片"
            className={`${inputClass} resize-none`}
          />
        </Row>

        <Row label="这是件什么事">
          {kindsDown ? (
            <p className="text-[14px] text-ink-soft">
              现在调不出可以选的类别。别的先填着，这一项等会儿再选。
            </p>
          ) : (
            <select
              value={draft.kindKey}
              onChange={(e) => change({ kindKey: e.target.value })}
              aria-label="这是件什么事"
              className={inputClass}
            >
              <option value="">还没选</option>
              {(kinds ?? []).map((kind) => (
                <option key={kind.key} value={kind.key}>
                  {kind.label}
                </option>
              ))}
            </select>
          )}
        </Row>

        <Seats draft={draft} kinds={kinds} onChange={change} />

        <Row
          label="谁负责这件事"
          note="写一个真人的名字。学生看不到有人负责，就不知道出了事找谁。"
        >
          <input
            value={draft.steward}
            onChange={(e) => change({ steward: e.target.value })}
            aria-label="谁负责这件事"
            placeholder="比如：陈牧"
            className={inputClass}
          />
        </Row>

        <Row label="什么时候截止">
          <input
            type="datetime-local"
            value={draft.deadline}
            onChange={(e) => change({ deadline: e.target.value })}
            aria-label="什么时候截止"
            className={inputClass}
          />
        </Row>

        <Row label="在哪（可以不写）">
          <input
            value={draft.location}
            onChange={(e) => change({ location: e.target.value })}
            aria-label="在哪"
            placeholder="比如：东校区"
            className={inputClass}
          />
        </Row>

        <Row label="由哪个组织发">
          <select
            value={draft.organizationId}
            onChange={(e) => change({ organizationId: e.target.value })}
            aria-label="由哪个组织发"
            className={inputClass}
          >
            <option value="">还没选</option>
            {orgs.map((org) => (
              <option key={org.id} value={org.id}>
                {org.name}
                {org.verified ? "（校园核过）" : "（校园没核过）"}
              </option>
            ))}
          </select>
          {chosen && !chosen.verified && (
            <p role="alert" className="mt-1 text-[13px] text-clash">
              {chosen.name}还没被校园核过，不能在这里招人。先去把这一步办了。
            </p>
          )}
        </Row>

        <Requirements draft={draft} onChange={change} />
      </section>

      {gaps.length > 0 && (
        <section
          role="alert"
          aria-label="还差什么"
          className="mt-4 rounded-[16px] border border-clash p-4"
        >
          <p className="text-[14px] font-medium text-clash">这几样还没写：</p>
          <ul className="mt-1.5 space-y-1">
            {gaps.map((gap) => (
              <li key={gap} className="text-[14px] text-clash">
                {gap}
              </li>
            ))}
          </ul>
        </section>
      )}

      {failure && (
        <p role="alert" className="mt-4 text-[14px] text-clash">
          {failure}
        </p>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => setPreviewing(!previewing)}
          aria-expanded={previewing}
          className="rounded-[12px] border border-line px-4 py-2 text-[14px]"
        >
          {previewing ? "收起预览" : "看看学生会看到什么"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void send()}
          className="rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-paper disabled:opacity-35"
        >
          {busy ? "发着…" : "发出去"}
        </button>
      </div>

      {previewing && (
        <section aria-label="学生会看到的样子" className="mt-5">
          <p className="mb-2 text-[13px] text-ink-soft">
            下面这张和学生那一屏是同一张卡，不是另画的样子。
          </p>
          <OpportunityCard row={{ opportunity: asPreview(draft, orgs), fills: [] }} />
        </section>
      )}
    </Shell>
  );
}

const inputClass =
  "mt-1 w-full rounded-[8px] border border-line px-3 py-2 text-[15px] outline-none placeholder:text-ink-faint focus:border-accent";

function Shell({
  title,
  lead,
  children,
}: {
  title: string;
  lead?: string;
  children: ReactNode;
}) {
  return (
    <main className="mx-auto w-full max-w-2xl px-5 py-10 sm:py-16">
      <header className="mb-8">
        <h1 className="text-[20px] font-semibold tracking-tight">{title}</h1>
        {lead && <p className="mt-1 text-[13px] text-ink-soft">{lead}</p>}
      </header>
      {children}
    </main>
  );
}

function Row({
  label,
  note,
  children,
}: {
  label: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <div>
      <span className="text-[13px] text-ink-soft">{label}</span>
      {note && <p className="text-[13px] text-ink-faint">{note}</p>}
      {children}
    </div>
  );
}

/**
 * 缺哪些角色，各几个。
 *
 * 这是这一屏的核心，也是唯一一处不允许退化成自由文本的地方：说不清缺口，
 * 谁都不知道自己能不能补上，而"不知道自己算不算"的人不会来。
 */
function Seats({
  draft,
  kinds,
  onChange,
}: {
  draft: Draft;
  kinds: ActionKind[] | null;
  onChange: (patch: Partial<Draft>) => void;
}) {
  const suggested = kinds?.find((k) => k.key === draft.kindKey)?.starter.roles ?? [];
  const taken = new Set(draft.seats.map((seat) => seat.role.trim()).filter(Boolean));

  const set = (index: number, patch: Partial<DraftSeat>) =>
    onChange({
      seats: draft.seats.map((seat, i) => (i === index ? { ...seat, ...patch } : seat)),
    });

  return (
    <div>
      <span className="text-[13px] text-ink-soft">缺哪些角色，各几个</span>
      <p className="text-[13px] text-ink-faint">
        一个角色一行。写「招若干人」，谁都不知道自己能不能补上。
      </p>

      <ul className="mt-1 space-y-2">
        {draft.seats.map((seat, index) => (
          <li key={index} className="flex flex-wrap items-center gap-2">
            <input
              value={seat.role}
              onChange={(e) => set(index, { role: e.target.value })}
              aria-label={`第 ${index + 1} 个角色`}
              placeholder="比如：剪辑"
              className="min-w-40 flex-1 rounded-[8px] border border-line px-3 py-2 text-[15px] outline-none placeholder:text-ink-faint focus:border-accent"
            />
            <input
              type="number"
              min={1}
              value={seat.capacity}
              onChange={(e) => set(index, { capacity: e.target.value })}
              aria-label={`第 ${index + 1} 个角色要几个人`}
              className="w-20 rounded-[8px] border border-line px-3 py-2 text-[15px] outline-none focus:border-accent"
            />
            <span className="text-[13px] text-ink-faint">个</span>
            {draft.seats.length > 1 && (
              <button
                type="button"
                onClick={() =>
                  onChange({ seats: draft.seats.filter((_, i) => i !== index) })
                }
                className="text-[13px] text-ink-soft underline underline-offset-4 hover:text-ink"
              >
                删掉第 {index + 1} 行
              </button>
            )}
          </li>
        ))}
      </ul>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => onChange({ seats: [...draft.seats, { role: "", capacity: "1" }] })}
          className="rounded-[12px] border border-line px-3 py-1.5 text-[13px] text-ink-soft hover:border-accent hover:text-ink"
        >
          再加一个角色
        </button>
        {suggested
          .filter((role) => !taken.has(role))
          .map((role) => (
            <button
              key={role}
              type="button"
              onClick={() =>
                onChange({
                  seats: [
                    ...draft.seats.filter((seat) => seat.role.trim()),
                    { role, capacity: "1" },
                  ],
                })
              }
              className="rounded-[12px] border border-line px-3 py-1.5 text-[13px] text-ink-soft hover:border-accent hover:text-ink"
            >
              加「{role}」
            </button>
          ))}
      </div>
    </div>
  );
}

/**
 * 要求。
 *
 * 可以不写；写了就必须说清是必须满足的还是加分的。两者对学生的意义完全不同：
 * 把加分项读成硬要求，够格的人自己就走了。
 */
function Requirements({
  draft,
  onChange,
}: {
  draft: Draft;
  onChange: (patch: Partial<Draft>) => void;
}) {
  const set = (index: number, patch: Partial<DraftRequirement>) =>
    onChange({
      requirements: draft.requirements.map((r, i) =>
        i === index ? { ...r, ...patch } : r,
      ),
    });

  return (
    <div>
      <span className="text-[13px] text-ink-soft">对来的人有什么要求（可以不写）</span>
      <p className="text-[13px] text-ink-faint">
        写了就说清是必须满足的还是加分的。含糊的一条会把够格的人吓走。
      </p>

      {draft.requirements.length > 0 && (
        <ul className="mt-1 space-y-2">
          {draft.requirements.map((r, index) => (
            <li key={index} className="flex flex-wrap items-center gap-2">
              <input
                value={r.text}
                onChange={(e) => set(index, { text: e.target.value })}
                aria-label={`第 ${index + 1} 条要求`}
                placeholder="比如：拍过一次短片"
                className="min-w-40 flex-1 rounded-[8px] border border-line px-3 py-2 text-[15px] outline-none placeholder:text-ink-faint focus:border-accent"
              />
              <select
                value={r.hard ? "hard" : "plus"}
                onChange={(e) => set(index, { hard: e.target.value === "hard" })}
                aria-label={`第 ${index + 1} 条是哪种`}
                className="rounded-[8px] border border-line px-3 py-2 text-[15px] outline-none focus:border-accent"
              >
                <option value="hard">必须满足的</option>
                <option value="plus">会加分的</option>
              </select>
              <button
                type="button"
                onClick={() =>
                  onChange({
                    requirements: draft.requirements.filter((_, i) => i !== index),
                  })
                }
                className="text-[13px] text-ink-soft underline underline-offset-4 hover:text-ink"
              >
                删掉第 {index + 1} 条
              </button>
            </li>
          ))}
        </ul>
      )}

      <button
        type="button"
        onClick={() =>
          onChange({ requirements: [...draft.requirements, { text: "", hard: true }] })
        }
        className="mt-2 rounded-[12px] border border-line px-3 py-1.5 text-[13px] text-ink-soft hover:border-accent hover:text-ink"
      >
        加一条要求
      </button>
    </div>
  );
}

/**
 * 发不出去的时候说人话。
 *
 * 不原样抛后端那句话：后端的措辞是给工程师看的，而这一屏上要出现的是
 * 下一步能做什么。
 */
function whyNot(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) return "这个组织还没被校园核过，不能在这里招人。";
    if (e.status === 404) return "找不到这个组织，换一个再试。";
    if (e.status === 422) return "有一项没被认下来，检查一下角色和截止时间。";
  }
  return "这一下没发出去。你填的都还在，再点一次试试。";
}
