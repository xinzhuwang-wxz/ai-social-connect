"use client";

/**
 * 「这次留下了什么」：一件事做完之后的那一屏。
 *
 * 六条产品判断决定了这一屏长成现在这样：
 *
 * 1. **只记发生过什么，不记谁做得好不好。** 这一屏上没有一个位置能放对队友的
 *    评价，不是暂时没做，是它不该存在。一旦有了，它就变成一个打分系统，而
 *    打分系统会让人不敢参加自己不擅长的事——那正是这个产品要人做的事。
 * 2. **先出现的是留下来的东西，不是一个输入框。** 空着的输入框问的是
 *    "你想说点什么"，而这一屏该先回答"这次真的发生了什么"。
 * 3. **没点过头的不算数，而且要写在每一条上。** 只在分组标题上说一次，
 *    用户扫过去就漏了；漏了他就会以为系统已经在用那句话。
 * 4. **助手是增强，不是前提。** 那段回顾抽不出来时，留下的东西照样看得到、
 *    自己写一条照样能写。反过来做的话，一个起草服务挂掉就等于这件事没留下痕迹。
 * 5. **收回是主按钮，一步完成。** 收回一条记录应该像删一条朋友圈那么简单。
 *    如果行使权利需要仪式感，用户就不会行使——没人行使的权利等于不存在。
 * 6. **收回立刻生效在屏幕上。** 用户此刻要的正是"它真的不在被用了"这个确认，
 *    不是一句"已提交"。
 *
 * 界面文案不使用领域词汇（见 docs/07 语言映射表）。
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";

import {
  againFrom,
  askThemAgain,
  myMatchableIntents,
  CONFIRMED,
  DRAFT,
  REVOKED,
  confirmedHere,
  echoFor,
  fromDraft,
  fromMine,
  leaveOneThing,
  writeOwn,
  type Echo,
  type EchoRecord,
  type Evidence,
  type Again,
  type Intent,
} from "@/lib/invitations";
import { confirmRecord, myRecords, revokeRecord } from "@/lib/me";

/**
 * 能留下哪几样东西。
 *
 * 后端发的是 `artifact` 这类标识符，它们不能出现在屏幕上。翻不出来的那一类
 * 不显示英文原文——宁可少一项，不能露一个字段名。
 */
const KINDS = [
  { key: "photo", label: "返图", link: true },
  { key: "note", label: "一段记录", link: false },
  { key: "artifact", label: "做出来的东西", link: false },
  { key: "link", label: "一个链接", link: true },
] as const;

const KIND_WORDS: Record<string, string> = Object.fromEntries(
  KINDS.map((kind) => [kind.key, kind.label]),
);

/**
 * 照这件事再来一次。
 *
 * PRD 的最后一段：第一次行动完成后产品进入下一轮 Loop。在它之前，
 * 森林里的一株点进去**只能看**。
 *
 * 它带用户回到首屏，把上次的目标预填进去——**但不替他保存**：
 * 抽取只产出草稿这条规矩在这里同样成立，尤其是时间和地点，
 * 它们必然是新的。
 */
function AgainCard({ eventId }: { eventId: string }) {
  const [again, setAgain] = useState<Again | null>(null);
  // null = 还在取数，[] = 取出来没有可用需求或取数失败
  const [intents, setIntents] = useState<Intent[] | null>(null);

  useEffect(() => {
    againFrom(eventId).then(setAgain, () => setAgain(null));
    // 取不出来就当空，不影响这一屏其余部分
    myMatchableIntents().then(
      (all) => setIntents(all.filter((i) => i.is_matchable)),
      () => setIntents([]),
    );
  }, [eventId]);

  if (!again) return null;

  const who = (again.last_time_with ?? []).map((m) => m.display_name).join("、");
  const members = again.last_time_with ?? [];

  return (
    <section
      aria-label="再来一次"
      className="mb-8 rounded-[16px] border border-line bg-card p-5 shadow-[var(--shadow-card)]"
    >
      <h2 className="text-[16px] font-medium">还想再来一次吗</h2>
      <p className="mt-1 text-[14px] text-ink-soft">
        {who ? `上次是和${who}一起做的。` : ""}
        照这件事再发一条，时间地点你自己重填——那两样必然是新的。
      </p>
      <a
        href={`/?again=${encodeURIComponent(again.goal)}`}
        className="mt-4 inline-block rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-paper"
      >
        照这个再来一次
      </a>
      {/* 只有上次有同伴才有人可以问 */}
      {members.length > 0 && (
        <InviteSection eventId={eventId} members={members} intents={intents} />
      )}
    </section>
  );
}

/**
 * 把新需求问上次那几个人。
 *
 * 「问」不是「拉进来」——每个人收到的是一条待答复，要各自来决定（不变量 3）。
 * intents 为 null 时还在取数，为 [] 时没有可用需求，两种情况都不显示这一块。
 */
function InviteSection({
  eventId,
  members,
  intents,
}: {
  eventId: string;
  members: Array<{ principal_id: string; display_name: string }>;
  intents: Intent[] | null;
}) {
  const [intentId, setIntentId] = useState("");
  const [busy, setBusy] = useState(false);
  // 问过了就不再显示表单——防止重复轰炸同一批人
  const [asked, setAsked] = useState(false);
  const [failed, setFailed] = useState(false);

  if (!intents || intents.length === 0) return null;

  if (asked) {
    return (
      <div className="mt-4 rounded-[10px] border border-line p-4">
        <p className="text-[14px]">问过了，等他们各自答复。</p>
        <p className="mt-1 text-[13px] text-ink-soft">
          这不是把他们拉进来——每个人收到的是一条待答复，要他们自己来决定。
        </p>
      </div>
    );
  }

  async function ask() {
    setBusy(true);
    setFailed(false);
    try {
      await askThemAgain(
        eventId,
        intentId,
        members.map((m) => m.principal_id),
      );
      setAsked(true);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-4">
      <p className="text-[13px] text-ink-soft">
        发了新需求之后，也可以直接问他们要不要：
      </p>
      <div className="mt-2 flex flex-wrap items-end gap-2">
        <select
          value={intentId}
          onChange={(e) => setIntentId(e.target.value)}
          aria-label="选一条需求"
          className="min-w-0 flex-1 rounded-[8px] border border-line bg-card p-2.5 text-[14px] outline-none focus:border-accent"
        >
          <option value="">选一条需求</option>
          {intents.map((intent) => (
            <option key={intent.id} value={intent.id}>
              {intent.content.goal}
            </option>
          ))}
        </select>
        <button
          type="button"
          disabled={busy || !intentId}
          onClick={() => void ask()}
          className="min-h-[44px] rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-paper disabled:opacity-35"
        >
          问他们
        </button>
      </div>
      {failed && (
        <p role="alert" className="mt-2 text-[13px] text-clash">
          没发出去，他们还没收到。再试一次？
        </p>
      )}
    </div>
  );
}

export function EchoScreen({ eventId }: { eventId: string }) {
  const [echo, setEcho] = useState<Echo | null>(null);
  const [records, setRecords] = useState<EchoRecord[]>([]);
  // 降级：调不出"我点过头的那几条"时，这一屏其余部分照常。
  const [mineDown, setMineDown] = useState(false);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setFailed(false);
    setEcho(null);
    // 两次独立取数：这一次留下的东西，和我在这件事上点过头的那几条。
    // 合成一次的话，一处失败就是整屏失败。
    const [one, two] = await Promise.allSettled([echoFor(eventId), myRecords()]);
    if (one.status !== "fulfilled") {
      setFailed(true);
      return;
    }
    setEcho(one.value);
    setMineDown(two.status !== "fulfilled");
    const drafts = (one.value.to_confirm ?? []).map(fromDraft);
    const mine =
      two.status === "fulfilled"
        ? confirmedHere([...two.value.confirmed, ...two.value.revoked], eventId)
        : [];
    setRecords([...drafts, ...mine]);
  }, [eventId]);

  useEffect(() => {
    void load();
  }, [load]);

  /** 一条被改掉之后就地换掉它。它自己的处境决定它出现在哪一堆里。 */
  const replace = useCallback((updated: EchoRecord) => {
    setRecords((all) => all.map((one) => (one.id === updated.id ? updated : one)));
  }, []);

  if (failed) {
    return (
      <Shell title="这次留下了什么">
        <section role="alert" className="rounded-[16px] border border-line bg-card p-5">
          <p className="text-[15px]">现在调不出这次留下的东西。</p>
          <p className="mt-1 text-[13px] text-ink-soft">
            没连上的时候什么都不会被改动，留下的东西一样都不会少。
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

  if (echo === null) {
    return (
      <Shell title="这次留下了什么">
        <div className="space-y-3" aria-label="加载中">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-[16px] bg-line" />
          ))}
        </div>
      </Shell>
    );
  }

  const drafts = records.filter((one) => one.state === DRAFT);
  const kept = records.filter((one) => one.state === CONFIRMED);
  const gone = records.filter((one) => one.state === REVOKED);
  const empty = echo.evidence.length === 0 && records.length === 0 && !echo.recap;

  // 空态：什么都还没有。这时候该说的是一句有用的话加一个能用的入口，
  // 不是一句"暂无内容"。
  if (empty) {
    return (
      <Shell title="这次留下了什么" lead={echo.event_title}>
        {/* **空态这一屏也要有它。** 它原先只挂在"已经留下过东西"那条分支上，
            而刚做完、还什么都没传的人恰恰是最可能想再来一次的那个——
            于是那扇门在唯一需要它的时刻不存在。 */}
        <AgainCard eventId={eventId} />

        <section className="rounded-[16px] border border-line bg-card p-6">
          <p className="text-[16px]">这次还没留下任何东西。</p>
          <p className="mt-2 text-[14px] text-ink-soft">
            留下点什么——返图、一段记录、做出来的东西。以后你自己也会想看，
            下次找人的时候它也说得出你做过什么。
          </p>
        </section>
        <LeaveSomething
          eventId={eventId}
          onLeft={(item) =>
            setEcho((now) => (now ? { ...now, evidence: [...now.evidence, item] } : now))
          }
        />
        <WriteOne
          eventId={eventId}
          onWritten={(one) => setRecords((all) => [one, ...all])}
        />
      </Shell>
    );
  }

  return (
    <Shell title="这次留下了什么" lead={echo.event_title}>
      {/* 闭环的最后一步：一株结出下一颗种子（PRD 持续互动那一段）。
          放在最上面——一个刚看完这次留下什么的人，正是最可能想再来一次的时候。 */}
      <AgainCard eventId={eventId} />

      <section aria-label="留下的东西">
        <h2 className="text-[16px] font-medium">留下的东西</h2>
        {echo.evidence.length === 0 ? (
          <p className="mt-1.5 text-[14px] text-ink-soft">
            这次还没有人留下东西。留下点什么，以后你自己也会想看。
          </p>
        ) : (
          <ul className="mt-3 space-y-3">
            {echo.evidence.map((item) => (
              <li key={item.id}>
                <article
                  aria-label={item.title}
                  className="rounded-[16px] border border-line bg-card p-5"
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <h3 className="text-[15px] font-medium">{item.title}</h3>
                    {KIND_WORDS[item.kind] && (
                      <span className="shrink-0 text-[11px] text-ink-faint">
                        {KIND_WORDS[item.kind]}
                      </span>
                    )}
                  </div>
                  {item.body && (
                    <p className="mt-1 text-[14px] text-ink-soft">{item.body}</p>
                  )}
                  {item.uri && (
                    <a
                      href={item.uri}
                      className="mt-1 inline-block text-[13px] text-accent underline underline-offset-4"
                    >
                      打开看看
                    </a>
                  )}
                </article>
              </li>
            ))}
          </ul>
        )}
      </section>

      <LeaveSomething
        eventId={eventId}
        onLeft={(item) =>
          setEcho((now) => (now ? { ...now, evidence: [...now.evidence, item] } : now))
        }
      />

      {echo.evidence.length > 0 && <Recap echo={echo} />}

      <section aria-label="等你点头" className="mt-8">
        <h2 className="text-[16px] font-medium">等你点头</h2>
        <p className="mt-0.5 text-[13px] text-ink-soft">
          这几条还不算数。没点过头的，任何人都看不到，也不会出现在给别人看的说明里。
        </p>
        {drafts.length === 0 ? (
          <p className="mt-3 text-[14px] text-ink-faint">没有等你点头的。</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {drafts.map((one) => (
              <li key={one.id}>
                <RecordCard record={one} onChanged={replace} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <WriteOne
        eventId={eventId}
        onWritten={(one) => setRecords((all) => [one, ...all])}
      />

      <section aria-label="已经在用的" className="mt-8">
        <h2 className="text-[16px] font-medium">已经在用的</h2>
        <p className="mt-0.5 text-[13px] text-ink-soft">
          你点过头，所以它们可能出现在别人看到的说明里。随时收得回。
        </p>
        {mineDown ? (
          <p className="mt-3 text-[14px] text-ink-soft">
            现在调不出你点过头的那几条。这一屏其余的照常能用，什么都没有被改动。
          </p>
        ) : kept.length === 0 ? (
          <p className="mt-3 text-[14px] text-ink-faint">还没有你点过头的。</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {kept.map((one) => (
              <li key={one.id}>
                <RecordCard record={one} onChanged={replace} />
              </li>
            ))}
          </ul>
        )}
      </section>

      {gone.length > 0 && (
        <section aria-label="你收回过的" className="mt-8">
          <h2 className="text-[16px] font-medium">你收回过的</h2>
          <p className="mt-0.5 text-[13px] text-ink-soft">
            留在这里只是让你知道曾经有过这句话，它不会再被用到。
          </p>
          <ul className="mt-3 space-y-3">
            {gone.map((one) => (
              <li key={one.id}>
                <RecordCard record={one} onChanged={replace} />
              </li>
            ))}
          </ul>
        </section>
      )}
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
 * 那段回顾。
 *
 * 它是留下来的东西的一次转写，所以能点开看它依据了哪些事实——看不到依据的
 * 一段话，用户既无从相信也无从反驳。抽不出来的时候这一段自己说清楚，
 * 而不是留一片空白让人以为这次什么都没发生。
 */
function Recap({ echo }: { echo: Echo }) {
  const [open, setOpen] = useState(false);
  return (
    <section aria-label="这次一起做成了什么" className="mt-8">
      <h2 className="text-[16px] font-medium">这次一起做成了什么</h2>
      {echo.recap ? (
        <div className="mt-3 rounded-[16px] border border-line bg-card p-5">
          <p className="text-[15px]">{echo.recap.text}</p>
          <button
            type="button"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            className="mt-2 text-[13px] text-ink-soft underline underline-offset-4 hover:text-ink"
          >
            这段是照着什么写的
          </button>
          {open && (
            <ul className="mt-1.5 space-y-1">
              {echo.recap.grounded_in.length === 0 ? (
                <li className="text-[13px] text-ink-faint">这段说不出照着什么写的。</li>
              ) : (
                echo.recap.grounded_in.map((line) => (
                  <li key={line} className="text-[13px] text-ink-faint">
                    · {line}
                  </li>
                ))
              )}
            </ul>
          )}
        </div>
      ) : (
        <p className="mt-3 text-[14px] text-ink-soft">
          这一段现在写不出来。上面那些是真发生过的，照样看得到；你也照样能自己写一条。
        </p>
      )}
    </section>
  );
}

/** 留下一件东西。**这里没有一个字段能放对人的评价。** */
function LeaveSomething({
  eventId,
  onLeft,
}: {
  eventId: string;
  onLeft: (item: Evidence) => void;
}) {
  const [kind, setKind] = useState<string>("photo");
  const [title, setTitle] = useState("");
  const [extra, setExtra] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const wantsLink = KINDS.find((one) => one.key === kind)?.link ?? false;
  const extraLabel = wantsLink ? "链接" : "多写几句";

  async function leave() {
    setBusy(true);
    setFailed(false);
    try {
      const item = await leaveOneThing(eventId, {
        kind,
        title: title.trim(),
        body: wantsLink ? null : extra.trim() || null,
        uri: wantsLink ? extra.trim() || null : null,
      });
      onLeft(item);
      setTitle("");
      setExtra("");
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-label="留下一件东西"
      className="mt-6 rounded-[16px] border border-line bg-card p-5"
    >
      <h2 className="text-[16px] font-medium">留下一件东西</h2>
      <p className="mt-0.5 text-[13px] text-ink-soft">
        只记发生过什么，不记谁做得好不好。
      </p>

      <div role="radiogroup" aria-label="这是什么" className="mt-3 flex flex-wrap gap-2">
        {KINDS.map((one) => (
          <button
            key={one.key}
            type="button"
            role="radio"
            aria-checked={kind === one.key}
            onClick={() => {
              setKind(one.key);
              setExtra("");
            }}
            className={`rounded-[12px] border px-3 py-1.5 text-[14px] ${
              kind === one.key ? "border-accent bg-accent-soft text-accent" : "border-line"
            }`}
          >
            {one.label}
          </button>
        ))}
      </div>

      <label className="mt-3 block">
        <span className="text-[13px] text-ink-soft">一句话说清这是什么</span>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          aria-label="一句话说清这是什么"
          placeholder="比如：成片 檐下.mp4"
          className="mt-1 w-full rounded-[8px] border border-line p-3 text-[15px] outline-none placeholder:text-ink-faint focus:border-accent"
        />
      </label>

      <label className="mt-3 block">
        <span className="text-[13px] text-ink-soft">{extraLabel}</span>
        <textarea
          value={extra}
          onChange={(e) => setExtra(e.target.value)}
          rows={2}
          aria-label={extraLabel}
          className="mt-1 w-full resize-none rounded-[8px] border border-line p-3 text-[15px] outline-none focus:border-accent"
        />
      </label>

      <button
        type="button"
        disabled={busy || !title.trim()}
        onClick={() => void leave()}
        className="mt-3 rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-paper disabled:opacity-35"
      >
        留下
      </button>

      {failed && (
        <p role="alert" className="mt-3 text-[13px] text-clash">
          这一下没发出去，这件东西还没留下。再点一次试试。
        </p>
      )}
    </section>
  );
}

/** 自己写一条。写完它也要再点一次头——通往「算数」的路只有一条。 */
function WriteOne({
  eventId,
  onWritten,
}: {
  eventId: string;
  onWritten: (record: EchoRecord) => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function write() {
    setBusy(true);
    setFailed(false);
    try {
      onWritten(fromDraft(await writeOwn(eventId, text.trim())));
      setText("");
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-label="自己写一条"
      className="mt-6 rounded-[16px] border border-line bg-card p-5"
    >
      <h2 className="text-[16px] font-medium">自己写一条</h2>
      <p className="mt-0.5 text-[13px] text-ink-soft">
        写完它也在「等你点头」那一堆里，点过才算数。
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={2}
        aria-label="你想记下什么？"
        placeholder="比如：我负责了这次的剪辑和调色"
        className="mt-3 w-full resize-none rounded-[8px] border border-line p-3 text-[15px] outline-none placeholder:text-ink-faint focus:border-accent"
      />
      <button
        type="button"
        disabled={busy || !text.trim()}
        onClick={() => void write()}
        className="mt-2 rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-paper disabled:opacity-35"
      >
        记下来
      </button>

      {failed && (
        <p role="alert" className="mt-3 text-[13px] text-clash">
          这一下没发出去，这句话还没记下。再点一次试试。
        </p>
      )}
    </section>
  );
}

function RecordCard({
  record,
  onChanged,
}: {
  record: EchoRecord;
  onChanged: (record: EchoRecord) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function run(act: (id: string) => Promise<Parameters<typeof fromMine>[0]>) {
    setBusy(true);
    setFailed(false);
    try {
      onChanged(fromMine(await act(record.id)));
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  const guess = record.drafted_by_agent && record.state === DRAFT;
  return (
    <article
      aria-label={record.text}
      className={`rounded-[16px] border p-5 ${
        guess ? "border-dashed border-draft bg-draft-soft" : "border-line bg-card"
      }`}
    >
      {record.state === DRAFT && (
        <p className="text-[11px] text-pending">还不算数</p>
      )}
      {record.state === DRAFT && record.hint && (
        <p className="text-[11px] text-draft">{record.hint}</p>
      )}
      <p className="mt-1 text-[15px]">{record.text}</p>
      <p className="mt-2 text-[13px] text-ink-faint">{basedOn(record)}</p>

      {record.state === CONFIRMED && (
        <p className="mt-1 text-[13px] text-ink-soft">
          {record.in_use > 0
            ? `现在有 ${record.in_use} 处正在用这句话`
            : "现在没有地方在用这句话"}
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        {record.state === DRAFT && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void run(confirmRecord)}
            className="rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-paper disabled:opacity-35"
          >
            对，是这样
          </button>
        )}
        {record.state !== REVOKED && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void run(revokeRecord)}
            className="rounded-[12px] border border-line px-4 py-2 text-[14px] disabled:opacity-35"
          >
            {record.state === DRAFT ? "删掉" : "收回"}
          </button>
        )}
        {record.state === REVOKED && (
          <p className="text-[14px] text-ink-soft">你收回了这句话，它不会再被用到。</p>
        )}
      </div>

      {failed && (
        <p role="alert" className="mt-3 text-[13px] text-clash">
          这一下没发出去，这句话还是原样。再点一次试试。
        </p>
      )}
    </article>
  );
}

/**
 * 这条是照着什么写的。
 *
 * 说不出来源的记录，本人无从判断该不该留着它——所以这一行永远在，
 * 哪怕它说的是"说不出来"。
 */
function basedOn(record: EchoRecord): string {
  if (record.based_on.length === 0) {
    return "这条说不出是照着什么写的。拿不准就删掉它";
  }
  return `照着这些写的：${record.based_on.join("、")}`;
}
