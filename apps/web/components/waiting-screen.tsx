"use client";

/**
 * 第三屏：等配队。
 *
 * 四条产品判断决定了这一屏长成现在这样：
 *
 * 1. **光说"请稍候"用户会走掉。** 等待本身没法缩短，但它可以变得有信息：
 *    下次什么时候配、这个方向上现在缺什么、有多少人也在等。知道"12 个人缺剪辑、
 *    只有 3 个人会"，用户才判断得出该改需求、该去拉人、还是该自己顶上。
 * 2. **只有聚合数，没有名字。** "缺什么"是公共信息，"谁在等"是别人的事。
 *    这一条写在界面上而不只是实现里——用户看不到我们没显示什么。
 * 3. **这一屏不是只读的。** 等待期正是最该允许改需求的时候：用户刚看完缺口，
 *    手里就有改的理由。做成只读等于让他看着数字干着急。
 * 4. **时间说人话。** "明早 8 点开始配队"，不是一串时间戳。
 *
 * `ReviseCard` 与 `whenPhrase` 由另两屏共用，所以从这里导出：改需求和
 * 时间说法各自只能有一处实现，两处迟早会不一致（比如一边漏掉"改完要重新
 * 送回队列"，用户就会悄无声息地退出配队）。
 *
 * 界面文案不使用领域词汇（见 docs/07 语言映射表）。
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { toContentIn, type Intent } from "@/lib/api";
import {
  myWaitingIntents,
  reviseAndReconfirm,
  runClearing,
  waitingNow,
  type ClearingReport,
  type Gap,
  type Waiting,
} from "@/lib/matching";

export function WaitingScreen() {
  const [pulse, setPulse] = useState<Waiting | null>(null);
  const [pulseFailed, setPulseFailed] = useState(false);
  const [mine, setMine] = useState<Intent[] | null>(null);
  // 拿不到"我在等什么"不该拖垮整屏：下次配队时间和缺口是公共信息，照常显示。
  const [mineDown, setMineDown] = useState(false);
  const [ran, setRan] = useState<ClearingReport | null>(null);

  const loadMine = useCallback(async () => {
    try {
      setMine(await myWaitingIntents());
      setMineDown(false);
    } catch {
      setMineDown(true);
    }
  }, []);

  const load = useCallback(async () => {
    setPulseFailed(false);
    setPulse(null);
    void loadMine();
    try {
      setPulse(await waitingNow());
    } catch {
      setPulseFailed(true);
    }
  }, [loadMine]);

  useEffect(() => {
    void load();
  }, [load]);

  async function again() {
    try {
      setRan(await runClearing());
    } catch {
      // 配一轮没跑起来不值得报错打断：下一次到点照样会配。
    }
    void load();
  }

  if (pulseFailed) return <Shell><LoadFailed onRetry={() => void load()} /></Shell>;
  if (pulse === null) return <Shell><Loading /></Shell>;

  const now = new Date();
  const scarce = new Set(pulse.gaps.filter((g) => g.scarce).map((g) => g.skill));

  return (
    <Shell>
      <header className="mb-8">
        <h1 className="text-[20px] font-semibold tracking-tight">
          {whenPhrase(pulse.next_round_at, now)}开始配队
        </h1>
        <p className="mt-1 text-[13px] text-ink-soft">
          {countdown(pulse.next_round_at, now)}。
          {pulse.waiting_count > 1
            ? `这个方向上现在有 ${pulse.waiting_count} 个人在等。`
            : "这个方向上现在只有你在等。"}
        </p>
      </header>

      <section aria-label="现在缺什么" className="rounded-[16px] border border-line bg-card p-5">
        <h2 className="text-[16px] font-medium">现在缺什么</h2>
        <p className="mt-1 text-[13px] text-ink-faint">
          这里只有人数，没有名字。
        </p>

        {pulse.gaps.length === 0 ? (
          // 空态：说清为什么空，并给一条能走的路。
          <div className="mt-4">
            <p className="text-[15px]">还没有人写下自己缺什么，所以这里是空的。</p>
            <p className="mt-1 text-[13px] text-ink-soft">
              你写清缺什么，下一轮就有人能对上。
            </p>
          </div>
        ) : (
          <ul className="mt-4 space-y-2.5">
            {pulse.gaps.map((gap) => (
              <GapRow key={gap.skill} gap={gap} />
            ))}
          </ul>
        )}
      </section>

      <section aria-label="我在等的事" className="mt-6">
        <h2 className="text-[16px] font-medium">你在等的事</h2>

        {mineDown && (
          <p className="mt-2 text-[14px] text-ink-soft">
            现在调不出你在等的那几件事。上面这些照常，等会儿再回来就能改了。
          </p>
        )}

        {!mineDown && mine === null && <Loading />}

        {/* 首次：还没有任何在等的事，给一条引导，不是一片空白。 */}
        {!mineDown && mine !== null && mine.length === 0 && (
          <div className="mt-2 rounded-[16px] border border-line bg-card p-5">
            <p className="text-[15px]">你还没有正在等配队的事。</p>
            <p className="mt-1 text-[13px] text-ink-soft">
              说一句你想做什么，下一轮就带上你。
            </p>
            <a
              href="/"
              className="mt-4 inline-block rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white"
            >
              去说一件事
            </a>
          </div>
        )}

        {!mineDown && mine !== null && mine.length > 0 && (
          <div className="mt-2 space-y-3">
            {mine.map((intent) => (
              <article
                key={intent.id}
                aria-label={intent.content.goal}
                className="rounded-[16px] border border-line bg-card p-5"
              >
                <p className="text-[15px]">{intent.content.goal}</p>
                <ReviseCard
                  intent={intent}
                  scarce={scarce}
                  canRevise={pulse.can_still_revise}
                  onDone={() => void loadMine()}
                />
                <a
                  href={`/intents/${intent.id}/teams`}
                  className="mt-4 inline-block text-[14px] text-ink-soft underline underline-offset-4 hover:text-ink"
                >
                  看看给你找的人
                </a>
              </article>
            ))}
          </div>
        )}
      </section>

      <div className="mt-8 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void again()}
          className="text-[14px] text-ink-soft underline underline-offset-4 hover:text-ink"
        >
          现在就配一次
        </button>
        <span className="text-[13px] text-ink-faint">
          {ran
            ? `这一轮看了 ${ran.considered} 件事，配成 ${ran.proposed} 个小队。`
            : "到点会自动配，不用一直守着。"}
        </span>
      </div>
    </Shell>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return <main className="mx-auto w-full max-w-2xl px-5 py-10 sm:py-16">{children}</main>;
}

/** 一样本事：多少人要、多少人会。缺口大的排前面，那是最该知道的一行。 */
function GapRow({ gap }: { gap: Gap }) {
  return (
    <li className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <span className="text-[15px]">{gap.skill}</span>
      <span className="text-[13px] text-ink-soft">
        {gap.wanted} 个人要，{gap.offered} 个人会
      </span>
      {gap.scarce && (
        <span className="rounded-[4px] bg-accent-soft px-1.5 py-0.5 text-[11px] text-accent">
          还缺 {gap.wanted - gap.offered} 个
        </span>
      )}
    </li>
  );
}

/**
 * 改需求。
 *
 * 「还差这几件事」那一屏也用它——**改需求只能有一处实现**。两屏各写一遍，
 * 迟早会有一边漏掉"改完要重新送回队列"这一步，而漏掉的那一边会让用户
 * 悄无声息地退出配队。
 *
 * 快捷动作只给稀缺的那几样：系统知道这一样难找，才谈得上建议你自己顶上。
 */
export function ReviseCard({
  intent,
  scarce,
  canRevise = true,
  onDone,
}: {
  intent: Intent;
  scarce?: Set<string>;
  canRevise?: boolean;
  onDone?: () => void;
}) {
  const original = intent.content.needs.join("、");
  const [text, setText] = useState(original);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [done, setDone] = useState(false);

  async function save(needs: string[], offers: string[]) {
    setBusy(true);
    setFailed(false);
    try {
      await reviseAndReconfirm(intent, {
        ...toContentIn(intent.content),
        needs,
        offers,
      });
      // 输入框跟着服务端认下的内容走。快捷动作改的是 needs 本身，
      // 不同步的话输入框里会留着改前的旧文本，下一次点「改好了」就把它写回去。
      setText(needs.join("、"));
      setDone(true);
      onDone?.();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  const typed = split(text);
  const changed = typed.join("、") !== original;
  const mine = intent.content.needs.filter((n) => scarce?.has(n));

  if (!canRevise) {
    return (
      <p className="mt-3 text-[13px] text-ink-soft">
        这一轮已经开始配了，改动从下一轮起算。
      </p>
    );
  }

  return (
    <div className="mt-3">
      <label className="block">
        <span className="text-[13px] text-ink-soft">我缺</span>
        <input
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setDone(false);
          }}
          placeholder="用、隔开"
          aria-label="我缺"
          className="mt-1 w-full rounded-[8px] border border-line px-3 py-2 text-[15px] outline-none placeholder:text-ink-faint focus:border-accent"
        />
      </label>

      <div className="mt-2 flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={busy || !changed}
          onClick={() => void save(typed, intent.content.offers)}
          className="rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white disabled:opacity-35"
        >
          {busy ? "改着…" : "改好了"}
        </button>
        {done && !failed && (
          <span role="status" className="text-[13px] text-ink-soft">
            改好了，下一轮按新的来。
          </span>
        )}
      </div>

      {mine.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {mine.map((skill) => (
            <button
              key={skill}
              type="button"
              disabled={busy}
              onClick={() =>
                void save(
                  intent.content.needs.filter((n) => n !== skill),
                  [...intent.content.offers, skill],
                )
              }
              className="rounded-[12px] border border-line px-3 py-1.5 text-[13px] text-ink-soft hover:border-accent hover:text-ink"
            >
              「{skill}」这一样我自己来
            </button>
          ))}
        </div>
      )}

      {failed && (
        <p role="alert" className="mt-2 text-[13px] text-clash">
          这一下没改上，你写的还在，再点一次试试。
        </p>
      )}
    </div>
  );
}

function split(text: string): string[] {
  return text
    .split(/[、,，]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function Loading() {
  return (
    <div className="mt-2 space-y-3" aria-label="加载中">
      {[...Array(3)].map((_, i) => (
        <div key={i} className="h-16 animate-pulse rounded-[16px] bg-line" />
      ))}
    </div>
  );
}

/** 错误态：说清哪里断了、下一步做什么，不出现错误码。 */
function LoadFailed({ onRetry }: { onRetry: () => void }) {
  return (
    <section role="alert" className="rounded-[16px] border border-line bg-card p-5">
      <p className="text-[15px]">现在查不到下次什么时候配队。</p>
      <p className="mt-1 text-[13px] text-ink-soft">
        你说过的那几件事都还在，到点照样带上你。
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white"
      >
        再看一次
      </button>
    </section>
  );
}

// --- 时间说人话 -------------------------------------------------------------

const PARTS = [
  [5, "凌晨"],
  [11, "早上"],
  [13, "中午"],
  [18, "下午"],
  [24, "晚上"],
] as const;

function clock(d: Date): string {
  const h = d.getHours();
  const part = PARTS.find(([end]) => h < end)?.[1] ?? "晚上";
  const twelve = h % 12 === 0 ? 12 : h % 12;
  const m = d.getMinutes();
  return `${part} ${twelve} 点${m === 0 ? "" : m === 30 ? "半" : ` ${m}`}`;
}

/** "明早 8 点"，不是 "2026-08-13T08:00:00+08:00"。 */
export function whenPhrase(iso: string, now: Date): string {
  const t = new Date(iso);
  const days = Math.round(
    (new Date(t.getFullYear(), t.getMonth(), t.getDate()).getTime() -
      new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()) /
      86400000,
  );
  const time = clock(t);
  if (days === 1 && time.startsWith("早上")) return `明早${time.slice(2)}`;
  const day =
    days <= 0 ? "今天" : days === 1 ? "明天" : days === 2 ? "后天" : `${t.getMonth() + 1} 月 ${t.getDate()} 日`;
  return `${day}${time}`;
}

/** 只到小时。"还有 2 小时 13 分"精确得毫无用处，还会让人盯着看。 */
export function countdown(iso: string, now: Date): string {
  const ms = new Date(iso).getTime() - now.getTime();
  if (ms <= 0) return "就这一会儿";
  const hours = ms / 3_600_000;
  if (hours < 1) return "还有不到 1 小时";
  if (hours < 24) return `还有约 ${Math.round(hours)} 小时`;
  return `还有约 ${Math.round(hours / 24)} 天`;
}
