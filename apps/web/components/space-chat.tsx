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

export function SpaceChat({ spaceId }: { spaceId: string }) {
  const [chat, setChat] = useState<Chat | null>(null);
  const [failed, setFailed] = useState(false);
  /**
   * 话题卡指的那几件事分别叫什么。
   *
   * 单独一次取数：问不到名字只是少说一行，说话这件事照常。
   */
  const [about, setAbout] = useState<Map<string, About>>(new Map());
  /** 助手这会儿起不了话头。是一句平静的话，不是一次故障。 */
  const [nothingToAsk, setNothingToAsk] = useState(false);
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
    try {
      const raised = await askForTopics(spaceId);
      if (raised.length === 0) setNothingToAsk(true);
      else refresh();
    } catch {
      setNothingToAsk(true);
    } finally {
      setAsking(false);
    }
  }

  const me = currentPrincipal();

  return (
    <section aria-label="说说话" className="mt-10">
      <h2 className="text-[16px] font-medium">说说话</h2>
      <p className="mt-0.5 text-[13px] text-ink-soft">
        说过的话都留着，往回翻得到。这里聊出的结果不算定下来——每件事还得相关的人各自去点头。
      </p>

      {failed ? (
        <div role="alert" className="mt-4 rounded-[16px] border border-line bg-card p-5">
          <p className="text-[15px]">现在看不到这里说过的话。</p>
          <p className="mt-1 text-[13px] text-ink-soft">
            没连上的时候谁说过什么都不会丢，你回来再看也不迟。
          </p>
          <button
            type="button"
            onClick={() => void load()}
            className="mt-4 rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white"
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
          <Say
            spaceId={spaceId}
            label="说一句"
            placeholder="比如：我周三晚上都在，谁一起过一遍脚本"
            cta="说出去"
            onSaid={refresh}
          />
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1">
            <button
              type="button"
              disabled={asking}
              onClick={() => void startATopic()}
              className="rounded-[12px] border border-line px-3 py-1.5 text-[14px] disabled:opacity-35"
            >
              让助手起个话头
            </button>
            {nothingToAsk && (
              <span className="text-[13px] text-ink-faint">
                助手这会儿起不了话头。你先说一句，大家会接的。
              </span>
            )}
          </div>
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
      className="mt-4 rounded-[16px] border border-line bg-card p-5"
    >
      <p className="text-[16px]">还没人说话。</p>
      <p className="mt-2 text-[14px] text-ink-soft">
        第一句最难，之后就顺了。说你什么时候有空、你想先做哪块，都比「你好」有用。
      </p>
      <p className="mt-2 text-[13px] text-ink-faint">
        不知道从哪开口，可以让助手先挑一件还没定的事问一句。
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
 * 助手那几句走灰紫加虚线——和画布上它起草的东西同一条视觉通道。它说的话
 * 和人说的话长得一样，就没人分得清谁在替谁做决定。
 */
function Said({ message, me }: { message: Message; me: string }) {
  const who = whoSaidIt(message, me);
  return (
    <div
      className={`rounded-[16px] border p-4 ${
        message.is_agent
          ? "border-dashed border-draft bg-draft-soft"
          : "border-line bg-card"
      }`}
    >
      <p
        className={`text-[12px] ${message.is_agent ? "text-draft" : "text-ink-faint"}`}
      >
        {who}
      </p>
      <p className="mt-1 text-[15px] whitespace-pre-wrap">{message.text}</p>
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
      className="rounded-[16px] border border-dashed border-draft bg-draft-soft p-5"
    >
      <p className="text-[12px] text-draft">{whoSaidIt(topic, me)}</p>
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
        <ol aria-label="这张卡下面的回复" className="mt-4 space-y-2">
          {replies.map((reply) => (
            <li key={reply.id} className="rounded-[12px] border border-line bg-card p-3">
              <p className="text-[12px] text-ink-faint">{whoSaidIt(reply, me)}</p>
              <p className="mt-1 text-[15px] whitespace-pre-wrap">{reply.text}</p>
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
          className="mt-3 rounded-[12px] border border-line bg-card px-3 py-1.5 text-[14px]"
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
  onSaid,
  onGiveUp,
}: {
  spaceId: string;
  repliesTo?: string;
  label: string;
  placeholder: string;
  cta: string;
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

  return (
    <div className="mt-4">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={2}
        aria-label={label}
        placeholder={placeholder}
        className="w-full resize-none rounded-[8px] border border-line bg-card p-3 text-[15px] outline-none placeholder:text-ink-faint focus:border-accent"
      />
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={busy || text.trim().length === 0}
          onClick={() => void send()}
          className="rounded-[12px] bg-accent px-4 py-2 text-[14px] font-medium text-white disabled:opacity-35"
        >
          {cta}
        </button>
        {onGiveUp && (
          <button
            type="button"
            onClick={onGiveUp}
            className="text-[14px] text-ink-soft underline underline-offset-4 hover:text-ink"
          >
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
