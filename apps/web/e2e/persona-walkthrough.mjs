/**
 * UI-only persona 走查。
 *
 * ## 规则
 *
 * **只通过界面操作。** 不读源码、不直连 API、不看文档——像一个刚打开这个
 * 网页的学生。唯一的例外是往浏览器 localStorage 里写一个身份，因为演示期
 * 没有登录页；那是"这台机器上的我是谁"，不是产品逻辑。
 *
 * ## 量什么
 *
 * ```
 * blocked_steps    走不下去：该有的入口不在，或者点了没反应
 * term_leaks       界面上出现了领域词汇
 * missing_states   该有的状态没有（主要是空态说不出下一步）
 * dead_ends        进得去出不来：一屏上没有任何通向下一步的东西
 * ```
 *
 * `confusion_hits` 与 `abandon_points` 需要判断力，机器给不出——它们由
 * 读这份报告的人补。**把五项都说成自动测好了是自欺。**
 *
 * 用法：`node e2e/persona-walkthrough.mjs [baseUrl]`
 */
import { chromium } from "playwright";

const BASE = process.argv[2] ?? "http://127.0.0.1:3000";

/** 从 CONTEXT.md 的术语表来。界面上出现任何一个都是泄漏。 */
const BANNED = [
  "意图信号", "意图编译", "匹配信封", "成局提案", "成局证明", "稳定性检查",
  "阻塞证明", "记忆切面", "行动回声", "场域智能体", "意图使者", "个人代理",
  "同意凭证", "代理授权", "共同素材", "共同行动边", "持续共同体", "曝光公平",
  "撮合窗口", "行动机会", "主体", "切面", "漏斗", "召回", "求解", "撮合",
  "信封", "凭证", "席位",
];

/** 八个 persona。每个只走他真的会走的那条路。 */
const PERSONAS = [
  {
    name: "大一新生，零历史，不知道这产品能干嘛",
    path: "/",
    // 他打开首页，需要立刻明白能干什么，并且有东西可点。
    wants: ["示范", "可点的入口"],
  },
  {
    name: "慢热的大三技术生，不想主动开口",
    path: "/",
    wants: ["不用先填资料", "可点的入口"],
  },
  {
    name: "赶 deadline 的发起人，只剩两天",
    path: "/waiting",
    wants: ["说得出下次什么时候配队", "还能改需求"],
  },
  {
    name: "社团组织者，要为比赛凑三支队",
    path: "/opportunities",
    wants: ["看得到在招什么", "能自己发一份"],
  },
  {
    name: "隐私敏感者，想知道系统记了自己什么",
    path: "/me",
    wants: ["看得到系统记了什么", "能收回"],
  },
  {
    name: "收到邀请但想拒绝的人",
    path: "/invitations",
    wants: ["看得到有没有人在等我"],
  },
  {
    name: "中途要退出的成员",
    path: "/me",
    wants: ["看得到我参加过什么"],
  },
  {
    name: "完成过一次、两周后回来的人",
    path: "/me",
    wants: ["看得到我留下过什么"],
  },
];

async function walk(page, persona) {
  const friction = {
    persona: persona.name,
    blocked_steps: 0,
    term_leaks: 0,
    missing_states: 0,
    dead_ends: 0,
    notes: [],
  };

  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 120)));

  await page.goto(`${BASE}${persona.path}`, { waitUntil: "networkidle" });
  // 客户端取数要一会儿。等不到就是等不到——那本身就是一次卡住。
  await page.waitForTimeout(1500);

  const text = await page.evaluate(() => document.body.innerText);

  if (errors.length) {
    friction.blocked_steps += 1;
    friction.notes.push(`页面报错：${errors[0]}`);
  }

  // 领域词汇泄漏
  const leaks = BANNED.filter((term) => text.includes(term));
  friction.term_leaks = leaks.length;
  if (leaks.length) friction.notes.push(`界面上出现：${leaks.join("、")}`);

  // 走不下去：一屏上没有任何可点的东西
  const clickable = await page.locator("button, a[href]").count();
  if (clickable === 0) {
    friction.dead_ends += 1;
    friction.notes.push("这一屏没有任何可以点的东西");
  }

  // 空态要说下一步，不能只说"没有"
  const looksEmpty = /还没有|没有正在|一个都没有|暂无|还没参加/.test(text);
  if (looksEmpty) {
    const saysNext = /去|说说|发一份|先|试试|看看/.test(text);
    if (!saysNext) {
      friction.missing_states += 1;
      friction.notes.push("空态只说了「没有」，没说下一步做什么");
    }
  }

  // 内容太少 = 用户对着一屏什么都没有
  if (text.trim().length < 40) {
    friction.blocked_steps += 1;
    friction.notes.push(`这一屏几乎是空的（${text.trim().length} 字）`);
  }

  friction.total =
    friction.blocked_steps +
    friction.term_leaks +
    friction.missing_states +
    friction.dead_ends;
  return friction;
}

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1280, height: 900 },
});
// 演示期没有登录页，身份放在 localStorage 里。
await context.addInitScript(() => {
  window.localStorage.setItem(
    "cofield.principal",
    "00000000-0000-4000-8000-000000000001",
  );
});

const report = [];
for (const persona of PERSONAS) {
  const page = await context.newPage();
  report.push(await walk(page, persona));
  await page.close();
}
await browser.close();

const total = report.reduce((sum, f) => sum + f.total, 0);
const summary = {
  base: BASE,
  measured_here: ["blocked_steps", "term_leaks", "missing_states", "dead_ends"],
  left_to_a_human: ["confusion_hits", "abandon_points"],
  personas: report,
  total_friction: total,
};
console.log(JSON.stringify(summary, null, 2));
process.exit(total === 0 ? 0 : 1);
