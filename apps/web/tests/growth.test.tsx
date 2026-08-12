/**
 * 七档生长。
 *
 * 断言的是**画对了**而不是**画得出**。这里最要紧的一条是高度：PRD 明写
 * 「禁止所有植物高度一致」，而"七株看着都差不多"是一个只有量一量才能
 * 发现的问题——渲染是成功的，快照是绿的，人一眼看过去却分不出前后。
 * 所以这份测试把每一株的轮廓顶点从 SVG 里量出来，一档一档比。
 *
 * 另外两条是产品判断，不是实现细节：一是**不出现百分比**（一个数字会立刻
 * 引出"凭什么是 40%"），二是**认不出来的阶段不许假装**。
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Growth, GrowthChip, GrowthPlant, GrowthTrail } from "@/components/growth";

/**
 * 七档，从种子到结果。数组顺序就是它们该长高的顺序。
 *
 * word 和 why 照抄后端现在给的那几句（`domain/model/growth.py`）——它们是
 * 属性，不是这个组件的资产，所以换词不会让这份测试变红；照抄只是为了
 * 让用例长得像真的那一屏。
 */
const STAGES = [
  { stage: "seed", word: "还没发芽", why: "投出去了，等人答复" },
  { stage: "sprout", word: "发芽了", why: "人齐了，还没开始定事情" },
  { stage: "seedling", word: "长出幼苗", why: "有人开始认领要做的事了" },
  { stage: "growing", word: "在长了", why: "事情在往前走" },
  { stage: "bud", word: "结了花苞", why: "时间地点分工都定了，等那天到" },
  { stage: "bloom", word: "开花了", why: "做完了，东西留下来了" },
  { stage: "fruit", word: "结了果", why: "从这件事又长出了下一件" },
] as const;

/** 后端哪天多给一档、或者拼错一个字，前端拿到的就是这种东西。 */
const UNKNOWN = "compost";

/**
 * 把一段 path 走一遍，收集它落到过的所有 y。
 *
 * 曲线只取控制点和端点：叶尖正好落在端点上，所以这个近似不会把一株矮的
 * 算成高的。只认这七株用到的命令——将来有人写了别的命令，这里宁可炸掉，
 * 也不要悄悄少量一段而把高度算错。
 */
function pathYs(d: string): number[] {
  const tokens = d.match(/[a-zA-Z]|-?\d*\.?\d+/g) ?? [];
  const ys: number[] = [];
  let x = 0;
  let y = 0;
  let cmd = "";
  let i = 0;
  const next = () => Number(tokens[i++] ?? 0);

  while (i < tokens.length) {
    const head = tokens[i] ?? "";
    if (/[a-zA-Z]/.test(head)) {
      cmd = head;
      i += 1;
    }
    const rel = cmd === cmd.toLowerCase();
    switch (cmd.toUpperCase()) {
      case "M":
      case "L": {
        const dx = next();
        const dy = next();
        x = rel ? x + dx : dx;
        y = rel ? y + dy : dy;
        break;
      }
      case "H": {
        const dx = next();
        x = rel ? x + dx : dx;
        break;
      }
      case "V": {
        const dy = next();
        y = rel ? y + dy : dy;
        break;
      }
      case "C": {
        const a = [next(), next(), next(), next(), next(), next()].map((n) => n ?? 0);
        ys.push(rel ? y + (a[1] ?? 0) : (a[1] ?? 0));
        ys.push(rel ? y + (a[3] ?? 0) : (a[3] ?? 0));
        const ex = a[4] ?? 0;
        const ey = a[5] ?? 0;
        x = rel ? x + ex : ex;
        y = rel ? y + ey : ey;
        break;
      }
      case "Z":
        break;
      default:
        throw new Error(`这份测试还不认识 path 命令「${cmd}」，量出来的高度不作数`);
    }
    ys.push(y);
  }
  return ys;
}

const attr = (el: Element, name: string) => Number(el.getAttribute(name) ?? 0);

/** 一株植物的轮廓顶点（viewBox 坐标，y 越小站得越高）。 */
function topOf(svg: SVGElement): number {
  const ys: number[] = [];
  svg.querySelectorAll("path").forEach((p) => ys.push(...pathYs(p.getAttribute("d") ?? "")));
  svg.querySelectorAll("circle").forEach((c) => ys.push(attr(c, "cy") - attr(c, "r")));
  svg.querySelectorAll("ellipse").forEach((e) => ys.push(attr(e, "cy") - attr(e, "ry")));
  return Math.min(...ys);
}

function plantOf(stage: string): SVGSVGElement {
  const { container } = render(<GrowthPlant stage={stage} />);
  const svg = container.querySelector("svg");
  if (!svg) throw new Error(`「${stage}」这一档什么都没画出来`);
  return svg;
}

describe("七档都在", () => {
  it("每一档都画得出一株，并且说得出它是什么、凭什么", () => {
    for (const { stage, word, why } of STAGES) {
      const { container } = render(<Growth stage={stage} word={word} why={why} />);

      // 植物只是 Progress Visualization：没有那句话，人只看见一个图形在变。
      expect(container).toHaveTextContent(word);
      expect(container).toHaveTextContent(why);
      expect(container.querySelector("svg")).not.toBeNull();
    }
  });

  it("七株不是同一张图：形状各不相同", () => {
    const drawn = STAGES.map(({ stage }) => plantOf(stage).innerHTML);

    expect(new Set(drawn).size).toBe(STAGES.length);
  });

  it("植物是填充的形状，不是细线图标", () => {
    // 细线在 13px 的列表行里看着像图表，而这里要的是"有东西在长"。
    for (const { stage } of STAGES) {
      const filled = plantOf(stage).querySelectorAll('[fill="currentColor"]');
      expect(filled.length).toBeGreaterThan(0);
    }
  });
});

describe("越往后越高", () => {
  it("七株站在同一条地平线上——不然比高度没有意义", () => {
    for (const { stage } of STAGES) {
      const ground = [...plantOf(stage).querySelectorAll("path")].map((p) =>
        p.getAttribute("d"),
      );
      expect(ground).toContain("M6 28h20");
    }
  });

  it("一档比一档高，而且高得看得出来", () => {
    // PRD：「禁止所有植物高度一致。」
    // 顶点 y 越小站得越高，所以这一串必须是严格递减的。
    const tops = STAGES.map(({ stage }) => topOf(plantOf(stage)));

    for (let i = 1; i < tops.length; i += 1) {
      const prev = tops[i - 1] ?? 0;
      const now = tops[i] ?? 0;
      const grew = prev - now;
      // 2 个 viewBox 单位 ≈ 整幅画的 6%。再小就只是抖了一下。
      expect(
        grew,
        `${STAGES[i]?.stage} 只比 ${STAGES[i - 1]?.stage} 高了 ${grew}`,
      ).toBeGreaterThanOrEqual(2);
    }
  });

  it("种子和结果差出大半幅画", () => {
    const first = topOf(plantOf("seed"));
    const last = topOf(plantOf("fruit"));

    expect(first - last).toBeGreaterThanOrEqual(18);
  });
});

describe("那一条走到哪", () => {
  it("走到第 N 档，前 N 格点亮，后面的不亮", () => {
    STAGES.forEach(({ stage }, index) => {
      const { container } = render(<GrowthTrail stage={stage} />);
      const cells = [...container.querySelectorAll("span")];

      expect(cells).toHaveLength(7);
      expect(cells.filter((c) => c.className.includes("bg-accent"))).toHaveLength(index + 1);
      expect(cells.filter((c) => c.className.includes("bg-line"))).toHaveLength(6 - index);
    });
  });

  it("读屏听到的也是七步里的第几步", () => {
    render(<GrowthTrail stage="bud" />);

    expect(screen.getByRole("img", { name: "七步里的第 5 步" })).toBeVisible();
  });
});

describe("认不出来的阶段", () => {
  it("不崩，也照常把后端给的说法显示出来", () => {
    const { container } = render(
      <Growth stage={UNKNOWN} word="在长着" why="说不太清到哪一步了" />,
    );

    expect(container).toHaveTextContent("在长着");
    expect(container).toHaveTextContent("说不太清到哪一步了");
    // 白屏是最坏的结果：至少那块地还在。
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("不假装它长到了哪一步：一格都不点亮，也不说「第 0 步」", () => {
    const { container } = render(<GrowthTrail stage={UNKNOWN} />);

    expect(container.querySelectorAll("span")).toHaveLength(7);
    expect(container.querySelectorAll(".bg-accent")).toHaveLength(0);
    expect(screen.getByRole("img", { name: "七步，现在这一步还说不准" })).toBeVisible();
    expect(container).not.toHaveTextContent("0");
  });

  it("四个入口都受得住同一个认不出来的字符串", () => {
    for (const node of [
      <GrowthPlant key="plant" stage={UNKNOWN} />,
      <Growth key="row" stage={UNKNOWN} word="在长着" />,
      <GrowthChip key="chip" stage={UNKNOWN} word="在长着" />,
      <GrowthTrail key="trail" stage={UNKNOWN} />,
    ]) {
      expect(() => render(node)).not.toThrow();
    }
  });
});

describe("不出现百分比", () => {
  it("七档一个数字都不给，也不给「完成度」这种说法", () => {
    // 一个百分比会立刻引出"凭什么是 40%"。定了时间没定地点，和定了地点
    // 没定时间，谁更"完成"？
    for (const { stage, word, why } of STAGES) {
      const { container } = render(
        <>
          <GrowthPlant stage={stage} />
          <Growth stage={stage} word={word} why={why} />
          <GrowthChip stage={stage} word={word} />
          <GrowthTrail stage={stage} />
        </>,
      );

      const shown = container.textContent ?? "";
      expect(shown).not.toMatch(/%|％/);
      expect(shown).not.toMatch(/\d\s*\/\s*\d/);
      expect(shown).not.toMatch(/完成度|进度|百分/);
      // 屏上一个数字都不该有：数字一出现就会被读成分数。
      expect(shown).not.toMatch(/\d/);
    }
  });

  it("读屏听到的是第几步，不是一个比例", () => {
    render(<GrowthTrail stage="growing" />);

    const trail = screen.getByRole("img");
    expect(trail.getAttribute("aria-label")).toBe("七步里的第 4 步");
  });
});

describe("配色只走 token", () => {
  it("画里一个 hex 都没有：颜色由外面那一层决定", () => {
    // 主色一旦要换，只该改 globals.css 一处。
    for (const { stage } of STAGES) {
      const svg = plantOf(stage);

      expect(svg.innerHTML).not.toMatch(/#[0-9a-fA-F]{3}/);
      for (const shape of svg.querySelectorAll("[fill], [stroke]")) {
        for (const name of ["fill", "stroke"]) {
          const value = shape.getAttribute(name);
          if (value !== null) expect(["currentColor", "none"]).toContain(value);
        }
      }
    }
  });

  it("还没发芽是灰的，别的都不是——它还没开始，不是它不好", () => {
    const { container: seed } = render(<GrowthPlant stage="seed" />);
    expect(seed.firstElementChild?.className).toContain("text-ink-faint");

    for (const { stage } of STAGES.slice(1)) {
      const { container } = render(<GrowthPlant stage={stage} />);
      expect(container.firstElementChild?.className).not.toContain("text-ink-faint");
    }
  });

  it("开花和结果分得开：不是同一个颜色", () => {
    const { container: bloom } = render(<GrowthChip stage="bloom" word="开花了" />);
    const { container: fruit } = render(<GrowthChip stage="fruit" word="结籽了" />);

    expect(bloom.firstElementChild?.className).not.toBe(fruit.firstElementChild?.className);
  });
});
