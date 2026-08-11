"use client";

/**
 * 「这次你会得到什么」：被邀请的那一侧。
 *
 * 五条产品判断决定了这一屏长成现在这样：
 *
 * 1. **主语是「我」，不是「你被选中了」。** 单向推荐会让接收方觉得自己是被挑的
 *    商品；而一次配对要成，必须两边都愿意——只看单边相关度会系统性高估
 *    真实匹配。所以这一屏先回答"我会得到什么"，再说别的。
 * 2. **得到排在付出前面。** 先说代价的邀请没人会读完。顺序在这里不是排版偏好，
 *    是这一屏还有没有人读下去的分界线。
 * 3. **不参加零负担。** 和「我加入」同一行、同等重量，一步完成，不二次确认、
 *    不问理由。要用摩擦力换的是承诺，不是拒绝——反过来做就是在换同意率。
 * 4. **「我可以，但……」必须写得清。** 条件写不清，对方无从回应，一次本可以谈成
 *    的事就变成一次没人看得懂的沉默。所以空条件不给发。
 * 5. **说清到什么时候要答复。** 不说的话，用户会把它当成一件可以永远拖着的事，
 *    而队里其余的人正在等他。
 *
 * 界面文案不使用领域词汇（见 docs/07 语言映射表）。
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { ApiError } from "@/lib/api";
import {
  invitationFor,
  myInvitations,
  type Invitation,
} from "@/lib/invitations";
import {
  ACCEPTED,
  CONDITIONAL,
  DECLINED,
  decide,
  gateStatus,
  type GateStatus,
} from "@/lib/matching";
import { currentPrincipal } from "@/lib/session";

import { whenPhrase } from "./waiting-screen";

/** 我被邀请进的每一队。这一屏是入口，答复在每张卡上就地完成。 */
export function InvitationsScreen() {
  const [invitations, setInvitations] = useState<Invitation[] | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setFailed(false);
    setInvitations(null);
    try {
      setInvitations(await myInvitations());
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (failed) {
    return (
      <Shell title="有人在等你">
        <Broken onRetry={() => void load()} />
      </Shell>
    );
  }

  if (invitations === null) {
    return (
      <Shell title="有人在等你">
        <Skeleton />
      </Shell>
    );
  }

  if (invitations.length === 0) {
    return (
      <Shell title="有人在等你">
        <section className="rounded-[16px] border border-line bg-card p-6">
          <p className="text-[16px]">现在没有人在等你答复。</p>
          <p className="mt-2 text-[14px] text-ink-soft">
            有人想拉你一起做事的时候，这里会先告诉你这次你会得到什么，再问你去不去。
            不去也不用解释。
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

  return (
    <Shell
      title="有人在等你"
      lead={`有 ${invitations.length} 件事在等你答复。先看这次你会得到什么，再决定去不去。`}
    >
      <div className="space-y-6">
        {invitations.map((invitation) => (
          <InvitationCard key={invitation.proposal_id} invitation={invitation} />
        ))}
      </div>
    </Shell>
  );
}

/** 单独一队。从通知点进来看到的就是这一屏。 */
export function InvitationScreen({ proposalId }: { proposalId: string }) {
  const [invitation, setInvitation] = useState<Invitation | null>(null);
  const [failed, setFailed] = useState(false);
  const [gone, setGone] = useState(false);

  const load = useCallback(async () => {
    setFailed(false);
    setGone(false);
    setInvitation(null);
    try {
      setInvitation(await invitationFor(proposalId));
    } catch (error) {
      // 找不到和没连上是两件事：一个该说"它不在了"，另一个该说"再试一次"。
      if (error instanceof ApiError && error.status === 404) setGone(true);
      else setFailed(true);
    }
  }, [proposalId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (gone) {
    return (
      <Shell title="这次你会得到什么">
        <section className="rounded-[16px] border border-line bg-card p-6">
          <p className="text-[16px]">这件事已经不在了。</p>
          <p className="mt-2 text-[14px] text-ink-soft">
            可能是过了答复的时间，也可能这几个人的安排改了。你没有错过什么要紧的——
            改完他们会再来问你一次。
          </p>
          <a
            href="/invitations"
            className="mt-5 inline-block rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white"
          >
            看看还有谁在等你
          </a>
        </section>
      </Shell>
    );
  }

  if (failed) {
    return (
      <Shell title="这次你会得到什么">
        <Broken onRetry={() => void load()} />
      </Shell>
    );
  }

  if (invitation === null) {
    return (
      <Shell title="这次你会得到什么">
        <Skeleton />
      </Shell>
    );
  }

  return (
    <Shell title="这次你会得到什么">
      <InvitationCard invitation={invitation} />
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

function Skeleton() {
  return (
    <div className="space-y-3" aria-label="加载中">
      {[...Array(2)].map((_, i) => (
        <div key={i} className="h-40 animate-pulse rounded-[16px] bg-line" />
      ))}
    </div>
  );
}

function Broken({ onRetry }: { onRetry: () => void }) {
  return (
    <section role="alert" className="rounded-[16px] border border-line bg-card p-5">
      <p className="text-[15px]">现在调不出等你答复的事。</p>
      <p className="mt-1 text-[13px] text-ink-soft">
        没连上的时候不会替你答复任何人，你回来再决定也不迟。
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

function InvitationCard({ invitation }: { invitation: Invitation }) {
  const [status, setStatus] = useState<GateStatus | null>(null);
  // 降级：读不到「还在等谁」不该挡住答复——挡住的代价是用户什么都做不了。
  const [statusDown, setStatusDown] = useState(false);
  const [mine, setMine] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [condition, setCondition] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    gateStatus(invitation.proposal_id).then(setStatus, () => setStatusDown(true));
  }, [invitation.proposal_id]);

  async function answer(value: string, text?: string) {
    setBusy(true);
    setFailed(false);
    try {
      setStatus(await decide(invitation.proposal_id, value, text));
      setStatusDown(false);
      setMine(value);
      setAsking(false);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  const me = currentPrincipal();
  const waitingOn = status?.waiting_on ?? [];
  // 已经答过的人不该被再问一次。读不到状态时按"还没答"算——
  // 多问一次比让人无法答复好。
  const answered =
    mine !== null ||
    (status !== null && (status.verdict !== "waiting" || !waitingOn.includes(me)));

  return (
    <section
      aria-label={invitation.about}
      className="rounded-[16px] border border-line bg-card p-5"
    >
      <h2 className="text-[16px] font-medium">{invitation.about}</h2>
      {invitation.with_others.length > 0 && (
        <p className="mt-1 text-[13px] text-ink-soft">
          和{invitation.with_others.join("、")}一起
        </p>
      )}

      <div className="mt-4">
        <h3 className="text-[13px] text-ink-soft">你会得到</h3>
        {invitation.i_get.length === 0 ? (
          <p className="mt-1.5 text-[14px] text-ink-soft">
            这次没说清你会得到什么。说不清的事你可以不去，不用解释。
          </p>
        ) : (
          <ul className="mt-1.5 space-y-1.5">
            {invitation.i_get.map((line) => (
              <li key={line} className="text-[15px]">
                {line}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="mt-4">
        <h3 className="text-[13px] text-ink-soft">你要出的</h3>
        {invitation.i_give.length === 0 ? (
          <p className="mt-1.5 text-[14px] text-ink-soft">这次没有要你专门出什么。</p>
        ) : (
          <ul className="mt-1.5 space-y-1.5">
            {invitation.i_give.map((line) => (
              <li key={line} className="text-[15px]">
                {line}
              </li>
            ))}
          </ul>
        )}
        {invitation.time_cost && (
          <p className="mt-1.5 text-[14px] text-ink-soft">
            大概要花：{invitation.time_cost}
          </p>
        )}
      </div>

      <p className="mt-4 text-[13px] text-ink-faint">
        {whenPhrase(invitation.answer_by, new Date())}之前答复。过了这个点就不留着了。
      </p>

      <div className="mt-5 border-t border-line pt-4">
        {answered ? (
          <Answered mine={mine} status={status} />
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              disabled={busy}
              onClick={() => void answer(ACCEPTED)}
              className="rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white disabled:opacity-35"
            >
              我加入
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setAsking(!asking)}
              aria-expanded={asking}
              className="rounded-[12px] border border-line px-4 py-2 text-[14px] disabled:opacity-35"
            >
              我可以，但……
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void answer(DECLINED)}
              className="rounded-[12px] border border-line px-4 py-2 text-[14px] disabled:opacity-35"
            >
              我不参加
            </button>
          </div>
        )}

        {asking && !answered && (
          <div className="mt-3">
            <label className="block">
              <span className="text-[13px] text-ink-soft">你的条件是什么？</span>
              <textarea
                value={condition}
                onChange={(e) => setCondition(e.target.value)}
                rows={2}
                aria-label="你的条件是什么？"
                placeholder="比如：周四我要上课，换成周三我就来"
                className="mt-1 w-full resize-none rounded-[8px] border border-line p-3 text-[15px] outline-none placeholder:text-ink-faint focus:border-accent"
              />
            </label>
            <p className="mt-1 text-[13px] text-ink-faint">
              这句话会原样带给他们。写清一点，他们才知道怎么改。
            </p>
            <button
              type="button"
              disabled={busy || !condition.trim()}
              onClick={() => void answer(CONDITIONAL, condition.trim())}
              className="mt-2 rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white disabled:opacity-35"
            >
              就这么说
            </button>
          </div>
        )}

        {statusDown && !answered && (
          <p className="mt-3 text-[13px] text-ink-faint">
            现在看不到还有谁没回。你照常决定，你的答复不受影响。
          </p>
        )}

        {failed && (
          <p role="alert" className="mt-3 text-[13px] text-clash">
            这一下没发出去。这几个人的安排可能已经变了，重新看一眼再决定。
          </p>
        )}
      </div>
    </section>
  );
}

/** 我已经答过之后，这张卡说什么。 */
function Answered({ mine, status }: { mine: string | null; status: GateStatus | null }) {
  if (mine === DECLINED) {
    return <p className="text-[15px]">知道了。这次就到这里。</p>;
  }

  const verdict = status?.verdict;

  if (verdict === "open") {
    return (
      <div>
        <p className="text-[15px]">都点头了，这件事成了。</p>
        {status?.formed_event_id && (
          <a
            href={`/events/${status.formed_event_id}/echo`}
            className="mt-2 inline-block text-[14px] text-ink-soft underline underline-offset-4 hover:text-ink"
          >
            去看这次留下了什么
          </a>
        )}
      </div>
    );
  }

  if (verdict === "needs_revision") {
    return (
      <p className="text-[15px]">
        {mine === CONDITIONAL
          ? "你的话已经带过去了。这几个人的安排要改一版，改好会再来问你一次。"
          : "有人提了条件。这几个人的安排要改一版，改好会再来问你一次。"}
      </p>
    );
  }

  if (verdict === "declined") {
    return <p className="text-[15px]">有人这次不参加，这一版先停下了。</p>;
  }

  if (verdict === "expired") {
    return <p className="text-[15px]">过了答复的时间，这次没赶上。</p>;
  }

  const left = status?.waiting_on?.length ?? 0;
  return (
    <p className="text-[15px]">
      {left > 0
        ? `还差 ${left} 个人点头。`
        : status === null
          ? "你的答复已经发出去了。"
          : "还差几个人点头。"}
    </p>
  );
}
