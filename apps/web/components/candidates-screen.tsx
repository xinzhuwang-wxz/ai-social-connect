"use client";

/**
 * 「谁说了愿意」：发起人挑人的那一屏。
 *
 * 旧链路让发起人挑一支队、然后等对方理不理他——把勇气花在一次抛硬币上。
 * 现在需求先投出去，答了愿意的人才进这一屏（ADR 0010）。
 *
 * 六条产品判断决定了它长成这样：
 *
 * 1. **屏上每一个人都已经说过愿意。** 这是整屏存在的理由，所以它要被写在
 *    最上面那句话里，而不是靠用户自己从"候选"两个字里推出来。
 *    不写的代价：他仍然会带着"我挑了会不会没人理"的心情去点，
 *    而那正是这条链路要消灭的东西。
 * 2. **排序与理由是 AI 给的，那一下是人点的。** 所以按钮上是「选 TA」，
 *    不是「采纳推荐」。换成后者，被选中的人就成了系统的决定——
 *    出了问题没有人能负责，而承诺只接受真人签名。
 * 3. **不给分数、不给百分比、不给名次。** 「匹配度 87%」用户既无从判断
 *    也无从反驳；逐条理由能被反驳，这正是它的价值。
 *    名次更糟：屏上的第 3 名会被当成"凑合"，而他明明说了愿意。
 * 4. **他自己写的那句话排在理由前面。** 系统的理由是关于他的，
 *    留言是他本人说的——后者更值钱，放在后面等于没有。
 * 5. **还没答的人只给数量不给名字。** 指名等于把"还没答"变成一条公开的
 *    怠慢记录；没答的人不欠任何人一个交代。
 * 6. **收满前先说清楚下一下会发生什么。** 最后一次点击会让这件事定下来、
 *    其余的人收到通知——事后才说，他会以为自己只是又选了一个人。
 *
 * 界面文案不使用领域词汇（见 docs/07 语言映射表）。
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";

import type { components } from "@/lib/api-types";
import { currentPrincipal } from "@/lib/session";

type Candidates = components["schemas"]["CandidatesOut"];
type Candidate = components["schemas"]["CandidateOut"];

/**
 * 这一屏自己的两次请求。
 *
 * 身份走请求头：服务端只按这个头认人，掉一个头就等于换了一个人在挑，
 * 而"挑人"是这条链路上唯一一个不可撤销的动作。
 */
async function ask(path: string, init?: RequestInit): Promise<Candidates> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Principal-Id": currentPrincipal(),
      ...init?.headers,
    },
  });
  if (!res.ok) throw new Error(`请求没能完成：${res.status}`);
  return (await res.json()) as Candidates;
}

const fetchCandidates = (intentId: string) =>
  ask(`/api/intents/${encodeURIComponent(intentId)}/candidates`);

const choose = (intentId: string, who: string) =>
  ask(
    `/api/intents/${encodeURIComponent(intentId)}/candidates/${encodeURIComponent(
      who,
    )}:choose`,
    { method: "POST" },
  );

export function CandidatesScreen({ intentId }: { intentId: string }) {
  const [data, setData] = useState<Candidates | null>(null);
  const [broken, setBroken] = useState(false);
  // 正在选的那一个。**按人记而不是记一个布尔**——否则一次点击会让整屏的
  // 按钮一起变灰，看起来像所有人都被选中了。
  const [picking, setPicking] = useState<string | null>(null);
  const [pickFailed, setPickFailed] = useState(false);

  const load = useCallback(async () => {
    setBroken(false);
    setData(null);
    try {
      setData(await fetchCandidates(intentId));
    } catch {
      setBroken(true);
    }
  }, [intentId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function pick(who: string) {
    setPicking(who);
    setPickFailed(false);
    try {
      setData(await choose(intentId, who));
    } catch {
      // 失败时**不改屏上任何东西**。把人挪进"已经选好的"再回滚，
      // 他会以为自己已经选过了，然后一直等一个不会来的人。
      setPickFailed(true);
    } finally {
      setPicking(null);
    }
  }

  if (broken) {
    return (
      <Shell>
        <section role="alert" className="rounded-[16px] border border-line bg-card p-5">
          <p className="text-[15px]">现在调不出说了愿意的人。</p>
          <p className="mt-1 text-[13px] text-ink-soft">
            没连上的时候不会替你选任何人，你回来再挑也不迟。
          </p>
          <button
            type="button"
            onClick={() => void load()}
            className="mt-4 rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-paper"
          >
            再试一次
          </button>
        </section>
      </Shell>
    );
  }

  if (data === null) {
    return (
      <Shell>
        <div className="space-y-3" aria-label="加载中">
          {[...Array(2)].map((_, i) => (
            <div key={i} className="h-40 animate-pulse rounded-[16px] bg-line" />
          ))}
        </div>
      </Shell>
    );
  }

  const full = data.still_need === 0;
  const nobody = data.chosen.length === 0 && data.willing.length === 0;

  return (
    <Shell
      lead={
        nobody
          ? undefined
          : "下面的人都已经说了愿意。你挑谁就是谁，不用再等一次回音。"
      }
    >
      {full ? (
        <Formed spaceId={data.space_id} />
      ) : (
        <p className="mb-5 text-[15px]">
          还差 {data.still_need} 个人。
          {data.still_need === 1 && data.willing.length > 0 && (
            // 在他点下去之前说，不是之后。事后说等于让他发现自己已经把
            // 别人拒掉了。
            <span className="text-pending">
              {" "}
              再选一个人就齐了——选完这件事就定下来，其余的人会知道这件事已经有人一起了。
            </span>
          )}
        </p>
      )}

      {nobody ? (
        <Nobody stillThinking={data.still_thinking} onRetry={() => void load()} />
      ) : (
        <div className="space-y-8">
          {data.chosen.length > 0 && (
            // 已经选好的单独一栏。混在一起时"我到底选了谁"要靠找按钮的有无
            // 来判断，而这是这一屏最不能含糊的一件事。
            <section aria-label="已经选好的" className="space-y-3">
              <h2 className="text-[13px] text-ink-soft">已经选好的</h2>
              {data.chosen.map((c) => (
                <Card key={c.principal_id} who={c} />
              ))}
            </section>
          )}

          <section aria-label="说了愿意的" className="space-y-3">
            <h2 className="text-[13px] text-ink-soft">说了愿意的</h2>
            {/* 收满之后这一栏就空了：多选出来的人进不了这件事，
                而一个点下去没反应的按钮比没有按钮更伤人。 */}
            {(full ? [] : data.willing).length === 0 ? (
              <p className="text-[14px] text-ink-soft">
                {full
                  ? "人齐了，不用再挑了。"
                  : "眼下没有新的人说愿意。有人答了会出现在这里。"}
              </p>
            ) : (
              data.willing.map((c) => (
                <Card
                  key={c.principal_id}
                  who={c}
                  onPick={() => void pick(c.principal_id)}
                  busy={picking === c.principal_id}
                  // 一次只让一个人的按钮转，其余的照常可点——
                  // 选错人的代价远大于多等一秒。
                  disabled={picking !== null && picking !== c.principal_id}
                />
              ))
            )}
          </section>

          {data.still_thinking > 0 && (
            // 只给数量。指名等于把"还没答"变成一条公开的怠慢记录。
            <section aria-label="还没答的">
              <p className="text-[14px] text-ink-soft">
                另外有 {data.still_thinking} 个人收到了，还没答。
              </p>
              <p className="mt-1 text-[13px] text-ink-faint">
                他们答了才会出现在上面。不用催，也不用一直守着。
              </p>
            </section>
          )}
        </div>
      )}

      {pickFailed && (
        <p role="alert" className="mt-5 text-[14px] text-clash">
          这一下没选上，没有人被选中。再点一次。
        </p>
      )}
    </Shell>
  );
}

function Shell({ lead, children }: { lead?: string; children: ReactNode }) {
  return (
    <main className="mx-auto w-full max-w-2xl px-5 py-10 sm:py-16">
      <header className="mb-6">
        <h1 className="text-[20px] font-semibold tracking-tight">谁说了愿意</h1>
        {lead && <p className="mt-1 text-[13px] text-ink-soft">{lead}</p>}
      </header>
      {children}
    </main>
  );
}

/** 收满了。**这一刻他最想去的是做事的地方**，不是回头再看一遍名单。 */
function Formed({ spaceId }: { spaceId?: string | null }) {
  return (
    <section
      aria-label="人齐了"
      className="mb-6 rounded-[16px] border border-line bg-accent-soft p-5 shadow-[var(--shadow-card)]"
    >
      <p className="text-[16px] font-medium text-accent">人齐了。</p>
      <p className="mt-1 text-[14px] text-ink-soft">
        剩下的人已经知道这件事有人一起了，你不用一个个去说。
      </p>
      {spaceId ? (
        <a
          href={`/spaces/${spaceId}`}
          className="mt-4 inline-block rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-paper"
        >
          去这件事的地方
        </a>
      ) : (
        <p className="mt-3 text-[13px] text-ink-faint">
          做事的地方正在开，刷新一下就能进去。
        </p>
      )}
    </section>
  );
}

/** 一个人都还没答。**不是白屏**——他需要知道这件事到底出去了没有。 */
function Nobody({
  stillThinking,
  onRetry,
}: {
  stillThinking: number;
  onRetry: () => void;
}) {
  return (
    <section
      aria-label="还没有人答"
      className="rounded-[16px] border border-line bg-card p-6 shadow-[var(--shadow-card)]"
    >
      {stillThinking > 0 ? (
        <>
          <p className="text-[16px]">投出去了 {stillThinking} 份，还没人答。</p>
          <p className="mt-2 text-[14px] text-ink-soft">
            说了愿意的人才会出现在这里，所以你不会看到一个不想来的人。
            有人答了这里就有，不用一直守着。
          </p>
        </>
      ) : (
        <>
          <p className="text-[16px]">这件事还没送到任何人手里。</p>
          <p className="mt-2 text-[14px] text-ink-soft">
            送出去要一点时间。等它到了别人那儿，说了愿意的人会出现在这里。
          </p>
        </>
      )}
      <button
        type="button"
        onClick={onRetry}
        className="mt-5 rounded-[12px] border border-line px-4 py-2 text-[14px]"
      >
        看看有没有新的
      </button>
    </section>
  );
}

function Card({
  who,
  onPick,
  busy = false,
  disabled = false,
}: {
  who: Candidate;
  onPick?: () => void;
  busy?: boolean;
  disabled?: boolean;
}) {
  return (
    <article
      aria-label={who.display_name}
      className={
        "rounded-[16px] border bg-card p-5 shadow-[var(--shadow-card)] " +
        (who.chosen ? "border-settled/40" : "border-line")
      }
    >
      <h3 className="text-[16px] font-medium">{who.display_name}</h3>

      {/* 他自己写的那句话。系统的理由是关于他的，这句是他本人说的——
          排在理由前面，因为它更值钱。 */}
      {who.note && (
        <p className="mt-2 rounded-[10px] bg-paper px-3 py-2 text-[15px]">
          「{who.note}」
        </p>
      )}

      <div className="mt-3">
        <h4 className="text-[13px] text-ink-soft">为什么是 TA</h4>
        {who.why.length === 0 ? (
          // 藏起来比说出来伤害大：他迟早会发现这一栏是空的。
          <p className="mt-1 text-[14px] text-ink-faint">
            这次没能说出理由。看 TA 自己写的那句话，或者先放着。
          </p>
        ) : (
          <ul className="mt-1.5 space-y-1.5">
            {who.why.map((line) => (
              <li key={line} className="text-[15px]">
                {line}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="mt-4 border-t border-line-soft pt-3">
        {who.chosen || !onPick ? (
          <span className="text-[14px] text-settled">你选了 TA</span>
        ) : (
          <button
            type="button"
            disabled={busy || disabled}
            onClick={onPick}
            className="rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-paper disabled:opacity-40"
          >
            {busy ? "选着…" : "选 TA"}
          </button>
        )}
      </div>
    </article>
  );
}
