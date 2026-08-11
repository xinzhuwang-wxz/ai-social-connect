"use client";

/**
 * 第六屏：一起把这件事做完的地方。标题就是这个项目自己的名字。
 *
 * 六条产品判断决定了这一屏长成现在这样：
 *
 * 1. **这是结构化画布，不是群聊。** 群聊里信息会沉底、决定没有归属、没读的人
 *    默认被代表。所以这里每条东西都有类型、状态、负责人和时限，一屏就能看见
 *    要做什么、卡在哪、还有哪些决定没关。
 * 2. **一条只出现一次。** 卡住的、要定的排在前面，剩下的归「要做什么」。同一张卡
 *    同时出现在两栏里，看板就开始说谎——数一遍以为六件事，其实只有四件。
 *    排序本身就是一句话：先看这里。
 * 3. **助手在角落，不在中央。** 它说话短，绝不主动弹窗，每条都带一个「不用了」。
 *    顶上那个开关能把它关掉，**关掉之后这一屏一格不少**——这是产品的一条承诺，
 *    界面上要看得出来，不能只写在文档里。
 * 4. **它写的东西一眼可辨，采纳之前不算数。** 灰紫加虚线是它专用的视觉通道；
 *    没人认下的那些不进进度、不落任何人待办、做不了任何结论。
 * 5. **要定的事说「还差谁」，不说比例。**「还差陈牧和苏晚点头」比「2/4 已确认」
 *    有用得多——看到名字的人知道该去戳谁，看到分数的人只能干等。
 * 6. **不显示任何人的内部编号。** 这一屏拿不到这个空间有哪些人的名字，那就说
 *    「有人在做」，不把一串编号糊到脸上。少说一句，好过说一句没人看得懂的话。
 *
 * 界面文案不使用领域词汇（见 docs/07 语言映射表）。
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { currentPrincipal } from "@/lib/session";
import {
  OURS,
  OUTSIDE,
  REACH,
  SOURCE,
  acceptSuggestion,
  addItem,
  board,
  canAsk,
  confirmItem,
  fetchSpace,
  itemKinds,
  justStarted,
  moves,
  myNod,
  reviseItem,
  suggestionsFor,
  toggleAgent,
  type Item,
  type ItemKind,
  type Progress,
  type Space,
  type Suggestion,
} from "@/lib/space";

import { whenPhrase } from "./waiting-screen";

/**
 * 状态在界面上怎么说。
 *
 * 后端发的是 `doing` 这类标识符，它们不能出现在屏幕上。翻不出来的不显示
 * 英文原文——宁可少一行，不能露一个字段名。
 */
const STATE_WORDS: Record<string, string> = {
  todo: "还没开始",
  doing: "在做了",
  done: "做完了",
  open: "还没定",
  settled: "定下来了",
  shared: "放上来了",
};

/** 把一条推到某个状态时，按钮上说什么。翻不出来的那一步就不给按钮。 */
const MOVE_WORDS: Record<string, string> = {
  todo: "先放回没开始",
  doing: "我开始做了",
  done: "做完了",
};

/** 谁能看见。两档，默认是窄的那一档。 */
const REACH_WORDS: Record<string, string> = {
  [OURS]: "只有我们几个看得见",
  [OUTSIDE]: "外面也看得见",
};

export function SpaceScreen({ spaceId }: { spaceId: string }) {
  const [space, setSpace] = useState<Space | null>(null);
  const [kinds, setKinds] = useState<ItemKind[] | null>(null);
  const [tips, setTips] = useState<Suggestion[] | null>(null);
  const [failed, setFailed] = useState(false);
  /**
   * 说过「不用了」的那几条。
   *
   * 建议不落库，所以「不用了」在服务端没有地方记。放在这一层而不是放在助手
   * 那张卡里，是为了让它熬过一次刷新——刚推掉的东西下一秒又冒出来，
   * 那个「不用了」就成了摆设。
   */
  const [waved, setWaved] = useState<string[]>([]);

  const readTips = useCallback(
    (id: string) => suggestionsFor(id).then(setTips, () => setTips(null)),
    [],
  );

  const load = useCallback(async () => {
    setFailed(false);
    setSpace(null);
    let loaded: Space;
    try {
      loaded = await fetchSpace(spaceId);
    } catch {
      setFailed(true);
      return;
    }
    setSpace(loaded);
    // 三段各自取数：条目类型或助手那一段挂了，画布照常。
    // 合成一次取数的话，一处失败就是整屏失败。
    itemKinds().then(setKinds, () => setKinds(null));
    void readTips(spaceId);
  }, [spaceId, readTips]);

  useEffect(() => {
    void load();
  }, [load]);

  /** 动完一下之后重新看一眼。不清空画布，免得每点一次就闪一遍骨架。 */
  const refresh = useCallback(() => {
    fetchSpace(spaceId).then(setSpace, () => {});
    void readTips(spaceId);
  }, [spaceId, readTips]);

  if (failed) {
    return (
      <Shell title="这件事">
        <section role="alert" className="rounded-[16px] border border-line bg-card p-5">
          <p className="text-[15px]">现在打不开这个地方。</p>
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

  if (space === null) {
    return (
      <Shell title="这件事">
        <div className="space-y-3" aria-label="加载中">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-28 animate-pulse rounded-[16px] bg-line" />
          ))}
        </div>
      </Shell>
    );
  }

  const me = currentPrincipal();
  const { stuck, gates, rest } = board(space);
  const fresh = justStarted(space);
  const byKey = new Map((kinds ?? []).map((k) => [k.key, k]));
  const live = (tips ?? []).filter((t) => !waved.includes(t.title));

  const card = (item: Item) => (
    <Card
      key={item.id}
      item={item}
      kind={byKey.get(item.kind)}
      me={me}
      spaceId={spaceId}
      onChanged={refresh}
    />
  );

  return (
    <Shell title={space.title} lead={space.summary}>
      <DoneBar progress={space.progress} />

      <AgentSwitch
        spaceId={spaceId}
        on={space.agent_enabled}
        onSwitched={(next) => {
          setSpace(next);
          void readTips(spaceId);
        }}
      />

      {fresh && <FirstStep space={space} />}

      <div className="mt-8 space-y-8">
        <Group
          title="卡在哪"
          note="没人认领，或者过了说好的时间。一件事没有名字挂在上面，它就不会自己往前走。"
          empty="没有卡住的。"
        >
          {stuck.map(card)}
        </Group>

        <Group
          title="还没定下来的"
          note="相关的人一个不少地点过头，才算定下来。"
          empty="没有等着定的事。"
        >
          {gates.map(card)}
        </Group>

        <Group
          title="要做什么"
          empty={
            space.cards.length > 0
              ? "其余的都在上面两栏里。"
              : "还没有要做的事。在下面放一条。"
          }
        >
          {rest.map(card)}
        </Group>

        <Group
          title="等你过目"
          note="助手写的。在你认下之前它不算数：不进进度，也不落到任何人头上。"
          empty={
            space.agent_enabled
              ? "助手现在没写什么。"
              : "助手关着。它写过的东西还留着，重新打开就回来。"
          }
        >
          {space.drafts.map(card)}
        </Group>
      </div>

      <AddItem spaceId={spaceId} kinds={kinds} open={fresh} onAdded={refresh} />

      {space.agent_enabled && live.length > 0 && (
        <Assistant
          spaceId={spaceId}
          tips={live}
          onWaved={(title) => setWaved((was) => [...was, title])}
          onTook={(title) => {
            setWaved((was) => [...was, title]);
            refresh();
          }}
        />
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
      <header className="mb-6">
        <h1 className="text-[20px] font-semibold tracking-tight">{title}</h1>
        {lead && <p className="mt-1 text-[13px] text-ink-soft">{lead}</p>}
      </header>
      {children}
    </main>
  );
}

/**
 * 做完了多少。
 *
 * 一格一件，不是一个百分比——这个产品不做总分。助手起草而没人认领的那些
 * 既不占格子也不填格子，所以它多写几条并不会把这条变短。
 */
function DoneBar({ progress }: { progress: Progress }) {
  if (progress.total === 0) return null;
  return (
    <div
      role="img"
      aria-label={`一共 ${progress.total} 件，做完 ${progress.done} 件`}
      className="flex gap-1"
    >
      {[...Array(progress.total)].map((_, i) => (
        <span
          key={i}
          className={`h-1.5 min-w-0 flex-1 rounded-full ${
            i < progress.done ? "bg-settled" : "bg-line"
          }`}
        />
      ))}
    </div>
  );
}

/**
 * 顶上那个开关。
 *
 * 旁边那句话不是装饰：关掉助手之后这一屏照常可用是产品的一条承诺，
 * 用户得在按下去之前就知道这一点，不然没人敢按。
 */
function AgentSwitch({
  spaceId,
  on,
  onSwitched,
}: {
  spaceId: string;
  on: boolean;
  onSwitched: (space: Space) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function flip() {
    setBusy(true);
    setFailed(false);
    try {
      onSwitched(await toggleAgent(spaceId, !on));
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1">
      <button
        type="button"
        role="switch"
        aria-checked={on}
        disabled={busy}
        onClick={() => void flip()}
        className={`rounded-[12px] border px-3 py-1.5 text-[14px] disabled:opacity-35 ${
          on ? "border-accent bg-accent-soft text-accent" : "border-line text-ink-soft"
        }`}
      >
        助手帮我看着
      </button>
      <span className="text-[13px] text-ink-faint">
        {on ? "随时关掉，这一屏其余照常" : "关着。这一屏其余照常"}
      </span>
      {failed && (
        <p role="alert" className="text-[13px] text-clash">
          这一下没发出去，开关还是原样。再点一次试试。
        </p>
      )}
    </div>
  );
}

/**
 * 刚开始的那一屏。
 *
 * 成局时留下的那一张卡就是下一步，所以这里把它的名字直接说出来。一个空看板
 * 会让人以为自己走错了地方，而这一屏最贵的就是刚成局那几分钟。
 */
function FirstStep({ space }: { space: Space }) {
  const first = space.cards[0];
  return (
    <section
      aria-label="从哪开始"
      className="mt-6 rounded-[16px] border border-line bg-card p-5"
    >
      {first ? (
        <>
          <p className="text-[16px]">先做这件事：{first.title}</p>
          <p className="mt-2 text-[14px] text-ink-soft">
            这是你们刚说好要自己定的那件事。认领它，或者往下面再放一条。
          </p>
        </>
      ) : (
        <>
          <p className="text-[16px]">这里还什么都没有。</p>
          <p className="mt-2 text-[14px] text-ink-soft">
            放一条要做的事，写清是什么。谁来做、什么时候之前做完，都可以放上去之后再说。
          </p>
        </>
      )}
    </section>
  );
}

function Group({
  title,
  note,
  empty,
  children,
}: {
  title: string;
  note?: string;
  empty: string;
  children: ReactNode[];
}) {
  return (
    <section aria-label={title}>
      <h2 className="text-[16px] font-medium">{title}</h2>
      {note && <p className="mt-0.5 text-[13px] text-ink-soft">{note}</p>}
      {children.length === 0 ? (
        <p className="mt-2 text-[14px] text-ink-faint">{empty}</p>
      ) : (
        <div className="mt-3 space-y-3">{children}</div>
      )}
    </section>
  );
}

/**
 * 画布上的一张卡。
 *
 * 助手写的用灰紫加虚线，和真人确认过的内容一眼可辨（08 §2.1）。还没人认下的
 * 那些不给任何操作按钮：它还不算数，给按钮就等于让人以为它已经在推进了。
 */
function Card({
  item,
  kind,
  me,
  spaceId,
  onChanged,
}: {
  item: Item;
  kind: ItemKind | undefined;
  me: string;
  spaceId: string;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [needsNods, setNeedsNods] = useState(false);

  async function run(act: () => Promise<unknown>, refused?: () => void) {
    setBusy(true);
    setFailed(false);
    setNeedsNods(false);
    try {
      await act();
      onChanged();
    } catch {
      if (refused) refused();
      else setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  const guess = item.awaiting_a_person;
  const nod = myNod(item, me);
  // 只说这一类自己声明过的状态。落到一条没声明过的状态上时（后端写进来的
  // 遗留值），宁可不说，也不能把「还没定」贴到一件要做的事上。
  const known = !kind || kind.states.includes(item.state);
  const state = known ? STATE_WORDS[item.state] : undefined;
  const facts = [
    item.assignee_id === me ? "你在做" : item.assignee_id ? "有人在做" : null,
    item.due_at ? `${whenPhrase(item.due_at, new Date())}之前` : null,
    state ?? null,
  ].filter(Boolean);

  return (
    <article
      aria-label={item.title}
      className={`rounded-[16px] border p-5 ${
        guess ? "border-dashed border-draft bg-draft-soft" : "border-line bg-card"
      }`}
    >
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-[16px] font-medium">{item.title}</h3>
        <span className="shrink-0 text-[11px] text-ink-faint">{item.label}</span>
      </div>

      {item.body && <p className="mt-1 text-[14px] text-ink-soft">{item.body}</p>}

      {item.drafted_by_agent && (
        <p className="mt-1 text-[11px] text-draft">
          {guess ? "还没人认下这条，它不算数" : "助手起草，有人认下了"}
        </p>
      )}

      {facts.length > 0 && (
        <p className="mt-2 text-[13px] text-ink-soft">{facts.join(" · ")}</p>
      )}

      {item.source && (
        <p className="mt-1 text-[13px] text-ink-faint">从哪来的：{item.source}</p>
      )}
      {item.reach && (
        <p className="mt-1 text-[13px] text-ink-faint">{REACH_WORDS[item.reach]}</p>
      )}

      {/* 这一刻这张卡该说的那句话。要定的事在这里说的是「还差谁」。 */}
      {item.notice && <p className="mt-2 text-[14px] text-pending">{item.notice}</p>}

      {!guess && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          {nod === "mine" && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void run(() => confirmItem(spaceId, item.id))}
              className="rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white disabled:opacity-35"
            >
              我点头
            </button>
          )}
          {nod === "done" && <span className="text-[14px] text-settled">你点过头了</span>}

          {kind?.counts_toward_progress &&
            (item.assignee_id === me ? (
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  void run(() => reviseItem(spaceId, item.id, { assignee_id: null }))
                }
                className="rounded-[12px] border border-line px-4 py-2 text-[14px] disabled:opacity-35"
              >
                放回去
              </button>
            ) : (
              !item.assignee_id && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void run(() => reviseItem(spaceId, item.id, { assignee_id: me }))
                  }
                  className="rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white disabled:opacity-35"
                >
                  我来做
                </button>
              )
            ))}

          {kind &&
            moves(kind, item).map((to) =>
              MOVE_WORDS[to] ? (
                <button
                  key={to}
                  type="button"
                  disabled={busy}
                  onClick={() => void run(() => reviseItem(spaceId, item.id, { state: to }))}
                  className="rounded-[12px] border border-line px-4 py-2 text-[14px] disabled:opacity-35"
                >
                  {MOVE_WORDS[to]}
                </button>
              ) : null,
            )}

          {/* 收回来是权利，一步完成；发出去要相关的人先点过头。
              两边不对称是刻意的：要走流程才能收回的权利等于没有。 */}
          {item.reach === OUTSIDE && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void run(() => reviseItem(spaceId, item.id, { reach: OURS }))}
              className="rounded-[12px] border border-line px-4 py-2 text-[14px] disabled:opacity-35"
            >
              收回来，只给我们看
            </button>
          )}
          {item.reach === OURS && (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void run(
                  () => reviseItem(spaceId, item.id, { reach: OUTSIDE }),
                  () => setNeedsNods(true),
                )
              }
              className="rounded-[12px] border border-line px-4 py-2 text-[14px] disabled:opacity-35"
            >
              放到外面去
            </button>
          )}
        </div>
      )}

      {needsNods && (
        <p className="mt-3 text-[13px] text-ink-soft">
          放到外面去这件事，得相关的人先点过头。先开一条要定的事。
        </p>
      )}

      {failed && (
        <p role="alert" className="mt-3 text-[13px] text-clash">
          这一下没发出去，这条还是原样。再点一次试试。
        </p>
      )}
    </article>
  );
}

/**
 * 放一条东西。
 *
 * 选项来自后端的清单，不是这里写死的一张表——那边多声明一类，这里自动多一项。
 * 这一屏问不出必填项的那几类不进选项：先收下再让后端拒，等于把一次报错
 * 当成了界面。
 */
function AddItem({
  spaceId,
  kinds,
  open,
  onAdded,
}: {
  spaceId: string;
  kinds: ItemKind[] | null;
  open: boolean;
  onAdded: () => void;
}) {
  const usable = (kinds ?? []).filter(canAsk);
  const [showing, setShowing] = useState(open);
  const [picked, setPicked] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [source, setSource] = useState("");
  const [reach, setReach] = useState<string>(OURS);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  if (kinds === null || usable.length === 0) {
    return (
      <p className="mt-8 text-[13px] text-ink-faint">
        现在放不了新东西。上面这些照常能用。
      </p>
    );
  }

  const kind = usable.find((k) => k.key === picked) ?? usable[0]!;
  const wants = (key: string) => kind.required_extras.includes(key);
  const ready =
    title.trim().length > 0 && (!wants(SOURCE) || source.trim().length > 0);

  async function put() {
    setBusy(true);
    setFailed(false);
    const extras: Record<string, unknown> = {};
    if (wants(SOURCE)) extras[SOURCE] = source.trim();
    if (wants(REACH)) extras[REACH] = reach;
    try {
      await addItem(spaceId, {
        kind: kind.key,
        title: title.trim(),
        body: body.trim() || null,
        extras,
      });
      setTitle("");
      setBody("");
      setSource("");
      setReach(OURS);
      onAdded();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  if (!showing) {
    return (
      <button
        type="button"
        onClick={() => setShowing(true)}
        className="mt-8 rounded-[12px] border border-line px-4 py-2 text-[14px]"
      >
        放一条东西
      </button>
    );
  }

  return (
    <section
      aria-label="放一条东西"
      className="mt-8 rounded-[16px] border border-line bg-card p-5"
    >
      <div role="radiogroup" aria-label="放什么" className="flex flex-wrap gap-2">
        {usable.map((k) => (
          <button
            key={k.key}
            type="button"
            role="radio"
            aria-checked={k.key === kind.key}
            onClick={() => setPicked(k.key)}
            className={`rounded-[12px] border px-3 py-1.5 text-[14px] ${
              k.key === kind.key
                ? "border-accent bg-accent-soft text-accent"
                : "border-line"
            }`}
          >
            {k.label}
          </button>
        ))}
      </div>

      <label className="mt-4 block">
        <span className="text-[13px] text-ink-soft">一句话说清是什么</span>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          aria-label="一句话说清是什么"
          placeholder="比如：周三之前把脚本写完"
          className="mt-1 w-full rounded-[8px] border border-line p-3 text-[15px] outline-none placeholder:text-ink-faint focus:border-accent"
        />
      </label>

      <label className="mt-3 block">
        <span className="text-[13px] text-ink-soft">要多说两句的话</span>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={2}
          aria-label="要多说两句的话"
          className="mt-1 w-full resize-none rounded-[8px] border border-line p-3 text-[15px] outline-none focus:border-accent"
        />
      </label>

      {wants(SOURCE) && (
        <label className="mt-3 block">
          <span className="text-[13px] text-ink-soft">从哪来的</span>
          <input
            value={source}
            onChange={(e) => setSource(e.target.value)}
            aria-label="从哪来的"
            placeholder="比如：苏晚周二拍的那段"
            className="mt-1 w-full rounded-[8px] border border-line p-3 text-[15px] outline-none placeholder:text-ink-faint focus:border-accent"
          />
        </label>
      )}

      {wants(REACH) && (
        <div role="radiogroup" aria-label="谁能看见" className="mt-3 flex flex-wrap gap-2">
          {[OURS, OUTSIDE].map((value) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={reach === value}
              onClick={() => setReach(value)}
              className={`rounded-[12px] border px-3 py-1.5 text-[14px] ${
                reach === value
                  ? "border-accent bg-accent-soft text-accent"
                  : "border-line"
              }`}
            >
              {REACH_WORDS[value]}
            </button>
          ))}
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={busy || !ready}
          onClick={() => void put()}
          className="rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white disabled:opacity-35"
        >
          放上去
        </button>
        <button
          type="button"
          onClick={() => setShowing(false)}
          className="text-[14px] text-ink-soft underline underline-offset-4 hover:text-ink"
        >
          先不放了
        </button>
      </div>

      {failed && (
        <p role="alert" className="mt-3 text-[13px] text-clash">
          这一条没放上去。看看要填的那几项是不是都填了，再试一次。
        </p>
      )}
    </section>
  );
}

/**
 * 角落里那张会说话的卡片。
 *
 * 它不占主区、不弹窗、说话短。每条都带一个「不用了」——一段话里混着三条建议，
 * 用户要么全接受要么全拒绝，那个「不用了」就无从谈起（07 原则四）。
 * 也没有一键全收：一键全收和让它自己写进去没有区别，中间那个人只是按了一下。
 */
function Assistant({
  spaceId,
  tips,
  onWaved,
  onTook,
}: {
  spaceId: string;
  tips: Suggestion[];
  onWaved: (title: string) => void;
  onTook: (title: string) => void;
}) {
  return (
    <aside
      aria-label="助手写的"
      className="mt-8 rounded-[16px] border border-dashed border-draft bg-draft-soft p-4 lg:fixed lg:right-6 lg:bottom-6 lg:mt-0 lg:w-72"
    >
      <p className="text-[13px] text-draft">这几条我先写着，你看要不要。</p>
      <ul className="mt-2 space-y-3">
        {tips.map((tip) => (
          <Tip
            key={tip.title}
            spaceId={spaceId}
            tip={tip}
            onWaved={() => onWaved(tip.title)}
            onTook={() => onTook(tip.title)}
          />
        ))}
      </ul>
    </aside>
  );
}

function Tip({
  spaceId,
  tip,
  onWaved,
  onTook,
}: {
  spaceId: string;
  tip: Suggestion;
  onWaved: () => void;
  onTook: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function take() {
    setBusy(true);
    setFailed(false);
    try {
      await acceptSuggestion(spaceId, {
        kind: tip.kind,
        title: tip.title,
        grounded_in: tip.grounded_in,
      });
      onTook();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li aria-label={tip.title}>
      <p className="text-[15px]">{tip.title}</p>
      {tip.grounded_in.length > 0 && (
        <p className="mt-0.5 text-[13px] text-ink-faint">
          我是看着这个写的：{tip.grounded_in.join("、")}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={busy}
          onClick={() => void take()}
          className="rounded-[12px] bg-accent px-3 py-1.5 text-[14px] font-medium text-white disabled:opacity-35"
        >
          放进来
        </button>
        {/* 一步说完，不问为什么。要问理由的拒绝就是在用摩擦力换同意率。 */}
        <button
          type="button"
          onClick={onWaved}
          className="rounded-[12px] border border-line px-3 py-1.5 text-[14px]"
        >
          不用了
        </button>
      </div>
      {failed && (
        <p role="alert" className="mt-2 text-[13px] text-clash">
          这一下没放进去。再点一次试试。
        </p>
      )}
    </li>
  );
}
