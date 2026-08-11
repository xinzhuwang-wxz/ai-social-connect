"use client";

/**
 * 第四屏：给你找的人。
 *
 * 五条产品判断决定了这一屏长成现在这样：
 *
 * 1. **没有百分比，没有分数。** 一个「匹配度 87%」用户既无从判断也无从反驳。
 *    这里只有逐条的理由，每条都能点开看它是从哪来的。
 * 2. **默认只显示结论。** 一队有六条依据、几条待决、几条不确定，全摊开就没人读了。
 *    点一行看一行的来源——密度不降低，可信度也不丢。
 * 3. **「留给你们自己定」不是缺陷。** 合不合得来、署名怎么算，这些即使有数据
 *    也不该由系统替人定。文案上要说成刻意留的，不是没算出来。
 * 4. **不确定的地方自己说出来。** 藏起来比说出来伤害大：用户迟早会发现，
 *    那时候丢的是对整份说明的信任。
 * 5. **拒绝零负担。** 一步完成，不二次确认，不问为什么。要确认的是承诺，
 *    不是拒绝——反过来做，就是在用摩擦力换同意率。
 *
 * 界面文案不使用领域词汇（见 docs/07 语言映射表）。
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { currentPrincipal } from "@/lib/session";
import {
  ACCEPTED,
  CONDITIONAL,
  DECLINED,
  decide,
  gateStatus,
  teamsFor,
  type GateStatus,
  type ProofLine,
  type Team,
} from "@/lib/matching";

import { BlockedScreen } from "./blocked-screen";
import { whenPhrase } from "./waiting-screen";

/**
 * 每条理由是从哪来的。
 *
 * 后端给的是 `user_statement` 这类标识符，它们不能出现在屏幕上；这一层把它们
 * 翻成人话。翻不出来的不显示英文原文——宁可少一行，不能露一个字段名。
 */
const SOURCE_WORDS: Record<string, string> = {
  user_statement: "你自己写下的",
  approved_facet: "他本人同意让你看到的经历",
  solver_constraint: "照着你说必须满足的那几条对出来的",
  objective_contribution: "照着你说会尽量考虑的那几条挑出来的",
  unresolved_conflict: "两边说法对不上，这一条我没敢替你判",
};

export function TeamsScreen({ intentId }: { intentId: string }) {
  const [teams, setTeams] = useState<Team[] | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setFailed(false);
    setTeams(null);
    try {
      setTeams(await teamsFor(intentId));
    } catch {
      setFailed(true);
    }
  }, [intentId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (failed) {
    return (
      <Shell title="给你找的人">
        <section role="alert" className="rounded-[16px] border border-line bg-card p-5">
          <p className="text-[15px]">现在调不出给你找的人。</p>
          <p className="mt-1 text-[13px] text-ink-soft">
            没连上的时候不会替你答复任何人，你回来再决定也不迟。
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

  if (teams === null) {
    return (
      <Shell title="给你找的人">
        <div className="space-y-3" aria-label="加载中">
          {[...Array(2)].map((_, i) => (
            <div key={i} className="h-40 animate-pulse rounded-[16px] bg-line" />
          ))}
        </div>
      </Shell>
    );
  }

  // 空态：这一轮没凑出来。这里不是"暂无结果"，是另一屏。
  if (teams.length === 0) {
    return (
      <Shell title="还差这几件事">
        <BlockedScreen intentId={intentId} />
      </Shell>
    );
  }

  return (
    <Shell
      title="给你找的人"
      lead={`这是这一轮配给你的 ${teams.length} 个小队。选一个，或者都不选——不选不用解释。`}
    >
      <div className="space-y-6">
        {teams.map((team) => (
          <TeamCard key={team.proposal_id} team={team} onRevised={() => void load()} />
        ))}
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
    <main className="mx-auto w-full max-w-2xl px-5 py-10 sm:py-16">
      <header className="mb-8">
        <h1 className="text-[20px] font-semibold tracking-tight">{title}</h1>
        {lead && <p className="mt-1 text-[13px] text-ink-soft">{lead}</p>}
      </header>
      {children}
    </main>
  );
}

function TeamCard({ team, onRevised }: { team: Team; onRevised: () => void }) {
  const [status, setStatus] = useState<GateStatus | null>(null);
  // 降级：读不到「还在等谁」不该挡住答复——挡住的代价是用户什么都做不了。
  const [statusDown, setStatusDown] = useState(false);
  const [mine, setMine] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [condition, setCondition] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    gateStatus(team.proposal_id).then(setStatus, () => setStatusDown(true));
  }, [team.proposal_id]);

  async function answer(value: string, text?: string) {
    setBusy(true);
    setFailed(false);
    try {
      setStatus(await decide(team.proposal_id, value, text));
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
  // 已经回过的人不该被再问一次。读不到状态时按"还没回"算——
  // 多问一次比让人无法答复好。
  const answered =
    mine !== null ||
    (status !== null && (status.verdict !== "waiting" || !waitingOn.includes(me)));

  return (
    <section
      aria-label={team.members.map((m) => m.display_name).join("、")}
      className="rounded-[16px] border border-line bg-card p-5"
    >
      <h2 className="text-[16px] font-medium">
        {team.members.map((m) => m.display_name).join("、")}
      </h2>
      <p className="mt-1 text-[13px] text-ink-faint">
        过了{whenPhrase(team.expires_at, new Date())}，这个小队就不留着了。
      </p>

      <Lines
        title="为什么是这几个人"
        lines={team.why_these_people}
        empty="这一队没写出逐条的理由。没有理由的话，你可以先不选。"
      />

      {team.stability_note && (
        <p className="mt-4 rounded-[8px] bg-paper px-3 py-2 text-[14px] text-settled">
          {team.stability_note}
        </p>
      )}

      {team.left_to_humans.length > 0 && (
        <Lines
          title="这几件事留给你们自己定"
          note="这些是特意留给人的：有数据也不该由系统替你们定。"
          lines={team.left_to_humans}
        />
      )}

      {team.uncertainties.length > 0 && (
        <Lines
          title="这几处我还没底"
          lines={team.uncertainties}
          tone="text-pending"
        />
      )}

      <div className="mt-5 border-t border-line pt-4">
        {answered ? (
          <Answered mine={mine} status={status} team={team} onRevised={onRevised} />
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
            {/* 拒绝和接受同等可达：一步完成，不问为什么，不再确认一次。 */}
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
              这句话会原样带给他们。系统不替你解释，也不替你改条件。
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
            这一下没发出去。这个小队可能已经变了，重新看一眼再决定。
          </p>
        )}
      </div>
    </section>
  );
}

/** 我已经回过之后，这张卡说什么。 */
function Answered({
  mine,
  status,
  team,
  onRevised,
}: {
  mine: string | null;
  status: GateStatus | null;
  team: Team;
  onRevised: () => void;
}) {
  if (mine === DECLINED) {
    // 零负担：不追问理由，不解释后果，不给"再想想"。
    return <p className="text-[15px]">知道了。这次就到这里。</p>;
  }

  const verdict = status?.verdict;

  if (verdict === "open") {
    return <p className="text-[15px]">都点头了，这件事成了。</p>;
  }

  if (verdict === "needs_revision") {
    return (
      <div>
        <p className="text-[15px]">
          {mine === CONDITIONAL
            ? "你的话已经带过去了。这几个人的安排要改一版，改好会再来问你一次。"
            : "有人提了条件。这几个人的安排要改一版，改好会再来问你一次。"}
        </p>
        <button
          type="button"
          onClick={onRevised}
          className="mt-2 text-[14px] text-ink-soft underline underline-offset-4 hover:text-ink"
        >
          看看改完的那版
        </button>
      </div>
    );
  }

  if (verdict === "declined") {
    // 谁拒绝的不显示——拒绝的人不必向任何人解释。
    return <p className="text-[15px]">有人这次不参加，这一版先停下了。</p>;
  }

  if (verdict === "expired") {
    return <p className="text-[15px]">过了答复的时间，这次没赶上。</p>;
  }

  const names = new Map(team.members.map((m) => [m.principal_id, m.display_name]));
  const left = (status?.waiting_on ?? []).map((id) => names.get(id)).filter(Boolean);
  return (
    <p className="text-[15px]">
      {left.length > 0
        ? `还差${left.join("、")}点头。`
        : status === null
          ? "你的答复已经发出去了。"
          : "还差几个人点头。"}
    </p>
  );
}

/**
 * 一组依据。默认只显示结论，点一行才展开它是从哪来的。
 *
 * 每条都能追到来源，这一屏才谈得上可以被反驳；而可以被反驳，才是用户
 * 愿意相信它的原因。
 */
function Lines({
  title,
  note,
  lines,
  empty,
  tone,
}: {
  title: string;
  note?: string;
  lines: ProofLine[];
  empty?: string;
  tone?: string;
}) {
  return (
    <div className="mt-4">
      <h3 className="text-[13px] text-ink-soft">{title}</h3>
      {note && <p className="mt-0.5 text-[13px] text-ink-faint">{note}</p>}
      {lines.length === 0 ? (
        // 降级：后端这一段拿不到时，这一屏其余部分照常。
        empty && <p className="mt-1.5 text-[14px] text-ink-soft">{empty}</p>
      ) : (
        <ul className="mt-1.5 space-y-1.5">
          {lines.map((line) => (
            <Line key={line.text} line={line} tone={tone} />
          ))}
        </ul>
      )}
    </div>
  );
}

function Line({ line, tone }: { line: ProofLine; tone?: string }) {
  const [open, setOpen] = useState(false);
  const source = SOURCE_WORDS[line.source];
  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className={`text-left text-[15px] hover:text-accent ${tone ?? ""}`}
      >
        {line.text}
      </button>
      {open && (
        <p className="mt-0.5 text-[13px] text-ink-faint">
          {source ? `这条是${source}。` : "这条没写来源。"}
        </p>
      )}
    </li>
  );
}
