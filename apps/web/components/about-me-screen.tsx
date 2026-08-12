"use client";

/**
 * 我这边：我能做什么、我想参与什么、我是什么样的人。
 *
 * ## 这一屏补的是产品里最大的一个洞
 *
 * 在它之前，一个真人**没有任何办法被别人找到**——漏斗按「我会什么」精确
 * 过滤，而没有任何地方能填这一项。真人对真人的匹配从来没成立过。
 *
 * ## 为什么「我能做的」和「我想参与的」要分成两栏
 *
 * 它们在系统里的分量不同：
 *
 * - **我能做的**是承诺。别人缺这一项的时候，你会被当成补上这个洞的人
 * - **我想参与的**只是意愿。它让你出现在候选里，但不会有人以为你会做
 *
 * 合成一栏，就只剩两种坏选择：要么勾了「剪辑」被当成剪辑师，要么不敢勾。
 * 分成两栏，一个想入门的人才敢说"我想参与"。
 *
 * ## 词从服务端来
 *
 * 词表是封闭的，前端硬编码一份的话，屏上迟早出现一个匹配零个人的词，
 * 而用户看不出任何异常——他只是永远配不到人。
 *
 * 界面文案不使用领域词汇（见 docs/07 语言映射表）。
 */

import { useEffect, useState } from "react";

import { api, type Profile, type Vocabulary } from "@/lib/api";

type Phase = "loading" | "ready" | "saving" | "saved" | "failed";

export function AboutMeScreen() {
  const [vocab, setVocab] = useState<Vocabulary | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  /** 名字是身份，放最上面。传空 = 这次不改，不是改成空的。 */
  const [displayName, setDisplayName] = useState("");
  const [skills, setSkills] = useState<string[]>([]);
  const [openTo, setOpenTo] = useState<string[]>([]);
  const [intro, setIntro] = useState("");
  const [zone, setZone] = useState<string>("");
  const [major, setMajor] = useState<string>("");
  const [unknown, setUnknown] = useState<string[]>([]);
  /** 打开这一屏时系统已经知道的。用来把话说对：是"带出来的"还是"你填的"。 */
  const [learned, setLearned] = useState<string[]>([]);

  useEffect(() => {
    Promise.all([api.vocabulary(), api.profile()])
      .then(([words, mine]: [Vocabulary, Profile]) => {
        setVocab(words);
        setDisplayName(mine.display_name);
        setSkills(mine.skills);
        setLearned(mine.skills);
        setOpenTo(mine.open_to);
        setIntro(mine.self_intro ?? "");
        setZone(mine.zone ?? "");
        setMajor(mine.major ?? "");
        setPhase("ready");
      })
      .catch(() => setPhase("failed"));
  }, []);

  async function save() {
    setPhase("saving");
    try {
      const saved = await api.saveProfile({
        // 传空字符串时给 null——这次不改名字，不是改成空的。
        display_name: displayName.trim() || null,
        skills,
        open_to: openTo,
        self_intro: intro.trim() || null,
        zone: zone || null,
        major: major || null,
      });
      // 服务端归一之后的才是真的存下来的东西。回填它，
      // 否则屏上显示「会剪片子的」而库里是「剪辑」，下一次打开又变了。
      setDisplayName(saved.display_name);
      setSkills(saved.skills);
      setOpenTo(saved.open_to);
      setUnknown(saved.not_recognised ?? []);
      setPhase("saved");
    } catch {
      setPhase("failed");
    }
  }

  if (phase === "loading") {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10">
        <div className="space-y-3" aria-label="加载中">
          <div className="h-6 w-40 animate-pulse rounded bg-line" />
          <div className="h-24 animate-pulse rounded bg-line" />
        </div>
      </main>
    );
  }

  if (!vocab) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10">
        <p className="text-[15px]">现在打不开这一页。</p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="mt-3 rounded-[12px] border border-line px-4 py-2 text-[14px]"
        >
          再试一次
        </button>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-10">
      <header className="mb-8">
        <h1 className="text-[22px] font-semibold tracking-tight">我这边</h1>
        {/* **不是一张必须填的表。** 你说过的话、做完的事会自己记到这里来：
            发需求时写的「我能出」，以及你点过头的那几句记录。
            这一屏是给你改和删的地方，不是入门的第一道门槛。 */}
        <p className="mt-2 text-[15px] text-ink-soft">
          {learned.length > 0
            ? "下面这些是你说过、做过的事情里带出来的。不对就改，不想要就点掉。"
            : "这里可以不填。你说一件事、做完一件事，它自己会记到这来——现在先看看有什么。"}
        </p>
      </header>

      {/* 名字是身份，放最上面——改名字和改技能是两件不同的事，
          合在一起会让人觉得名字只是表单里的一项。 */}
      <section className="mt-8">
        <h2 className="text-[16px] font-medium">我叫</h2>
        <p className="mt-1 text-[13px] text-ink-soft">
          留空不会清掉你的名字，只是这次不改。
        </p>
        <input
          type="text"
          aria-label="我叫"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          maxLength={20}
          placeholder="你的名字"
          className="mt-2 w-full rounded-[12px] border border-line bg-card px-3 py-2.5 text-[16px] outline-none focus:border-accent"
        />
      </section>

      <Picker
        title="我能做的"
        hint="别人缺这一项的时候，你会被当成能补上的那个人。你在需求里写过的「我能出」、以及你点过头的记录，都会自己出现在这里。"
        words={vocab.skills}
        chosen={skills}
        onToggle={(w) => setSkills(toggle(skills, w))}
      />

      <Picker
        title="我想参与的"
        hint="不代表你会做。它只是让你出现在这类事的名单里——想入门的人填这一栏。"
        words={vocab.skills}
        chosen={openTo}
        onToggle={(w) => setOpenTo(toggle(openTo, w))}
      />

      <section className="mt-8">
        <h2 className="text-[16px] font-medium">我是什么样的人</h2>
        <p className="mt-1 text-[13px] text-ink-soft">
          上面那些词装不下的，写在这里。「文风比较冲」「喜欢做完再说」——
          这些话找人的时候真的会被用到。
        </p>
        <textarea
          aria-label="我是什么样的人"
          value={intro}
          onChange={(e) => setIntro(e.target.value)}
          rows={3}
          maxLength={500}
          placeholder="比如：拍东西比较野，不太爱按分镜来，做完了会自己剪一版"
          className="mt-2 w-full rounded-[12px] border border-line bg-card p-3 text-[15px]"
        />
      </section>

      <section className="mt-8">
        <h2 className="text-[16px] font-medium">我是哪个院系的</h2>
        <p className="mt-1 text-[13px] text-ink-soft">
          {/* 它不是给人看的标签，是配队时用来凑不同背景的人的。 */}
          配队时会拿它来凑不同背景的人。不填也行，只是少一条把你和别的
          院系放到一起的理由。
        </p>
        <div role="radiogroup" aria-label="我是哪个院系的" className="mt-2 flex flex-wrap gap-2">
          <Chip label="不说" on={major === ""} onClick={() => setMajor("")} />
          {vocab.majors.map((m) => (
            <Chip key={m} label={m} on={major === m} onClick={() => setMajor(m)} />
          ))}
        </div>
      </section>

      <section className="mt-8">
        <h2 className="text-[16px] font-medium">我常在哪</h2>
        <p className="mt-1 text-[13px] text-ink-soft">
          不填就是哪个校区都行——不填不会让你被排除。
        </p>
        <div role="radiogroup" aria-label="我常在哪" className="mt-2 flex flex-wrap gap-2">
          <Chip label="都行" on={zone === ""} onClick={() => setZone("")} />
          {vocab.zones.map((z) => (
            <Chip key={z} label={z} on={zone === z} onClick={() => setZone(z)} />
          ))}
        </div>
      </section>

      {/* **保存跟着走，不是压在最底下。**
          这一屏在 390px 宽的手机上有三千多像素高：勾了两个词想存一下，
          得先划过院系、校区、那段自述才够得到按钮。而这一屏正是决定
          "别人能不能找到你"的那一屏——它的保存不该需要找。

          常驻在底部标签栏上方，一直看得见。 */}
      <div className="sticky bottom-[calc(72px+env(safe-area-inset-bottom))] z-20 -mx-4 mt-8 border-t border-line bg-paper/95 px-4 py-3 backdrop-blur-md sm:bottom-4 sm:mx-0 sm:rounded-[16px] sm:border">
        <button
          type="button"
          onClick={save}
          disabled={phase === "saving"}
          className="inline-flex min-h-[48px] w-full items-center justify-center rounded-[16px] bg-accent px-5 text-[15px] font-semibold text-paper disabled:opacity-50 active:opacity-80"
        >
          {phase === "saving" ? "正在存…" : "存下来"}
        </button>
        {phase === "saved" && (
          <p className="mt-2 text-center text-[14px] text-settled">
            存好了，现在别人找得到你。
          </p>
        )}
        {phase === "failed" && (
          <p role="alert" className="mt-2 text-center text-[14px] text-clash">
            没能存下来，再点一次试试——你填的东西都还在。
          </p>
        )}
      </div>

      {unknown.length > 0 && (
        // 静默丢掉的代价是他永远不知道为什么没人找他。
        <p role="status" className="mt-4 text-[14px] text-ink-soft">
          「{unknown.join("」「")}」这几个词我没认出来，它们不会用来精确找人。
          把它们写进上面那段话里，找人的时候一样算数。
        </p>
      )}
    </main>
  );
}

function toggle(list: string[], word: string): string[] {
  return list.includes(word) ? list.filter((w) => w !== word) : [...list, word];
}

function Picker({
  title,
  hint,
  words,
  chosen,
  onToggle,
}: {
  title: string;
  hint: string;
  words: string[];
  chosen: string[];
  onToggle: (word: string) => void;
}) {
  return (
    <section aria-label={title} className="mt-8">
      <h2 className="text-[16px] font-medium">{title}</h2>
      <p className="mt-1 text-[13px] text-ink-soft">{hint}</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {words.map((word) => (
          <Chip
            key={word}
            label={word}
            on={chosen.includes(word)}
            onClick={() => onToggle(word)}
          />
        ))}
      </div>
    </section>
  );
}

function Chip({
  label,
  on,
  onClick,
}: {
  label: string;
  on: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={on}
      onClick={onClick}
      className={
        "rounded-full border px-3 py-1.5 text-[14px] transition-colors " +
        (on
          ? "border-accent bg-accent-soft text-accent"
          : "border-line text-ink-soft hover:text-ink")
      }
    >
      {label}
    </button>
  );
}
