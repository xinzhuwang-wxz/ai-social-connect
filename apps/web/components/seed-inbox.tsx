"use client";

/**
 * 信箱：有人想找你一起做一件事。
 *
 * 这是投递制里被找到的那一侧（ADR 0010）。他收到的不再是"要不要加入这支队"，
 * 而是"要不要参与这件事"——挑人那一下发生在他表态之后，由发起人来点。
 *
 * ## 六条产品判断决定了它长成这样
 *
 * 1. **完整展示行动信息，有限展示发起人信息。** 他要判断的是这件事值不值得
 *    参与，不是这个人够不够格。所以做什么、什么时候、在哪、要几个人、缺什么
 *    一样不少，而发起人只给一个名字。反过来做就是把它变成看人下菜的界面，
 *    而看人的界面里，普通人永远选不上。
 * 2. **说了愿意不等于已经加入，这句话必须在按钮旁边。** 写在别处等于没写：
 *    他点完就走了。不说的代价是他以为自己已经答应了，然后在没被挑中时
 *    觉得被放了鸽子——那是一次本可以避免的伤害。
 * 3. **不感兴趣和愿意一样便宜。** 一步完成、不二次确认、不问为什么。
 *    要用摩擦力换的是承诺，不是拒绝——反过来做就是在换同意率。
 * 4. **留言是可选的。** 要求写一句理由才能说愿意，会让人不敢点愿意；
 *    而一个不敢表态的候选，对发起人等于不存在。
 * 5. **不给排名、不给还有几个人也说了愿意、不给分数。** 知道自己是第几个
 *    只会让人退出，而这里本来就没有评价。"为什么找到你"逐条说事实，
 *    不折成一个数——一个数字既解释不了什么，又会被当成对人的判定。
 * 6. **答过的卡不撤走，就地显示答了什么。** 卡片在指头底下消失，读起来像
 *    "我刚才那一下到底算不算"。
 *
 * 界面文案不使用领域词汇（见 docs/07 语言映射表）；状态用世界观的词，
 * 动作和承诺只用朴素词（ADR 0009）。
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { mySeeds, respondToSeed, type Seed } from "@/lib/seeds";

export function SeedInbox() {
  const [seeds, setSeeds] = useState<Seed[] | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setFailed(false);
    setSeeds(null);
    try {
      setSeeds(await mySeeds());
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (failed) {
    return (
      <Shell>
        <section
          role="alert"
          className="rounded-[16px] border border-line bg-card p-5 shadow-[var(--shadow-card)]"
        >
          <p className="text-[15px]">现在打不开你的信箱。</p>
          {/* 断网时最该说的不是"出错了"，是"你什么都没答应"。
              没有这一句，他会怀疑自己刚才那一下是不是已经发出去了。 */}
          <p className="mt-1 text-[13px] text-ink-soft">
            没连上的时候不会替你答复任何人，你回来再决定也不迟。
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

  if (seeds === null) {
    return (
      <Shell>
        <div role="status" aria-label="加载中" className="space-y-3">
          {[0, 1].map((i) => (
            <div key={i} className="h-44 animate-pulse rounded-[16px] bg-line" />
          ))}
        </div>
      </Shell>
    );
  }

  if (seeds.length === 0) {
    return (
      <Shell>
        <section className="rounded-[16px] border border-line bg-card p-6 shadow-[var(--shadow-card)]">
          <p className="text-[16px]">现在没有人找你。</p>
          {/* 空信箱最常见的原因不是"没人发事"，是他从没说过自己能做什么。
              只说"暂时没有"等于让他回来刷——而刷不出东西的人不会回来第三次。 */}
          <p className="mt-2 text-[14px] text-ink-soft">
            这里只放别人想拉你一起做的事。先说说你能做什么、想参与什么——
            没有这一步，别人缺人的时候找不到你。
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-4">
            <a
              href="/me/about"
              className="rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-paper"
            >
              填一下我这边
            </a>
            <a href="/" className="text-[14px] text-ink-soft underline underline-offset-4 hover:text-ink">
              我自己发起一件事
            </a>
          </div>
        </section>
      </Shell>
    );
  }

  const waiting = seeds.filter((s) => s.state === "delivered").length;

  return (
    <Shell
      lead={
        waiting > 0
          ? `有 ${waiting} 件事想找你一起做。看看要不要参与，不参与也不用解释。`
          : "这几件事你都看过了。"
      }
    >
      <div className="space-y-6">
        {seeds.map((seed) => (
          <SeedCard
            key={seed.intent_id}
            seed={seed}
            onAnswered={(next) =>
              setSeeds((all) =>
                (all ?? []).map((s) => (s.intent_id === next.intent_id ? next : s)),
              )
            }
          />
        ))}
      </div>
    </Shell>
  );
}

function Shell({ lead, children }: { lead?: string; children: ReactNode }) {
  return (
    <main className="mx-auto w-full max-w-2xl px-5 py-10 sm:py-16">
      <header className="mb-8">
        <h1 className="text-[20px] font-semibold tracking-tight">信箱</h1>
        {lead && <p className="mt-1 text-[13px] text-ink-soft">{lead}</p>}
      </header>
      {children}
    </main>
  );
}

function SeedCard({
  seed,
  onAnswered,
}: {
  seed: Seed;
  onAnswered: (next: Seed) => void;
}) {
  const [saying, setSaying] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  // 「以后类似的叫我」和「不感兴趣」在服务端是同一次表态，回来的 state 一样。
  // 差别只在他还想不想再被找——那句承诺得说出来，否则这个选项和拒绝没区别。
  const [remembered, setRemembered] = useState(false);

  const answered = seed.state !== "delivered";

  async function send(willing: boolean, text: string | null, remindMe: boolean) {
    setBusy(true);
    setFailed(false);
    try {
      const next = await respondToSeed(
        seed.intent_id,
        willing,
        text ?? undefined,
        remindMe,
      );
      setRemembered(remindMe);
      setSaying(false);
      onAnswered(next);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-label={seed.goal}
      className="rounded-[16px] border border-line bg-card p-5 shadow-[var(--shadow-card)]"
    >
      <h2 className="text-[16px] font-medium">{seed.goal}</h2>
      {/* 发起人只给名字。多给一样都会把这一屏变成"看人"，
          而他要判断的是这件事值不值得参与。 */}
      <p className="mt-0.5 text-[13px] text-ink-soft">{seed.from_name} 想找人一起</p>

      {seed.said && (
        <p className="mt-3 border-l-2 border-line pl-3 text-[15px] text-ink-soft">
          「{seed.said}」
        </p>
      )}

      <dl className="mt-4 divide-y divide-line-soft">
        <Row term="什么时候" value={readable(seed.when)} />
        <Row term="在哪" value={seed.where || "还没说在哪"} />
        <Row term="要几个人" value={headcount(seed.team_min, seed.team_max)} />
        <Row
          term="缺什么"
          value={seed.needs.length > 0 ? seed.needs.join("、") : "没说缺什么"}
        />
        {seed.offers.length > 0 && (
          <Row term="他能出的" value={seed.offers.join("、")} />
        )}
      </dl>

      <div className="mt-4">
        <h3 className="text-[13px] text-ink-soft">为什么找到你</h3>
        {seed.why.length > 0 ? (
          // 逐条列事实。折成一个数字既解释不了什么，又会被当成对人的判定。
          <ul className="mt-1.5 space-y-1.5">
            {seed.why.map((line) => (
              <li key={line} className="text-[15px]">
                {line}
              </li>
            ))}
          </ul>
        ) : (
          // 降级：排序和解释那一层不在时，卡片照样能答复。
          // 挡住答复的代价是他什么都做不了，而这件事本身没有任何变化。
          <p className="mt-1.5 text-[14px] text-ink-faint">
            现在说不出为什么找到你。这不影响你决定要不要参与。
          </p>
        )}
      </div>

      <div className="mt-5 border-t border-line pt-4">
        {answered ? (
          <Answered seed={seed} remembered={remembered} />
        ) : (
          <>
            {/* 这句话的位置就是它的全部意义：它必须在他按下去之前被看到。 */}
            <p className="text-[13px] text-pending">
              说了愿意不等于已经加入。他还要在说了愿意的人里挑，挑中了这件事才算定下来。
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <button
                type="button"
                disabled={busy}
                onClick={() => void send(true, null, false)}
                className="rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-paper disabled:opacity-35"
              >
                我愿意
              </button>
              {/* 和「我愿意」同一行、同样一步完成、不问为什么。
                  等重指的是代价相等，不是像素相等。 */}
              <button
                type="button"
                disabled={busy}
                onClick={() => void send(false, null, false)}
                className="rounded-[12px] border border-line px-4 py-2 text-[14px] disabled:opacity-35"
              >
                这次不感兴趣
              </button>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-4">
              <button
                type="button"
                disabled={busy}
                aria-expanded={saying}
                onClick={() => setSaying(!saying)}
                className="text-[14px] text-ink-soft underline underline-offset-4 hover:text-ink disabled:opacity-35"
              >
                想先说一句
              </button>
              {/* 第三个动作，**不是第三种表态**：这次不参与，外加把这件事缺的
                  那几样记进「我想参与的」，下次有人缺同样的东西时他会被找到。
                  和拒绝一样便宜，一步完成。 */}
              <button
                type="button"
                disabled={busy}
                onClick={() => void send(false, null, true)}
                className="text-[14px] text-ink-soft underline underline-offset-4 hover:text-ink disabled:opacity-35"
              >
                以后类似的叫我
              </button>
            </div>

            {saying && (
              <div className="mt-3">
                <label className="block">
                  <span className="text-[13px] text-ink-soft">想说的话</span>
                  <span className="ml-2 text-[12px] text-ink-faint">
                    可以不写。不写照样能说愿意
                  </span>
                  <textarea
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    rows={2}
                    maxLength={200}
                    aria-label="想说的话"
                    placeholder="比如：我剪过两支短片，周六下午都有空"
                    className="mt-1 w-full resize-none rounded-[8px] border border-line p-3 text-[15px] outline-none placeholder:text-ink-faint focus:border-accent"
                  />
                </label>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void send(true, note.trim() || null, false)}
                  className="mt-2 rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-paper disabled:opacity-35"
                >
                  就这么说，我愿意
                </button>
              </div>
            )}
          </>
        )}

        {failed && (
          // 不假装成功。他以为答过了而对方没收到，是这一屏最贵的一种错。
          <p role="alert" className="mt-3 text-[13px] text-clash">
            这一下没送出去，他那边没有收到。再点一次。
          </p>
        )}
      </div>
    </section>
  );
}

/** 答过之后这张卡说什么。**不再给按钮**——同一件事不该问他第二次。 */
function Answered({ seed, remembered }: { seed: Seed; remembered: boolean }) {
  if (seed.state === "chosen") {
    return (
      <div>
        <p className="text-[15px]">他挑中了你，这件事定下来了。</p>
        {/* 直接进那件事，不是丢到别处让他自己找——他刚被选中，
            最想去的是那件事本身，多一步会把那一下磨掉。 */}
        <a
          href={seed.space_id ? `/spaces/${seed.space_id}` : "/me"}
          className="mt-2 inline-flex min-h-[44px] items-center text-[15px] text-accent underline underline-offset-4"
        >
          去这件事的地方
        </a>
      </div>
    );
  }

  if (seed.state === "passed") {
    return (
      <p className="text-[15px]">
        {remembered
          ? "知道了，这次就到这里。以后有类似的事会再来找你。"
          : "知道了，这次就到这里。"}
      </p>
    );
  }

  return (
    <div>
      <p className="text-[15px]">你说了愿意。</p>
      {seed.my_note && (
        <p className="mt-1 text-[14px] text-ink-soft">你说的是：{seed.my_note}</p>
      )}
      {/* 不说"你排第几"，也不说"还有多少人也说了愿意"——那两样都只会让人退出。
          该说的是接下来会发生什么，以及不用一直等在这里。 */}
      <p className="mt-1 text-[13px] text-ink-soft">
        他会在说了愿意的人里挑，挑中了会告诉你。这段时间你可以照常做别的事。
      </p>
    </div>
  );
}

function Row({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex gap-4 py-2.5">
      <dt className="w-20 shrink-0 text-[13px] text-ink-faint">{term}</dt>
      <dd className="text-[15px]">{value}</dd>
    </div>
  );
}

/** 「还没说」也是一条信息：一件连时间都没定的事，值得他知道再决定。 */
function readable(iso: string | null | undefined): string {
  if (!iso) return "还没说什么时候";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const week = "日一二三四五六"[d.getDay()];
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日 周${week} ${d.getHours()}:${String(
    d.getMinutes(),
  ).padStart(2, "0")}`;
}

/** 人数算上发起人自己。不说清楚的话，三个人的局会被读成"他再找三个"。 */
function headcount(min: number | null | undefined, max: number | null | undefined): string {
  if (min && max) {
    return min === max ? `一共 ${min} 个人（算他自己）` : `一共 ${min}–${max} 个人（算他自己）`;
  }
  if (min) return `至少 ${min} 个人（算他自己）`;
  if (max) return `最多 ${max} 个人（算他自己）`;
  return "还没说要几个人";
}
