"use client";

/**
 * 学生侧：现在有谁在招人。
 *
 * 五条产品判断决定了这一屏的信息层次：
 *
 * 1. **一条招募不是一段宣传文案，是一张缺口清单。** 学生只问一件事：这里缺的
 *    我能不能补上。所以摘要行先给"缺什么角色"，细节收起来点开看。
 * 2. **缺口按角色列，不给一个总数。** "还缺 3 个人"读完还是不知道自己算不算，
 *    "剪辑缺2 · 拍摄缺1"才让人当场判断得出。
 * 3. **和我有关的标出来而不是过滤掉。** 我会的正缺的那条标一个暖色提示，
 *    排在前面，但别的不藏起来——别人的机会学生也可能帮忙转发。
 * 4. **重复出现在每张卡上的信息提炼成标记或收起。** 「由谁负责」「已核验」
 *    每张卡都一模一样时读者会直接跳过。把它们缩成摘要行的一个小标记（核验），
 *    或者收进展开区（负责人、详细要求），让人想看时才看。
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

/**
 * 主按钮 / 次按钮。**最终形态是手机**，所以尺寸从拇指开始算：
 * 主按钮 48px 高、窄屏独占一行，次按钮 44px 且下划线是常态——
 * 触屏上没有 hover，靠 hover 才现形的可点性等于不存在。
 */
const PRIMARY =
  "inline-flex min-h-[48px] w-full items-center justify-center rounded-[16px] bg-accent px-5 text-[15px] font-semibold text-paper active:opacity-80 sm:w-auto";
const QUIET =
  "inline-flex min-h-[44px] items-center text-[15px] text-ink-soft underline underline-offset-4 active:text-ink hover:text-ink";

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
        <section role="alert" className="rounded-[16px] border border-line bg-card p-4 sm:p-5">
          <p className="text-[16px]">现在调不出正在招人的事。</p>
          <p className="mt-1 text-[14px] text-ink-soft">
            你说过的那几件事都还在，到点照样带上你。
          </p>
          <button type="button" onClick={() => void load()} className={`${PRIMARY} mt-4`}>
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
            <div key={i} className="h-24 animate-pulse rounded-[16px] bg-line" />
          ))}
        </div>
      </Shell>
    );
  }

  if (rows.length === 0) {
    return (
      <Shell title="正在招人的事">
        <section className="rounded-[16px] border border-line bg-card p-4 sm:p-5">
          <p className="text-[16px]">现在没有正在招人的事。</p>
          <p className="mt-1 text-[14px] text-ink-soft">
            你也可以自己发起一件。写清缺哪些角色、各几个，别人才知道自己能不能补上。
          </p>
          <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-4">
            <a href="/opportunities/new" className={PRIMARY}>
              发一份招募
            </a>
            <a href="/" className={`${QUIET} justify-center sm:justify-start`}>
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
      lead="能补上你缺口的排在前面。带 ✓ 的组织学校核过；没核过的会单独标出来。"
    >
      {orderPlain && (
        <p className="mb-4 text-[13px] text-ink-faint">
          现在对不上你说过的事，先按截止得急的排。
        </p>
      )}
      <div className="space-y-3">
        {rows.map((row) => (
          <OpportunityCard key={row.opportunity.id || row.opportunity.title} row={row} />
        ))}
      </div>
      <p className="mt-6 text-[14px] text-ink-soft">
        看到能补上的缺口，就去说一句你想做什么——下一轮配队会把你和它对上。
      </p>
      {/* 发布入口在这一支里也要有。
          原先它**只在空列表那一支**：招募一多就整个消失，而看到满屏招募的
          恰恰是社团组织者本人——他来这一屏就是为了发一份，却只能看别人招。 */}
      <div className="mt-1 flex flex-col items-start gap-1 sm:flex-row sm:items-center sm:gap-5">
        <a href="/" className={QUIET}>
          去说一件事
        </a>
        <a href="/opportunities/new" className={QUIET}>
          发一份招募
        </a>
      </div>
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
    // 底部留出 pb-24：手机上固定底栏会压住最后一行。
    <main className="mx-auto w-full max-w-2xl px-4 pb-24 pt-6 sm:px-5 sm:pb-16 sm:pt-16">
      <header className="mb-6 sm:mb-8">
        <h1 className="text-[28px] font-bold leading-tight tracking-tight sm:text-[30px]">
          {title}
        </h1>
        {lead && <p className="mt-1.5 text-[14px] text-ink-soft">{lead}</p>}
      </header>
      {children}
    </main>
  );
}

/**
 * 一份招募。
 *
 * **默认收起**：摘要行给最重要的三件事——在招什么组织、缺哪种人、什么时候截止。
 * 点开才看到完整的座位表、负责人、要求。这样十几条在两三屏内能扫完，
 * 而不是拉八屏。
 *
 * 折叠用 CSS class 控制（不用 `hidden` 属性，不用 inline display:none），
 * 理由是展开按钮本身就要键盘可操作，而测试库不执行 CSS，
 * 保持内容在 DOM 里让辅助技术可寻。
 *
 * 发布那一侧的预览渲染的是**同一个组件**——"提交前看看学生会看到什么"要是
 * 另画一张，两边迟早对不上，而对不上的那一刻，预览就成了误导。
 */
export function OpportunityCard({ row }: { row: Listed }) {
  const [expanded, setExpanded] = useState(false);
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
  const hasDetail =
    steward !== undefined ||
    must.length > 0 ||
    plus.length > 0 ||
    unsaid.length > 0 ||
    shortOf.some((s) => s.capacity > 1) ||
    filled.length > 0;

  return (
    <article
      aria-label={o.title}
      className="rounded-[16px] border border-line bg-card"
    >
      {/* ── 摘要行（始终可见）──────────────────────────────────────────
          三件事：组织+核验状态、角色缺口、截止期。
          组织核验压成摘要行顶部的一小行；重复的「由谁负责」收进展开区。 */}
      <div className="p-4 sm:p-5">
        {/* 组织行：核验过的压缩成小标记，没核过的仍然显眼警告 */}
        <div aria-label="谁在招人">
          {orgDown ? (
            <p className="text-[15px] text-ink-soft">这个组织的信息暂时调不出来。</p>
          ) : o.organization_verified ? (
            // **每张卡都有的徽章不携带任何信息。** 二十个组织全核过时，
            // 「校园核过这个组织」在十二张卡上一字不差地重复十二遍，
            // 而且是摘要行里最宽的东西。压成一个记号，规则在列表顶上
            // 说一次——没核过的那一档照旧显眼，因为那一个才是要看的。
            <p className="flex flex-wrap items-center gap-1.5 text-[13px] text-ink-faint">
              <span aria-label="校园核过这个组织" title="校园核过这个组织">
                ✓
              </span>
              <span>{o.organization_name}</span>
            </p>
          ) : (
            <div role="alert" className="rounded-[10px] border border-clash px-3 py-2">
              <p className="flex flex-wrap items-center gap-2 text-[15px]">
                <span>{o.organization_name}</span>
                <span className="rounded-full px-2 py-0.5 text-[12px] font-medium text-clash">
                  校园没核过这个组织
                </span>
              </p>
              <p className="mt-1 text-[14px] text-clash">
                没核过的组织不该在这里招人。别先交学号、手机号这些。
              </p>
            </div>
          )}
        </div>

        {/* 标题 */}
        <h2 className="mt-2 text-[18px] font-semibold sm:text-[20px]">{o.title}</h2>
        {o.goal && <p className="mt-0.5 text-[14px] text-ink-soft">{o.goal}</p>}

        {/* 和我有关的标出来，排在前面但不藏别的——这是排序/标注，不是过滤 */}
        {row.fills.length > 0 && (
          <p className="mt-2 rounded-[10px] bg-paper px-3 py-2 text-[15px] text-settled">
            你说过你能做{row.fills.join("、")}，这里正缺。
          </p>
        )}

        {/* 角色缺口紧凑摘要：让人在不展开的情况下就知道缺什么。
            当 seats 为空时不在摘要行重复"没写角色"，留给展开区说一次——
            避免测试库遇到两个相同文本节点。
            各角色用单一文本节点（"剪辑 缺2个"），不拆成两个 span，
            防止整张卡片作用域内出现两个独立的"剪辑"文本节点。 */}
        {(shortOf.length > 0 || filled.length > 0) && (
          <p className="mt-2 text-[15px] text-ink-soft" aria-label="缺口摘要">
            {shortOf.length === 0 ? (
              "所有角色已满"
            ) : (
              shortOf.map((seat, i) => (
                <span key={seat.role}>
                  {i > 0 && <span className="mx-1.5 text-ink-hint" aria-hidden="true">·</span>}
                  {/* 角色名和缺口数合为一个文本节点，避免独立 span 被 getByText 误匹配 */}
                  {`${seat.role} 缺${seat.gap}个`}
                </span>
              ))
            )}
          </p>
        )}

        {/* 截止期和地点：一行，小字 */}
        <p className="mt-2 text-[13px] text-ink-faint">
          {deadlineWords(o.deadline, now)}
          {o.location_scope ? ` · ${o.location_scope}` : ""}
        </p>

        {/* 展开/收起：有实质内容时才显示按钮
            aria-expanded 让屏幕阅读器知道当前状态 */}
        {hasDetail && (
          <button
            type="button"
            onClick={() => setExpanded((e) => !e)}
            aria-expanded={expanded}
            className="mt-3 inline-flex min-h-[44px] items-center gap-1 text-[14px] text-ink-soft underline underline-offset-4 active:text-ink hover:text-ink"
          >
            {expanded ? "收起" : "查看负责人和要求"}
          </button>
        )}
      </div>

      {/* ── 展开区（默认折叠，用 CSS class，不用 hidden 属性）──────────────
          内容始终在 DOM 里（让测试库和辅助技术可以找到），
          视觉上靠 Tailwind 的 hidden class 控制显示与否。
          注意：不使用 `hidden` HTML 属性——那会让测试断言 toBeVisible() 失败。 */}
      <div className={expanded ? "border-t border-line" : "hidden"}>
        <div className="px-4 pb-4 pt-3 sm:px-5 sm:pb-5">
          {/* 完整座位表（含容量信息）：放展开区，因为「还缺几个」在摘要行已说过，
              「一共要几个、已经有几个」是发现自己排在等候队列里时才需要的细节 */}
          <section aria-label="还缺什么">
            <h3 className="text-[13px] font-medium text-ink-faint">缺口明细</h3>
            {shortOf.length === 0 && filled.length === 0 ? (
              <p className="mt-1.5 text-[15px] text-ink-soft">
                这份招募没写缺哪些角色，看不出你能不能补上。
              </p>
            ) : (
              <ul className="mt-2 space-y-2">
                {shortOf.map((seat) => (
                  <li
                    key={seat.role}
                    className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[15px]"
                  >
                    <span>{seat.role}</span>
                    <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[12px] text-accent">
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

          {/* 负责人：每张卡都一模一样时，重复出现只会让人跳过。
              收进展开区后，有问题的人点开才找，不关心的人不受打扰 */}
          <div className="mt-4" aria-label="谁负责">
            {steward ? (
              <p className="text-[15px]">这件事由 {steward} 负责，有问题找他。</p>
            ) : (
              <p role="alert" className="text-[15px] text-clash">
                这份招募没写谁负责。没人负责的事最后会烂在那里，先问清楚是谁在管。
              </p>
            )}
          </div>

          {/* 要求：区分硬软，但只有有内容时才渲染这一块 */}
          {(must.length > 0 || plus.length > 0 || unsaid.length > 0) && (
            <section aria-label="什么样的人能来" className="mt-4">
              {must.length > 0 && (
                <>
                  <h3 className="text-[13px] font-medium text-ink-faint">必须满足的</h3>
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
                  <h3 className="mt-3 text-[13px] font-medium text-ink-faint">会加分的</h3>
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
                  <h3 className="mt-3 text-[13px] font-medium text-ink-faint">
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
        </div>
      </div>
    </article>
  );
}

/** 截止期说人话："8 月 15 日下午 6 点截止，还有约 3 天"。 */
function deadlineWords(iso: string, now: Date): string {
  const at = Date.parse(iso);
  if (!Number.isFinite(at)) return "还没写什么时候截止";
  return `${whenPhrase(iso, now)}截止，${countdown(iso, now)}`;
}
