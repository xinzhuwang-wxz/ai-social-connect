"use client";

/**
 * 项目空间里的那段群聊。
 *
 * 大家组完队被拉进来，这里是他们真正开始认识彼此的地方。六条产品判断决定了
 * 它长成现在这样：
 *
 * 1. **助手的话一眼可辨。** 每一句都写着是谁说的，助手那几句还走灰紫加虚线
 *    这条专用通道——和画布上它起草的东西同一个视觉信号。分不清谁说的，
 *    「AI 起草、人类决定」就只是一句话。
 * 2. **话题卡不是普通消息，是一张卡。** 它自己占一块，点开在下面回复，
 *    回复只挂在这张卡下面，不冲散主线。
 * 3. **助手发话题是为了把该聊的尽快聊清楚，不是为了活跃气氛。** 所以每张卡
 *    都写着它关于哪件还没定的事——看得出它不是在找话说。名字要去画布那边
 *    问；问不到就少说一行，不把一串编号糊到脸上。
 * 4. **没人回的那张不藏，也不置顶。** 它照样待在它当时的位置上。没人接说明
 *    这张卡问得不对，或者这件事大家不在意；把它顶上去只会让更多人学会
 *    略过助手说的话。
 * 5. **这里定不了任何事。** 一张卡下面聊出了共识，那件事也还没定——界面上
 *    必须看得出「聊完还得各自去点头」，不能让人聊完就以为完了。这一条错了，
 *    「相关的人一个不少地点过头才算定下来」当场作废。
 * 6. **整条记录都在，不截断。** 说过的话往回翻得到；哪天说的也标出来，
 *    不然一条长记录翻起来没有落点。
 *
 * ## 手机上还多三条
 *
 * 7. **我说的靠右，别人说的靠左。** 一条从上到下齐宽的记录，在手机上
 *    每读一句都要先去看一眼作者名才知道是谁——左右一分，这一步就省了。
 *    助手**永远靠左**：右边那一侧只属于本人。
 * 8. **输入框吸底。** 一条长记录往回翻两屏之后，输入框就被翻没了；
 *    要说话得先滑回来，而那一路上人就把想说的话忘了。
 * 9. **点击区不小于 44px。** 走在路上单手打字的人点不中 36px 的按钮。
 *
 * 界面文案不使用领域词汇（见 docs/07 语言映射表）。
 */

import { useCallback, useEffect, useState } from "react";

import {
  askForTopics,
  dayPhrase,
  fetchChat,
  nobodySpokeYet,
  say,
  timeline,
  whatTheyreAbout,
  type About,
  type Chat,
  type Line,
  type Message,
  type NewMessage,
} from "@/lib/chat";
import { currentPrincipal } from "@/lib/session";
import { fetchSpace } from "@/lib/space";

/**
 * 这句话是谁说的。
 *
 * 这一屏拿不到这个组里的人叫什么（只有编号，没有名字），所以别人只能说
 * 「组里的人」。少说一句，好过说一句没人看得懂的话。
 */
function whoSaidIt(message: Message, me: string): string {
  if (message.is_agent) return "助手";
  return message.author_id === me ? "我" : "组里的人";
}

/** 这句话是不是我说的。助手说的**永远不算**——右边那一侧只属于本人。 */
function isMine(message: Message, me: string): boolean {
  return !message.is_agent && message.author_id === me;
}

/** 手机上的点击区。规范给的按钮高度是 44–52px。 */
const PRIMARY =
  "inline-flex min-h-[48px] items-center justify-center rounded-[16px] bg-accent px-5 text-[15px] font-medium text-paper disabled:opacity-35";
const SECONDARY =
  "inline-flex min-h-[44px] items-center justify-center rounded-[16px] border border-line bg-card px-4 text-[15px] disabled:opacity-35";
/** 只有文字的那一类。下划线常在，不靠 hover——手机上没有 hover。 */
const QUIET =
  "inline-flex min-h-[44px] items-center text-[15px] text-ink-soft underline underline-offset-4 hover:text-ink active:text-ink";

export function SpaceChat({ spaceId }: { spaceId: string }) {
  const [chat, setChat] = useState<Chat | null>(null);
  const [failed, setFailed] = useState(false);
  /**
   * 话题卡指的那几件事分别叫什么。
   *
   * 单独一次取数：问不到名字只是少说一行，说话这件事照常。
   */
  const [about, setAbout] = useState<Map<string, About>>(new Map());
  /** 助手这会儿说不出什么。是一句平静的话，不是一次故障。 */
  const [nothingToAsk, setNothingToAsk] = useState(false);
  /** 联系不上助手——要说清，不能静默。和「助手没东西说」是两件不同的事。 */
  const [topicsFailed, setTopicsFailed] = useState(false);
  /**
   * 助手刚发了个话头。
   *
   * 话头发出之后要在屏上说清它还不算数——让人聊出结果就以为事情定了，
   * 是这一段最容易翻的车。同时给「继续聊聊」这条出路：助手发的话头
   * 不该变成必须回答的作业。
   */
  const [topicsRaised, setTopicsRaised] = useState(false);
  const [asking, setAsking] = useState(false);

  const load = useCallback(async () => {
    setFailed(false);
    setChat(null);
    let loaded: Chat;
    try {
      loaded = await fetchChat(spaceId);
    } catch {
      setFailed(true);
      return;
    }
    setChat(loaded);
    fetchSpace(spaceId).then(
      (space) => setAbout(whatTheyreAbout(space)),
      () => setAbout(new Map()),
    );
  }, [spaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  /** 说完一句之后重新看一眼。不清空记录，免得每说一句就闪一遍骨架。 */
  const refresh = useCallback(() => {
    fetchChat(spaceId).then(setChat, () => {});
  }, [spaceId]);

  async function startATopic() {
    setAsking(true);
    setNothingToAsk(false);
    setTopicsFailed(false);
    setTopicsRaised(false);
    try {
      const raised = await askForTopics(spaceId);
      if (raised.length === 0) {
        // 助手暂时没有要问的事——不是故障，是它这会儿说不出什么。
        setNothingToAsk(true);
      } else {
        setTopicsRaised(true);
        refresh();
      }
    } catch {
      // 联系不上和「没东西说」是两件事：措辞不同，用户下一步也不同。
      setTopicsFailed(true);
    } finally {
      setAsking(false);
    }
  }

  const me = currentPrincipal();

  return (
    <section aria-label="说说话" className="mt-8 sm:mt-10">
      <h2 className="text-[18px] font-semibold">说说话</h2>
      <p className="mt-0.5 text-[13px] text-ink-soft">
        说过的话都留着，往回翻得到。这里聊出的结果不算定下来——每件事还得相关的人各自去点头。
      </p>

      {failed ? (
        <div
          role="alert"
          className="mt-4 rounded-[16px] border border-line bg-card p-4 sm:p-5"
        >
          <p className="text-[16px]">现在看不到这里说过的话。</p>
          <p className="mt-1 text-[14px] text-ink-soft">
            没连上的时候谁说过什么都不会丢，你回来再看也不迟。
          </p>
          <button
            type="button"
            onClick={() => void load()}
            className={PRIMARY + " mt-4 w-full sm:w-auto"}
          >
            再试一次
          </button>
        </div>
      ) : chat === null ? (
        <div className="mt-4 space-y-3" aria-label="加载中">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-12 animate-pulse rounded-[16px] bg-line" />
          ))}
        </div>
      ) : nobodySpokeYet(chat) ? (
        <FirstWord />
      ) : (
        <Record lines={timeline(chat)} me={me} about={about} spaceId={spaceId} onSaid={refresh} />
      )}

      {!failed && chat !== null && (
        <>
          {/* 「推进一下」排在输入框**上面**：吸底的那一格只留给
              "现在就说一句"，别的东西挤进去就把它顶离了拇指。 */}
          <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1">
            <button
              type="button"
              disabled={asking}
              onClick={() => void startATopic()}
              className={SECONDARY}
            >
              推进一下
            </button>
            {nothingToAsk && (
              <span className="text-[13px] text-ink-faint">
                助手这会儿说不出什么。你先说一句，大家会接的。
              </span>
            )}
          </div>
          {topicsFailed && (
            <p role="alert" className="mt-2 text-[13px] text-clash">
              现在联系不上助手，稍后再试一次。
            </p>
          )}
          {topicsRaised && (
            // 说清话头还不算数，同时给「继续聊聊」这条出路。
            // 用户不应该觉得被迫必须回复助手问的那一件事。
            <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[10px] border border-draft bg-draft-soft px-4 py-3">
              <span className="text-[13px] text-draft">
                助手发了个话头。聊出来的结果不算定下来——还得大家各自去点头。
              </span>
              <button
                type="button"
                onClick={() => setTopicsRaised(false)}
                className={QUIET}
              >
                继续聊聊
              </button>
            </div>
          )}
          <Say
            spaceId={spaceId}
            label="说一句"
            placeholder="比如：我周三晚上都在，谁一起过一遍脚本"
            cta="说出去"
            docked
            onSaid={refresh}
          />
        </>
      )}
    </section>
  );
}

/**
 * 一句话都还没说的时候。
 *
 * 这里最贵的就是刚被拉进来那几分钟，而一个空白框会让人默认别人先说。所以
 * 先给一句让人愿意开口的话，再给一个具体的例子——「随便说点什么」等于
 * 什么都没说。
 */
function FirstWord() {
  return (
    <div
      aria-label="还没人说话"
      className="mt-4 rounded-[16px] border border-line bg-card p-4 sm:p-5"
    >
      <p className="text-[16px]">还没人说话。</p>
      <p className="mt-2 text-[14px] text-ink-soft">
        第一句最难，之后就顺了。说你什么时候有空、你想先做哪块，都比「你好」有用。
      </p>
      <p className="mt-2 text-[13px] text-ink-faint">
        不知道从哪开口，可以点「推进一下」，让助手先挑一件还没定的事问一句。
      </p>
    </div>
  );
}

/** 说过的话，从上到下，一句不少。 */
function Record({
  lines,
  me,
  about,
  spaceId,
  onSaid,
}: {
  lines: Line[];
  me: string;
  about: Map<string, About>;
  spaceId: string;
  onSaid: () => void;
}) {
  const now = new Date();
  let lastDay = "";

  return (
    <ol aria-label="说过的话" className="mt-4 space-y-3">
      {lines.map((line) => {
        const day = dayPhrase(line.at, now);
        const fresh = day !== lastDay;
        lastDay = day;
        return (
          <li key={line.id}>
            {fresh && (
              <p className="mb-3 text-center text-[12px] text-ink-faint">{day}</p>
            )}
            {line.kind === "said" ? (
              <Said message={line.message} me={me} />
            ) : (
              <TopicCard
                topic={line.topic}
                replies={line.replies}
                answered={line.answered}
                about={line.topic.about_item_id ? about.get(line.topic.about_item_id) : undefined}
                me={me}
                spaceId={spaceId}
                onSaid={onSaid}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}

/**
 * 一句话。
 *
 * 三条视觉通道，一眼分得开：
 *
 * - **我说的靠右**，浅绿底。右边那一侧只属于本人
 * - **别人说的靠左**，暖白底
 * - **助手说的靠左**，还多一圈虚线——和画布上它起草的东西同一条通道。
 *   它说的话和人说的话长得一样，就没人分得清谁在替谁做决定
 *
 * 每一句照旧写着是谁说的。左右只是让人不用读那一行就先知道个大概，
 * 不是拿来替代它——两个人都在左边的时候，名字仍然是唯一的区分。
 */
function Said({
  message,
  me,
  tight,
}: {
  message: Message;
  me: string;
  /** 挂在话题卡下面的那些回复。窄一档，免得卡里再套一个同样大的块。 */
  tight?: boolean;
}) {
  const mine = isMine(message, me);
  const skin = message.is_agent
    ? "rounded-bl-[10px] border-dashed border-draft bg-draft-soft"
    : mine
      ? "rounded-br-[10px] border-accent-soft bg-accent-soft"
      : "rounded-bl-[10px] border-line bg-card";
  const nameTone = message.is_agent
    ? "font-medium text-draft"
    : mine
      ? "text-ink-soft"
      : "text-ink-faint";

  return (
    <div className={"flex " + (mine ? "justify-end" : "justify-start")}>
      <div
        className={`min-w-0 max-w-[85%] rounded-[16px] border ${
          tight ? "px-3 py-2.5" : "px-4 py-3"
        } ${skin}`}
      >
        <p className={"text-[12px] " + nameTone}>{whoSaidIt(message, me)}</p>
        <p className="mt-1 text-[15px] break-words whitespace-pre-wrap">
          {message.text}
        </p>
      </div>
    </div>
  );
}

/**
 * 一张话题卡。
 *
 * 它不是一条消息：它自己是一块，写清关于哪件还没定的事，回复挂在它下面。
 * 「聊出结果也不算定下来」就写在卡上，而不是写在某份文档里——一屏聊得热闹、
 * 事却一件没定，是这一段最容易翻的车。
 */
function TopicCard({
  topic,
  replies,
  answered,
  about,
  me,
  spaceId,
  onSaid,
}: {
  topic: Message;
  replies: Message[];
  answered: boolean;
  about: About | undefined;
  me: string;
  spaceId: string;
  onSaid: () => void;
}) {
  const [replying, setReplying] = useState(false);

  return (
    <article
      aria-label={topic.text}
      className="rounded-[16px] border border-dashed border-draft bg-draft-soft p-4 sm:p-5"
    >
      <p className="text-[12px] font-medium text-draft">{whoSaidIt(topic, me)}</p>
      <p className="mt-1 text-[16px]">{topic.text}</p>

      {about ? (
        <>
          <p className="mt-2 text-[13px] text-ink-soft">关于：{about.title}</p>
          <p className="mt-1 text-[13px] text-pending">
            {about.settled
              ? "这件事已经定下来了。"
              : "这件事还没定。在这儿聊出结果也不算定下来——还得相关的人各自去点头。"}
          </p>
        </>
      ) : (
        <p className="mt-2 text-[13px] text-pending">
          在这儿聊出结果也不算定下来——还得相关的人各自去点头。
        </p>
      )}

      {replies.length > 0 && (
        // 卡下面的回复也左右分明：这一段常常正是几个人来回接话的地方。
        <ol aria-label="这张卡下面的回复" className="mt-4 space-y-2">
          {replies.map((reply) => (
            <li key={reply.id}>
              <Said message={reply} me={me} tight />
            </li>
          ))}
        </ol>
      )}

      {!answered && (
        <p className="mt-3 text-[13px] text-ink-faint">
          还没人接这个话。可能问得不巧，也可能这件事大家眼下不着急。
        </p>
      )}

      {replying ? (
        <Say
          spaceId={spaceId}
          repliesTo={topic.id}
          label="回一句"
          placeholder="就说这一件事"
          cta="回在这张卡下面"
          onSaid={() => {
            setReplying(false);
            onSaid();
          }}
          onGiveUp={() => setReplying(false)}
        />
      ) : (
        <button
          type="button"
          onClick={() => setReplying(true)}
          className={SECONDARY + " mt-3"}
        >
          回一句
        </button>
      )}
    </article>
  );
}

/**
 * 说一句，或者回在某张卡下面。
 *
 * **发不出去的时候那句话留在框里。** 一条打了半天的消息因为一次超时就没了，
 * 用户下次就不敢在这儿说长话了——而这一段值钱的正是那些长话。
 */
function Say({
  spaceId,
  repliesTo,
  label,
  placeholder,
  cta,
  docked,
  onSaid,
  onGiveUp,
}: {
  spaceId: string;
  repliesTo?: string;
  label: string;
  placeholder: string;
  cta: string;
  /**
   * 主输入框吸在底上。
   *
   * 挂在话题卡下面的那个不吸底——一屏上两个吸底的框，第二个只会挡住第一个。
   *
   * 注：这里吸的是**视口底**。哪天这一屏被放进带固定底栏的页面里，
   * 要么给它一个偏移，要么把底栏让出来——底栏会压在它上面。
   */
  docked?: boolean;
  onSaid: () => void;
  onGiveUp?: () => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function send() {
    setBusy(true);
    setFailed(false);
    const body: NewMessage = repliesTo
      ? { text: text.trim(), replies_to: repliesTo }
      : { text: text.trim() };
    try {
      await say(spaceId, body);
      setText("");
      onSaid();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  // 吸底的那一格里，框和按钮**并排**不上下摞：摞起来要占掉小半屏，
  // 而这是一块永远盖在记录上面的东西。
  const field = (
    // **16px 不是审美，是功能**：iOS Safari 对更小的输入框会在聚焦时
    // 自动放大整页，而且缩不回去——用户会以为页面坏了。
    <textarea
      value={text}
      onChange={(e) => setText(e.target.value)}
      rows={2}
      aria-label={label}
      placeholder={placeholder}
      className="min-h-[48px] w-full resize-none rounded-[10px] border border-line bg-card px-3 py-3 text-[16px] outline-none placeholder:text-ink-faint focus:border-accent"
    />
  );

  const sendButton = (
    <button
      type="button"
      disabled={busy || text.trim().length === 0}
      onClick={() => void send()}
      className={PRIMARY + (docked ? " shrink-0" : "")}
    >
      {cta}
    </button>
  );

  if (docked) {
    return (
      <div className="sticky bottom-0 z-10 mt-4 rounded-[16px] border border-line bg-paper/95 p-2 backdrop-blur-md">
        <div className="flex items-end gap-2">
          {field}
          {sendButton}
        </div>
        {failed && (
          <p role="alert" className="mt-2 px-1 text-[13px] text-clash">
            这句话没发出去，还在框里。再点一次试试。
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="mt-4">
      {field}
      <div className="mt-2 flex flex-wrap items-center gap-3">
        {sendButton}
        {onGiveUp && (
          <button type="button" onClick={onGiveUp} className={QUIET}>
            先不回了
          </button>
        )}
      </div>
      {failed && (
        <p role="alert" className="mt-2 text-[13px] text-clash">
          这句话没发出去，还在框里。再点一次试试。
        </p>
      )}
    </div>
  );
}
