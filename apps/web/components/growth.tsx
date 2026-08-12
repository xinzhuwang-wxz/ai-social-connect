"use client";

/**
 * 一件事长到哪一步了。
 *
 * ## 为什么用生命周期而不是进度条
 *
 * 一个百分比会立刻引出"凭什么是 40%"。而这件事本来就不是能精确到百分点
 * 的东西：定了时间没定地点，和定了地点没定时间，谁更"完成"？
 *
 * 生命周期的模糊性在这里是优点。它在**承诺**那一栏才是缺陷——所以按钮上
 * 永远是「我加入」「就这么办」这种朴素词，不是「一起种」（ADR 0009）。
 *
 * ## 每一档都说得出凭什么
 *
 * 说不出判据的进度条会被当成系统在评价你。所以后端连 `growth_why` 一起给：
 * 「人齐了，还没开始定事情」——它说的是事实，不是分数。
 *
 * ## 阶段不由聊天量决定
 *
 * 不变量 6。聊了两百条而一件事都没定，它就停在「发芽了」。
 * 这不是惩罚，是诚实。
 *
 * ## 植物只是 Progress Visualization
 *
 * PRD v2：植物不能挤占聊天面积，而且**必须配文字**——只看见一株植物在变，
 * 人不知道现在发生了什么。所以这里没有一个组件是"只有画"的：
 * `Growth` 一定带 word，`GrowthChip` 一定带 word，`GrowthPlant` 只在
 * 旁边就有 `Growth` 的地方出现。
 */

/**
 * 七步（PRD v2「植物成长 Progress」）。顺序就是判据的顺序：
 *
 * | 这一档 | 事件到了哪 | 凭什么是这一档 | 屏上说的 |
 * |---|---|---|---|
 * | `seed`     | 匹配中       | 已投递，还在等参与意向     | 还没发芽 |
 * | `sprout`   | 已成局／破冰 | 每个人都点了头             | 发芽了   |
 * | `seedling` | 刚开始做     | 有人认领了要做的事         | 长出幼苗 |
 * | `growing`  | 讨论中       | 真人在有效交流，事情在推进 | 在长了   |
 * | `bud`      | 已约好       | 行动约定全员确认           | 结了花苞 |
 * | `bloom`    | 已完成       | 全员确认真实行动完成       | 开花了   |
 * | `fruit`    | 再次发起     | 从这一段里结出了下一颗种子 | 结了果   |
 *
 * 右边那一列**在这个文件里一个字都没有**：它随 `growth_word` 从后端来
 * （ADR 0009，`domain/model/growth.py` 的 `WORDS`）。抄在这儿只是为了
 * 让改画的人知道自己画的那一株旁边会写什么，以那边为准。
 */
const ORDER = [
  "seed",
  "sprout",
  "seedling",
  "growing",
  "bud",
  "bloom",
  "fruit",
] as const;

type Stage = (typeof ORDER)[number];

/**
 * 七株。
 *
 * 填充的形状，不是细线图标——细线在小尺寸上看着像图表，而这里要的是
 * "有东西在长"。参照 Forest 那类应用的画法：软的圆角、两层色（茎深叶浅）、
 * 一株一株地长出来。
 *
 * 手画的，不引图标库：七个形状不值得一整包体积。
 *
 * ## 七株共用一条地平线，所以高度可比
 *
 * 地面永远是 `M6 28h20`。它不动，一档比一档高才是一件看得出来的事——
 * PRD 明写「禁止所有植物高度一致」。轮廓顶点（y 越小越高）：
 *
 * ```
 * seed 21.6 · sprout 17.5 · seedling 13.5 · growing 9.3
 * bud 6.8 · bloom 4.1 · fruit 1.4
 * ```
 *
 * 后三档的高度差收窄，是因为到那时候形状本身已经足够分得开
 * （花苞、开花、结果各是一个轮廓）；前四档只能靠长高来区分。
 * 这条阶梯有测试盯着，改形状时会被量出来。
 */
function Sprig({ stage, size = 22 }: { stage: string; size?: number }) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 32 32",
    fill: "none",
    "aria-hidden": true,
  };
  const stem = "currentColor";
  const leaf = { fill: "currentColor", opacity: 0.45 };
  const line = {
    stroke: stem,
    strokeWidth: 2.1,
    strokeLinecap: "round" as const,
    fill: "none",
  };
  // 土是一条线，不是一个盆——盆意味着被摆布。
  const soil = { ...line, opacity: 0.3 };

  switch (stage) {
    case "seed":
      // 一颗埋着的种子：它压在地平线上，一半在土里。
      return (
        <svg {...common}>
          <path d="M6 28h20" {...soil} />
          <ellipse cx="16" cy="26" rx="3.8" ry="4.4" fill="currentColor" opacity={0.55} />
        </svg>
      );
    case "sprout":
      // 冒头：一根短茎，一片叶。
      return (
        <svg {...common}>
          <path d="M6 28h20" {...soil} />
          <path d="M16 28v-7" {...line} />
          <path d="M16 22c0-2.7 2-4.5 4.6-4.5 0 2.7-2 4.5-4.6 4.5Z" {...leaf} />
        </svg>
      );
    case "seedling":
      // 长叶：两片，左右各一。有人认领了要做的事。
      return (
        <svg {...common}>
          <path d="M6 28h20" {...soil} />
          <path d="M16 28V17" {...line} />
          <path d="M16 18.5c0-3 2.2-5 5.1-5 0 3-2.2 5-5.1 5Z" {...leaf} />
          <path d="M16 23c0-2.7-2-4.5-4.7-4.5 0 2.7 2 4.5 4.7 4.5Z" {...leaf} />
        </svg>
      );
    case "growing":
      // 长高：茎明显拔上去，三片叶交错。事情在推进。
      return (
        <svg {...common}>
          <path d="M6 28h20" {...soil} />
          <path d="M16 28V12" {...line} />
          <path d="M16 13.5c0-2.5 1.9-4.2 4.6-4.2 0 2.5-1.9 4.2-4.6 4.2Z" {...leaf} />
          <path d="M16 18.6c0-2.8-2.1-4.7-5-4.7 0 2.8 2.1 4.7 5 4.7Z" {...leaf} />
          <path d="M16 23.6c0-2.8 2.1-4.7 5-4.7 0 2.8-2.1 4.7-5 4.7Z" {...leaf} />
        </svg>
      );
    case "bud":
      // 花苞：一个还合着的水滴。合着，因为还没发生。
      return (
        <svg {...common}>
          <path d="M6 28h20" {...soil} />
          <path d="M16 28V15" {...line} />
          <path d="M16 21c0-3-2.2-5-5.1-5 0 3 2.2 5 5.1 5Z" {...leaf} />
          <path d="M16 25.4c0-2.5 1.8-4.2 4.6-4.2 0 2.5-1.8 4.2-4.6 4.2Z" {...leaf} />
          <path
            d="M16 15.2c-2.5 0-4.1-2-4.1-4.5c0-2.5 1.8-3.9 4.1-3.9c2.3 0 4.1 1.4 4.1 3.9c0 2.5-1.6 4.5-4.1 4.5Z"
            fill="currentColor"
            opacity={0.8}
          />
        </svg>
      );
    case "bloom":
      // 开花：花瓣是四片圆，不是星形——星形看着像奖励，而这不是一个奖励。
      // 茎和叶和花苞那一档一样：开花就是同一株把苞打开了，不是换了一株。
      return (
        <svg {...common}>
          <path d="M6 28h20" {...soil} />
          <path d="M16 28V15" {...line} />
          <path d="M16 21c0-3-2.2-5-5.1-5 0 3 2.2 5 5.1 5Z" {...leaf} />
          <path d="M16 25.4c0-2.5 1.8-4.2 4.6-4.2 0 2.5-1.8 4.2-4.6 4.2Z" {...leaf} />
          <circle cx="16" cy="11" r="2.9" fill="currentColor" />
          <circle cx="16" cy="6.6" r="2.5" {...leaf} />
          <circle cx="16" cy="15.4" r="2.5" {...leaf} />
          <circle cx="11.6" cy="11" r="2.5" {...leaf} />
          <circle cx="20.4" cy="11" r="2.5" {...leaf} />
        </svg>
      );
    case "fruit":
      // 结果：最高的一株，顶上一颗实心的果，旁边地上落着一粒籽——
      // 那一粒和第一档的种子是同一个形状。它不是终点，是下一次的起点。
      return (
        <svg {...common}>
          <path d="M6 28h20" {...soil} />
          <path d="M16 28V8.6" {...line} />
          <path d="M16 16c0-3.1-2.3-5.2-5.3-5.2 0 3.1 2.3 5.2 5.3 5.2Z" {...leaf} />
          <path d="M16 21.6c0-3.1 2.3-5.2 5.3-5.2 0 3.1-2.3 5.2-5.3 5.2Z" {...leaf} />
          <circle cx="16" cy="5" r="3.6" fill="currentColor" />
          <ellipse cx="24.6" cy="26.4" rx="2.4" ry="2.8" {...leaf} />
        </svg>
      );
    default:
      // 认不出来的阶段：**画一块空地，不画一株植物。**
      // 猜一株出来等于替后端宣布这件事长到哪了；空地说的是实话——
      // 我们不知道。旁边的 word 照常来自后端，所以人还是看得懂。
      return (
        <svg {...common}>
          <path d="M6 28h20" {...soil} />
        </svg>
      );
  }
}

/**
 * 越往后越绿。三处例外：
 *
 * - **还没发芽是灰的**——它还没开始，不是它不好
 * - 开花换成"定下来了"那一档绿：这件事成了
 * - 结果是土色的——一颗熟了的果，也是下一颗还没被种下的种子
 *
 * 只用 token，不写死 hex：配色由 `globals.css` 统一换。
 */
const TONE: Record<Stage, string> = {
  seed: "text-ink-faint",
  sprout: "text-accent",
  seedling: "text-accent",
  growing: "text-accent",
  bud: "text-accent",
  bloom: "text-settled",
  fruit: "text-pending",
};

/** 大一株，给项目空间的看板用。它是那一屏的情绪中心。 */
export function GrowthPlant({ stage }: { stage: string }) {
  const tone = TONE[stage as Stage] ?? "text-ink-soft";
  return (
    <span
      className={
        "grid size-14 shrink-0 place-items-center rounded-full bg-accent-soft " + tone
      }
    >
      <Sprig stage={stage} size={32} />
    </span>
  );
}

/** 一行：它现在是什么，以及凭什么。 */
export function Growth({
  stage,
  word,
  why,
}: {
  stage: string;
  word: string;
  why?: string;
}) {
  const tone = TONE[stage as Stage] ?? "text-ink-soft";
  return (
    <div className="flex items-center gap-2">
      <span className={tone}>
        <Sprig stage={stage} />
      </span>
      <span className="text-[14px] font-medium">{word}</span>
      {why && <span className="text-[13px] text-ink-faint">· {why}</span>}
    </div>
  );
}

/**
 * 七档的那一条。走到哪一档，前面的都点亮。
 *
 * 认不出来的阶段一格都不点亮，读屏也说"还说不准"——**不是第 0 步**，
 * 那听着像倒退了一步。
 */
export function GrowthTrail({ stage }: { stage: string }) {
  const at = ORDER.indexOf(stage as Stage);
  return (
    <div
      className="flex items-center gap-1.5"
      role="img"
      aria-label={at < 0 ? "七步，现在这一步还说不准" : `七步里的第 ${at + 1} 步`}
    >
      {ORDER.map((s, i) => (
        <span
          key={s}
          className={
            "h-1 flex-1 rounded-full " +
            (i <= at ? "bg-accent" : "bg-line")
          }
        />
      ))}
    </div>
  );
}

/** 小一号的，给列表里一行一株用。 */
export function GrowthChip({ stage, word }: { stage: string; word: string }) {
  const tone = TONE[stage as Stage] ?? "text-ink-soft";
  return (
    <span
      className={
        "inline-flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-[12px] " +
        tone
      }
    >
      <Sprig stage={stage} size={13} />
      {word}
    </span>
  );
}
