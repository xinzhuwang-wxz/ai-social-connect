"use client";

/**
 * 学生侧：现在有谁在招人。
 *
 * 五条产品判断决定了这一屏长成现在这样：
 *
 * 1. **一条招募不是一段宣传文案，是一张缺口清单。** 学生只问一件事：这里缺的
 *    我能不能补上。所以每一行是"什么角色、还缺几个"，不是"诚邀热爱者加入"。
 * 2. **缺口按角色列，不给一个总数。** "还缺 3 个人"读完还是不知道自己算不算，
 *    "剪辑还缺 2 个、拍摄还缺 1 个"才让人当场判断得出。
 * 3. **组织核没核过要显眼。** 学生要靠它判断这不是一个用来收集信息的假项目。
 *    未核过的组织本来就不该发招募，所以列表里出现的都是核过的——但这件事
 *    要说出来。说不出来，那份安全就只存在于后端，学生感受不到。
 * 4. **一定要显示真人负责人。** 没人负责的事最后会烂在那里，而"烂在那里"的
 *    代价是学生付的。后端还没把负责人透出来时，这里明说没写，不留白。
 * 5. **排序按"我能补上哪个缺口"，不按发布时间。** 时间序是给发布方看的。
 *
 * 界面文案不使用领域词汇（见 docs/07 语言映射表）。
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";

import {
  ORG_UNKNOWN,
  arrange,
  openOpportunities,
  readRequirement,
  whatICanDo,
  type Listed,
} from "@/lib/opportunities";

import { countdown, whenPhrase } from "./waiting-screen";

export function OpportunityList() {
  const [rows, setRows] = useState<Listed[] | null>(null);
  const [failed, setFailed] = useState(false);
  // 降级：读不到"我说过我能出什么"只影响顺序，不该让整屏空着。
  const [orderPlain, setOrderPlain] = useState(false);

  const load = useCallback(async () => {
    setFailed(false);
    setRows(null);
    let canDo: string[] = [];
    let plain = false;
    try {
      canDo = await whatICanDo();
    } catch {
      plain = true;
    }
    setOrderPlain(plain);
    try {
      setRows(arrange(await openOpportunities(), canDo));
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (failed) {
    return (
      <Shell title="正在招人的事">
        <section role="alert" className="rounded-[16px] border border-line bg-card p-5">
          <p className="text-[15px]">现在调不出正在招人的事。</p>
          <p className="mt-1 text-[13px] text-ink-soft">
            你说过的那几件事都还在，到点照样带上你。
          </p>
          <button
            type="button"
            onClick={() => void load()}
            className="mt-4 rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white"
          >
            再看一次
          </button>
        </section>
      </Shell>
    );
  }

  if (rows === null) {
    return (
      <Shell title="正在招人的事">
        <div className="space-y-3" aria-label="加载中">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-40 animate-pulse rounded-[16px] bg-line" />
          ))}
        </div>
      </Shell>
    );
  }

  if (rows.length === 0) {
    return (
      <Shell title="正在招人的事">
        <section className="rounded-[16px] border border-line bg-card p-5">
          <p className="text-[15px]">现在没有正在招人的事。</p>
          <p className="mt-1 text-[13px] text-ink-soft">
            你也可以自己发起一件。写清缺哪些角色、各几个，别人才知道自己能不能补上。
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <a
              href="/opportunities/new"
              className="rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white"
            >
              发一份招募
            </a>
            <a
              href="/"
              className="text-[14px] text-ink-soft underline underline-offset-4 hover:text-ink"
            >
              先说说我想做什么
            </a>
          </div>
        </section>
      </Shell>
    );
  }

  return (
    <Shell
      title="正在招人的事"
      lead="能补上你缺口的排在前面。每一条都写清了还缺什么、缺几个、谁负责。"
    >
      {orderPlain && (
        <p className="mb-4 text-[13px] text-ink-faint">
          现在对不上你说过的事，先按截止得急的排。
        </p>
      )}
      <div className="space-y-6">
        {rows.map((row) => (
          <OpportunityCard key={row.opportunity.id || row.opportunity.title} row={row} />
        ))}
      </div>
      <p className="mt-8 text-[13px] text-ink-soft">
        看到能补上的缺口，就去说一句你想做什么——下一轮配队会把你和它对上。
      </p>
      <a
        href="/"
        className="mt-1 inline-block text-[14px] text-ink-soft underline underline-offset-4 hover:text-ink"
      >
        去说一件事
      </a>
    </Shell>
  );
}

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

/**
 * 一份招募。
 *
 * 发布那一侧的预览渲染的是**同一个组件**——"提交前看看学生会看到什么"要是
 * 另画一张，两边迟早对不上，而对不上的那一刻，预览就成了误导。
 */
export function OpportunityCard({ row }: { row: Listed }) {
  const o = row.opportunity;
  const now = new Date();
  const orgDown = o.organization_name === ORG_UNKNOWN;
  const shortOf = o.seats.filter((seat) => seat.gap > 0);
  const filled = o.seats.filter((seat) => seat.gap === 0);
  const asked = o.qualifications.map(readRequirement);
  const must = asked.filter((r) => r.hard === true);
  const plus = asked.filter((r) => r.hard === false);
  const unsaid = asked.filter((r) => r.hard === null);
  const steward = o.steward_name?.trim();

  return (
    <article
      aria-label={o.title}
      className="rounded-[16px] border border-line bg-card p-5"
    >
      <h2 className="text-[16px] font-medium">{o.title}</h2>
      {o.goal && <p className="mt-1 text-[15px] text-ink-soft">{o.goal}</p>}

      <div className="mt-3" aria-label="谁在招人">
        {orgDown ? (
          <p className="text-[14px] text-ink-soft">这个组织的信息暂时调不出来。</p>
        ) : o.organization_verified ? (
          <p className="flex flex-wrap items-center gap-2 text-[14px]">
            <span>{o.organization_name}</span>
            <span className="rounded-[4px] bg-accent-soft px-1.5 py-0.5 text-[11px] text-settled">
              校园核过这个组织
            </span>
          </p>
        ) : (
          <div role="alert" className="rounded-[8px] border border-clash px-3 py-2">
            <p className="flex flex-wrap items-center gap-2 text-[14px]">
              <span>{o.organization_name}</span>
              <span className="rounded-[4px] px-1.5 py-0.5 text-[11px] font-medium text-clash">
                校园没核过这个组织
              </span>
            </p>
            <p className="mt-1 text-[13px] text-clash">
              没核过的组织不该在这里招人。别先交学号、手机号这些。
            </p>
          </div>
        )}
      </div>

      <div className="mt-3" aria-label="谁负责">
        {steward ? (
          <p className="text-[14px]">这件事由 {steward} 负责，有问题找他。</p>
        ) : (
          <p role="alert" className="text-[14px] text-clash">
            这份招募没写谁负责。没人负责的事最后会烂在那里，先问清楚是谁在管。
          </p>
        )}
      </div>

      <section aria-label="还缺什么" className="mt-4">
        <h3 className="text-[13px] text-ink-soft">还缺什么</h3>
        {shortOf.length === 0 && filled.length === 0 ? (
          <p className="mt-1.5 text-[14px] text-ink-soft">
            这份招募没写缺哪些角色，看不出你能不能补上。
          </p>
        ) : (
          <ul className="mt-1.5 space-y-1.5">
            {shortOf.map((seat) => (
              <li
                key={seat.role}
                className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[15px]"
              >
                <span>{seat.role}</span>
                <span className="rounded-[4px] bg-accent-soft px-1.5 py-0.5 text-[11px] text-accent">
                  还缺 {seat.gap} 个
                </span>
                <span className="text-[13px] text-ink-faint">
                  一共要 {seat.capacity} 个，已经有 {seat.filled} 个
                </span>
              </li>
            ))}
            {filled.map((seat) => (
              <li key={seat.role} className="text-[15px] text-ink-faint">
                {seat.role} 已经满了
              </li>
            ))}
          </ul>
        )}
      </section>

      {row.fills.length > 0 && (
        <p className="mt-3 rounded-[8px] bg-paper px-3 py-2 text-[14px] text-settled">
          你说过你能做{row.fills.join("、")}，这里正缺。
        </p>
      )}

      {(must.length > 0 || plus.length > 0 || unsaid.length > 0) && (
        <section aria-label="什么样的人能来" className="mt-4">
          {must.length > 0 && (
            <>
              <h3 className="text-[13px] text-ink-soft">必须满足的</h3>
              <ul className="mt-1 space-y-1">
                {must.map((r) => (
                  <li key={r.text} className="text-[15px]">
                    {r.text}
                  </li>
                ))}
              </ul>
            </>
          )}
          {plus.length > 0 && (
            <>
              <h3 className="mt-3 text-[13px] text-ink-soft">会加分的</h3>
              <ul className="mt-1 space-y-1">
                {plus.map((r) => (
                  <li key={r.text} className="text-[15px] text-ink-soft">
                    {r.text}
                  </li>
                ))}
              </ul>
            </>
          )}
          {unsaid.length > 0 && (
            <>
              <h3 className="mt-3 text-[13px] text-ink-soft">
                这几条没说清是必须还是加分
              </h3>
              <ul className="mt-1 space-y-1">
                {unsaid.map((r) => (
                  <li key={r.text} className="text-[15px] text-ink-soft">
                    {r.text}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}

      <p className="mt-4 text-[13px] text-ink-faint">
        {deadlineWords(o.deadline, now)}
        {o.location_scope ? ` · ${o.location_scope}` : ""}
      </p>
    </article>
  );
}

/** 截止期说人话："8 月 15 日下午 6 点截止，还有约 3 天"。 */
function deadlineWords(iso: string, now: Date): string {
  const at = Date.parse(iso);
  if (!Number.isFinite(at)) return "还没写什么时候截止";
  return `${whenPhrase(iso, now)}截止，${countdown(iso, now)}`;
}
