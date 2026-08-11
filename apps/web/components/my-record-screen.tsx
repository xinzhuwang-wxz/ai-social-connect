"use client";

/**
 * 三个自我管理面：我参加过的 / 关于我的记录 / 谁能看到我。
 *
 * 五条产品判断决定了这一屏长成现在这样：
 *
 * 1. **这是控制台，不是展示位。** 三块内容全是给自己看、给自己操作的。
 *    做成一个可供他人浏览的主页，产品就退回「看人卡决定要不要连接」，
 *    而那样冷启动的人天然吃亏——他没有卡可给。
 * 2. **一次只看一块。** 三块摞在一屏上，用户三块都不会认真看。
 *    每屏一个决定，所以它们是三个页签而不是三个区块。
 * 3. **什么都没有时不是三个空列表。** 刚注册的人打开看到三个空框，
 *    只会关掉。那时候该说的是一句有用的话加一个能点的入口。
 * 4. **收回是主按钮，一步完成。** 收回一条记录应该像删一条朋友圈那么简单。
 *    如果行使权利需要仪式感，用户就不会行使——而一个没人行使的权利
 *    等于不存在。
 * 5. **系统猜的和自己点过头的一眼可辨。** 猜的那条有独立的视觉通道，
 *    而且永远排在「等你点头」那一堆里，不会混进「已经在用的」。
 *
 * 界面文案不使用领域词汇（见 docs/07 语言映射表）。
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";

import {
  ABANDONED,
  COMPLETED,
  confirmRecord,
  myEvents,
  myRecords,
  myVisibility,
  nothingYet,
  revokeRecord,
  stopShowing,
  type MyEvent,
  type MyRecord,
  type MyRecords,
  type Visibility,
} from "@/lib/me";

import { countdown, whenPhrase } from "./waiting-screen";

/**
 * 每一项在界面上叫什么。
 *
 * 后端发的是 `location_scope` 这类标识符，它们不能出现在屏幕上。翻不出来的
 * 不显示英文原文——宁可少说一项，不能露一个字段名。
 */
const ITEM_WORDS: Record<string, string> = {
  goal: "要做什么",
  offers: "我能出",
  needs: "我缺",
  time_window: "什么时候",
  location_scope: "在哪",
  team_size: "几个人",
  boundaries: "我的底线",
  open_questions: "还没定的事",
  portfolio_link: "作品链接",
  self_intro: "我写的那段介绍",
  major: "我的专业",
  confirmed_events: "我做完过的事",
};

type Tab = "events" | "records" | "shown";

export function MyRecordScreen() {
  const [events, setEvents] = useState<MyEvent[] | null>(null);
  const [records, setRecords] = useState<MyRecords | null>(null);
  const [shown, setShown] = useState<Visibility[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>("events");

  const load = useCallback(async () => {
    setLoading(true);
    // 三次独立取数：其中一块挂了，另外两块照常能用。
    // 合成一个接口的话，一处失败就是整屏失败。
    const [e, r, v] = await Promise.allSettled([
      myEvents(),
      myRecords(),
      myVisibility(),
    ]);
    setEvents(e.status === "fulfilled" ? e.value : null);
    setRecords(r.status === "fulfilled" ? r.value : null);
    setShown(v.status === "fulfilled" ? v.value : null);
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /**
   * 收回一条之后，界面**立刻**照服务端同一条判断重算一遍：收回过的话
   * 不再能被引用，所以它从「现在带出去的话」里当场消失。
   *
   * 不等下一次取数才更新，是因为用户此刻要的正是"它真的没了"这个确认；
   * 但仍然在后台对一次，服务端才是权威——对不上就以服务端为准。
   */
  const forget = useCallback((gone: MyRecord) => {
    setShown((rows) =>
      rows === null
        ? rows
        : rows.map((row) => ({
            ...row,
            shows_records: row.shows_records.filter((t) => t !== gone.text),
          })),
    );
    myVisibility().then(setShown, () => {});
  }, []);

  if (loading) {
    return (
      <Shell>
        <div className="space-y-3" aria-label="加载中">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-[16px] bg-line" />
          ))}
        </div>
      </Shell>
    );
  }

  // 三块全都调不出来才算这一屏坏了。只坏一块的时候，那一块自己说明情况。
  if (events === null && records === null && shown === null) {
    return (
      <Shell>
        <section role="alert" className="rounded-[16px] border border-line bg-card p-5">
          <p className="text-[15px]">现在调不出你这边的东西。</p>
          <p className="mt-1 text-[13px] text-ink-soft">
            没连上的时候什么都不会被改动，你回来再看也不迟。
          </p>
          <button
            type="button"
            onClick={() => void load()}
            className="mt-4 rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white"
          >
            再试一次
          </button>
        </section>
      </Shell>
    );
  }

  // 什么都还没有：一句有用的话加一个能点的入口，不是三个空列表。
  if (nothingYet(events, records, shown)) {
    return (
      <Shell>
        <section className="rounded-[16px] border border-line bg-card p-6">
          <p className="text-[16px]">你还没参加过什么，先说说想做点什么。</p>
          <p className="mt-2 text-[14px] text-ink-soft">
            做完一件事之后，这里会有你做过的事、系统记下的几句话、
            以及你给出去过什么。每一样都收得回。
          </p>
          <a
            href="/"
            className="mt-5 inline-block rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white"
          >
            说说想做点什么
          </a>
        </section>
      </Shell>
    );
  }

  const waiting = records?.to_confirm.length ?? 0;

  return (
    <Shell>
      <div role="tablist" aria-label="这一页的三块" className="mb-6 flex flex-wrap gap-2">
        <Tab id="events" now={tab} onPick={setTab} label="我参加过的" />
        <Tab
          id="records"
          now={tab}
          onPick={setTab}
          label="关于我的记录"
          // 有几条等着你点头，是这一页唯一需要被催的事——不催，
          // 系统猜的那些就会一直躺在那里，谁都不知道该不该用。
          badge={waiting > 0 ? `${waiting} 条等你` : undefined}
        />
        <Tab id="shown" now={tab} onPick={setTab} label="谁能看到我" />
      </div>

      {tab === "events" && (
        <Panel id="events">
          <Events events={events} onRetry={() => void load()} />
        </Panel>
      )}
      {tab === "records" && (
        <Panel id="records">
          <Records
            records={records}
            onChanged={setRecords}
            onForgotten={forget}
            onRetry={() => void load()}
          />
        </Panel>
      )}
      {tab === "shown" && (
        <Panel id="shown">
          <Shown shown={shown} onChanged={setShown} onRetry={() => void load()} />
        </Panel>
      )}
    </Shell>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <main className="mx-auto w-full max-w-2xl px-5 py-10 sm:py-16">
      <header className="mb-8">
        <h1 className="text-[20px] font-semibold tracking-tight">只有你看得到</h1>
        <p className="mt-1 text-[13px] text-ink-soft">
          这一页不给别人看。别人只看到你为某一次事情亲手同意给出去的那一小块。
        </p>
      </header>
      {children}
    </main>
  );
}

function Tab({
  id,
  now,
  onPick,
  label,
  badge,
}: {
  id: Tab;
  now: Tab;
  onPick: (t: Tab) => void;
  label: string;
  badge?: string;
}) {
  const on = now === id;
  return (
    <button
      type="button"
      role="tab"
      id={`tab-${id}`}
      aria-selected={on}
      aria-controls={`panel-${id}`}
      onClick={() => onPick(id)}
      className={`rounded-[12px] border px-3 py-1.5 text-[14px] ${
        on ? "border-accent bg-accent-soft text-accent" : "border-line"
      }`}
    >
      {label}
      {badge && <span className="ml-1.5 text-[11px] text-pending">{badge}</span>}
    </button>
  );
}

function Panel({ id, children }: { id: Tab; children: ReactNode }) {
  return (
    <section role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`}>
      {children}
    </section>
  );
}

/** 某一块单独调不出来时说什么。其余两块照常。 */
function Down({ what, onRetry }: { what: string; onRetry: () => void }) {
  return (
    <div className="rounded-[16px] border border-line bg-card p-5">
      <p className="text-[15px]">现在调不出{what}。</p>
      <p className="mt-1 text-[13px] text-ink-soft">
        这一页其余的照常能用，什么都没有被改动。
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 rounded-[12px] border border-line px-4 py-2 text-[14px]"
      >
        再试一次
      </button>
    </div>
  );
}

function Empty({ text, cta }: { text: string; cta?: { href: string; label: string } }) {
  return (
    <div className="rounded-[16px] border border-line bg-card p-5">
      <p className="text-[15px]">{text}</p>
      {cta && (
        <a
          href={cta.href}
          className="mt-4 inline-block rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white"
        >
          {cta.label}
        </a>
      )}
    </div>
  );
}

// --- 我参加过的 -------------------------------------------------------------

function Events({
  events,
  onRetry,
}: {
  events: MyEvent[] | null;
  onRetry: () => void;
}) {
  if (events === null) return <Down what="你参加过的" onRetry={onRetry} />;
  if (events.length === 0) {
    return (
      <Empty
        text="你还没参加过什么，先说说想做点什么。"
        cta={{ href: "/", label: "说说想做点什么" }}
      />
    );
  }
  return (
    <ul className="space-y-3">
      {events.map((event) => (
        <li key={event.event_id}>
          <EventCard event={event} />
        </li>
      ))}
    </ul>
  );
}

function EventCard({ event }: { event: MyEvent }) {
  const now = new Date();
  return (
    <article
      aria-label={event.title}
      className="rounded-[16px] border border-line bg-card p-5"
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-[16px] font-medium">{event.title}</h2>
        <span className="shrink-0 text-[11px] text-ink-faint">
          {whenPhrase(event.formed_at, now)}开始
        </span>
      </div>
      <p className="mt-1 text-[14px] text-ink-soft">{event.goal}</p>
      {event.with_others.length > 0 && (
        <p className="mt-2 text-[13px] text-ink-soft">
          和{event.with_others.join("、")}一起
        </p>
      )}
      <p className="mt-3 text-[13px]">
        {/* 取消的事照样在这里——它是你真实的经历。但它不算做成的。
            两句话分开说，是因为把它藏起来和把它算成功劳一样都是假话。 */}
        {event.counts_as_done ? (
          <span className="text-settled">这件事做成了</span>
        ) : event.left_at ? (
          <span className="text-ink-soft">你中途退出了，这次不算你做成的</span>
        ) : event.state === ABANDONED ? (
          <span className="text-ink-soft">这件事后来取消了，不算做成的</span>
        ) : event.state === COMPLETED ? (
          <span className="text-ink-soft">这件事已经结束</span>
        ) : (
          <span className="text-pending">还在做</span>
        )}
      </p>
    </article>
  );
}

// --- 关于我的记录 -----------------------------------------------------------

function Records({
  records,
  onChanged,
  onForgotten,
  onRetry,
}: {
  records: MyRecords | null;
  onChanged: (r: MyRecords) => void;
  onForgotten: (gone: MyRecord) => void;
  onRetry: () => void;
}) {
  if (records === null) return <Down what="系统记下的那些话" onRetry={onRetry} />;

  const empty =
    records.to_confirm.length === 0 &&
    records.confirmed.length === 0 &&
    records.revoked.length === 0;
  if (empty) {
    return (
      <Empty
        text="系统还没记下关于你的任何一句话。做完一件事之后，这里会有几句，逐条由你决定留不留。"
        cta={{ href: "/", label: "说说想做点什么" }}
      />
    );
  }

  /** 一条被改掉之后，把它挪到该去的那一堆。三堆分开是这一面的全部要点。 */
  function replace(updated: MyRecord) {
    const drop = (list: MyRecord[]) => list.filter((r) => r.id !== updated.id);
    const next: MyRecords = {
      to_confirm: drop(records!.to_confirm),
      confirmed: drop(records!.confirmed),
      revoked: drop(records!.revoked),
    };
    if (updated.state === "revoked") next.revoked = [updated, ...next.revoked];
    else if (updated.state === "confirmed") next.confirmed = [updated, ...next.confirmed];
    else next.to_confirm = [updated, ...next.to_confirm];
    onChanged(next);
    if (updated.state === "revoked") onForgotten(updated);
  }

  return (
    <div className="space-y-8">
      <Group
        title="等你点头"
        note="没点过头的这几条，任何人都看不到。"
        list={records.to_confirm}
        empty="没有等你点头的。"
        onChanged={replace}
      />
      <Group
        title="已经在用的"
        note="你点过头，所以它们可能出现在别人看到的说明里。随时收得回。"
        list={records.confirmed}
        empty="还没有你点过头的。"
        onChanged={replace}
      />
      {records.revoked.length > 0 && (
        <Group
          title="你收回过的"
          note="留在这里只是让你知道曾经有过这句话，它不会再被用到。"
          list={records.revoked}
          onChanged={replace}
        />
      )}
    </div>
  );
}

function Group({
  title,
  note,
  list,
  empty,
  onChanged,
}: {
  title: string;
  note: string;
  list: MyRecord[];
  empty?: string;
  onChanged: (r: MyRecord) => void;
}) {
  return (
    <section aria-label={title}>
      <h2 className="text-[16px] font-medium">{title}</h2>
      <p className="mt-0.5 text-[13px] text-ink-soft">{note}</p>
      {list.length === 0 ? (
        empty && <p className="mt-3 text-[14px] text-ink-faint">{empty}</p>
      ) : (
        <ul className="mt-3 space-y-3">
          {list.map((record) => (
            <li key={record.id}>
              <RecordCard record={record} onChanged={onChanged} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RecordCard({
  record,
  onChanged,
}: {
  record: MyRecord;
  onChanged: (r: MyRecord) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function run(act: (id: string) => Promise<MyRecord>) {
    setBusy(true);
    setFailed(false);
    try {
      onChanged(await act(record.id));
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  const guess = record.drafted_by_agent && record.state === "draft";
  return (
    <article
      aria-label={record.text}
      className={`rounded-[16px] border p-5 ${
        guess ? "border-dashed border-draft bg-draft-soft" : "border-line bg-card"
      }`}
    >
      {record.drafted_by_agent && (
        <p className="text-[11px] text-draft">这是我猜的，你看对不对</p>
      )}
      <p className="mt-1 text-[15px]">{record.text}</p>
      <p className="mt-2 text-[13px] text-ink-faint">{sourceLine(record)}</p>

      {record.state === "confirmed" && (
        <p className="mt-1 text-[13px] text-ink-soft">
          {record.in_use > 0
            ? `现在有 ${record.in_use} 处正在用这句话`
            : "现在没有地方在用这句话"}
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        {record.state === "draft" && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void run(confirmRecord)}
            className="rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white disabled:opacity-35"
          >
            对，是这样
          </button>
        )}
        {/* 收回是主按钮，不是二级菜单里的一项，也不再确认一次。 */}
        {record.state !== "revoked" && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void run(revokeRecord)}
            className="rounded-[12px] border border-line px-4 py-2 text-[14px] disabled:opacity-35"
          >
            {record.state === "draft" ? "删掉" : "收回"}
          </button>
        )}
        {record.state === "revoked" && (
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
 * 这条是从哪来的。
 *
 * 说不出来源的记录，本人无从判断该不该留着它——所以这一行永远在，
 * 哪怕它说的是"说不出来"。
 */
function sourceLine(record: MyRecord): string {
  const from = record.event_title ? `来自「${record.event_title}」` : "";
  const items = record.sources.map((s) => s.title).join("、");
  if (from && items) return `${from}，依据：${items}`;
  if (from) return `${from}。这条没留下可查的东西`;
  if (items) return `依据：${items}`;
  return "这条说不出是从哪来的。拿不准就删掉它";
}

// --- 谁能看到我 -------------------------------------------------------------

function Shown({
  shown,
  onChanged,
  onRetry,
}: {
  shown: Visibility[] | null;
  onChanged: (v: Visibility[]) => void;
  onRetry: () => void;
}) {
  if (shown === null) return <Down what="你给出去过什么" onRetry={onRetry} />;
  if (shown.length === 0) {
    return <Empty text="现在没有人能看到你的任何东西。你给出去的每一次都有期限，到了就自己失效。" />;
  }
  return (
    <ul className="space-y-3">
      {shown.map((row) => (
        <li key={row.envelope_id}>
          <ShownCard
            row={row}
            onGone={() => onChanged(shown.filter((r) => r.envelope_id !== row.envelope_id))}
          />
        </li>
      ))}
    </ul>
  );
}

function ShownCard({ row, onGone }: { row: Visibility; onGone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const seen = row.shows.filter((s) => s.seen_by_others).map((s) => ITEM_WORDS[s.field_name]);
  const hidden = row.shows.filter((s) => !s.seen_by_others).map((s) => ITEM_WORDS[s.field_name]);
  const words = (list: (string | undefined)[]) => list.filter(Boolean).join("、");

  async function takeBack() {
    setBusy(true);
    setFailed(false);
    try {
      await stopShowing(row.envelope_id);
      onGone();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article
      aria-label={row.for_what || "这一次"}
      className="rounded-[16px] border border-line bg-card p-5"
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-[16px] font-medium">{row.for_what || "这一次"}</h2>
        <span className="shrink-0 text-[11px] text-ink-faint">
          {countdown(row.expires_at, new Date())}自己失效
        </span>
      </div>

      {seen.length > 0 && (
        <p className="mt-2 text-[14px]">他们看得到：{words(seen)}</p>
      )}
      {hidden.length > 0 && (
        <p className="mt-1 text-[14px] text-ink-soft">
          只拿来配队、他们看不到：{words(hidden)}
        </p>
      )}
      {row.shows_records.length > 0 && (
        <div className="mt-2">
          <p className="text-[14px]">还带上你这几句话：</p>
          <ul className="mt-1 space-y-0.5">
            {row.shows_records.map((text) => (
              <li key={text} className="text-[14px] text-ink-soft">
                {text}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 一步收回。问一句"确定吗"就是在用摩擦力换留存率。 */}
      <button
        type="button"
        disabled={busy}
        onClick={() => void takeBack()}
        className="mt-4 rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white disabled:opacity-35"
      >
        收回
      </button>

      {failed && (
        <p role="alert" className="mt-3 text-[13px] text-clash">
          这一下没发出去，他们还看得到。再点一次试试。
        </p>
      )}
    </article>
  );
}
