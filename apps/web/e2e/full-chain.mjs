/**
 * 一个人从零开始，只用界面，走完他能走的全部。
 *
 * ## 和 persona-walkthrough 的区别
 *
 * 那个逐屏打开看有没有明显问题。**这个真的在用产品**：打字、点按钮、
 * 等结果、读屏上写了什么。前者能过而后者过不了的地方，正是"每一片都做好了、
 * 合起来走不动"藏身的地方。
 *
 * ## 规则
 *
 * 只通过界面。不读源码、不看文档、不直接打 API——**除了两处**：
 *
 * 1. 往 localStorage 写一个身份（演示期没有登录页）
 * 2. 判断某一步是否成功时读 DOM 文本
 *
 * 「现在就配一轮」那个按钮是**界面上真有的**（演示模式），
 * 所以走查用它推进，不是绕过界面调 API。
 *
 * ## 一个人走不完的部分
 *
 * 成局需要队里每个人各自点头。一个 persona 走到「我加入 → 还在等谁」
 * 就到头了，**这本身就是真实的用户体验**，不是走查的缺陷。
 * 那之后的屏（项目空间、留下什么）由已经成局的场景单独验。
 */
import { chromium } from "playwright";

const BASE = process.argv[2] ?? "http://127.0.0.1:3000";
const ME = process.argv[3] ?? "00000000-0000-4000-8000-0000000000aa";

const BANNED = [
  "意图信号", "意图编译", "匹配信封", "成局提案", "成局证明", "稳定性检查",
  "阻塞证明", "记忆切面", "行动回声", "场域智能体", "同意凭证", "代理授权",
  "共同素材", "曝光公平", "撮合窗口", "行动机会", "主体", "切面", "漏斗",
  "召回", "求解", "撮合", "信封", "凭证", "席位", "成局",
];

const friction = [];
function stuck(step, why) {
  friction.push({ step, why });
  console.log(`  ✗ ${step} —— ${why}`);
}
function ok(step, note = "") {
  console.log(`  ✓ ${step}${note ? " —— " + note : ""}`);
}

async function textOf(page) {
  // **要把输入框里的值也算进来。** 需求卡上「我缺」是可编辑的，
  // `innerText` 读不到它——只读 innerText 会把一张填好的卡看成空卡，
  // 然后报一个不存在的卡点。第一版就是这么误报的。
  return page.evaluate(() => {
    const typed = [...document.querySelectorAll("input, textarea")]
      .map((e) => e.value)
      .filter(Boolean)
      .join("\n");
    return document.body.innerText + "\n" + typed;
  });
}

async function checkWords(page, step) {
  const text = await textOf(page);
  const leaks = BANNED.filter((t) => text.includes(t));
  if (leaks.length) stuck(step, `界面上出现领域词汇：${leaks.join("、")}`);
}

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
await context.addInitScript(
  (me) => window.localStorage.setItem("cofield.principal", me),
  ME,
);
const page = await context.newPage();
page.on("pageerror", (e) => stuck("页面报错", String(e).slice(0, 100)));

console.log("\n① 打开首页，看得出这是干什么的吗");
await page.goto(BASE, { waitUntil: "networkidle" });
await page.waitForTimeout(1200);
{
  const text = await textOf(page);
  if (text.length < 60) stuck("首页", "几乎是空的");
  else ok("首页", `${text.split("\n")[0]}`);
  await checkWords(page, "首页");
}

console.log("\n② 说一句话");
{
  const box = page.locator("textarea, input[type=text]").first();
  if ((await box.count()) === 0) {
    stuck("说一句话", "找不到可以打字的地方");
  } else {
    await box.click();
    await box.fill("想拍支短片，缺个会剪辑的和一个会拍摄的，这周末，三四个人");
    await page.waitForTimeout(300);
    // 找那个把话变成卡片的按钮。
    const go = page.getByRole("button", { name: /整理|看看|开始|下一步|继续|帮我/ });
    if ((await go.count()) === 0) {
      const buttons = await page.getByRole("button").allInnerTexts();
      stuck("说一句话", `打完字之后不知道点哪个：${buttons.join(" / ")}`);
    } else {
      await go.first().click();
      await page.waitForTimeout(2500);
      const text = await textOf(page);
      if (text.includes("剪辑") && text.includes("拍摄")) {
        ok("整理成需求卡", "缺的两样都认出来了");
      } else {
        stuck("整理成需求卡", "屏上看不到它认出了「剪辑」和「拍摄」");
      }
      await checkWords(page, "需求卡");
    }
  }
}

console.log("\n③ 确认，开始找人");
{
  const confirm = page.getByRole("button", { name: /开始找人|就这样|确认/ });
  if ((await confirm.count()) === 0) {
    const buttons = await page.getByRole("button").allInnerTexts();
    stuck("确认", `不知道怎么让它开始找人：${buttons.join(" / ")}`);
  } else {
    await confirm.first().click();
    await page.waitForTimeout(2500);
    ok("确认");
  }
}

console.log("\n④ 等配队这一屏说得出什么");
await page.goto(`${BASE}/waiting`, { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
{
  const text = await textOf(page);
  if (/配队/.test(text)) ok("等配队", text.split("\n")[0]);
  else stuck("等配队", "说不出下次什么时候配");
  await checkWords(page, "等配队");

  const now = page.getByRole("button", { name: /现在就配|快进/ });
  if ((await now.count()) === 0) {
    stuck("等配队", "没有任何办法看到配队结果——只能真等六小时");
  } else {
    await now.first().click();
    await page.waitForTimeout(6000);
    ok("触发一轮配队");
  }
}

console.log("\n⑤ 给你找的人");
await page.goto(`${BASE}/waiting`, { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
{
  const link = page.getByRole("link", { name: /小队|给你找|看看/ });
  if ((await link.count()) > 0) {
    await link.first().click();
    await page.waitForTimeout(2500);
  } else {
    stuck("从等配队走到小队", "配完之后没有任何入口通向结果");
  }
  const text = await textOf(page);
  if (/%|匹配度|评分|得分/.test(text)) {
    stuck("小队", "屏上出现了百分比或分数");
  }
  await checkWords(page, "小队");
  console.log(`     屏上第一行：${text.split("\n").filter(Boolean)[0] ?? "(空)"}`);
}

console.log("\n⑥ 我的记录（零历史的人第一次打开）");
await page.goto(`${BASE}/me`, { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
{
  const text = await textOf(page);
  if (text.trim().length < 40) stuck("我的记录", "一片空白");
  else if (!/去|说说|先|试试/.test(text)) {
    stuck("我的记录", "空态只说了「没有」，没说下一步做什么");
  } else ok("我的记录", text.split("\n").filter(Boolean).slice(0, 2).join(" / "));
  await checkWords(page, "我的记录");
}

console.log("\n⑦ 有哪些招募");
await page.goto(`${BASE}/opportunities`, { waitUntil: "networkidle" });
await page.waitForTimeout(2000);
{
  const text = await textOf(page);
  if (text.trim().length < 40) stuck("招募", "一片空白");
  else ok("招募", text.split("\n").filter(Boolean)[1] ?? "");
  await checkWords(page, "招募");
}

await browser.close();

console.log(`\n${"─".repeat(60)}`);
if (friction.length === 0) {
  console.log("走完了，一处没卡。");
} else {
  console.log(`卡了 ${friction.length} 处：`);
  for (const f of friction) console.log(`  · ${f.step}：${f.why}`);
}
process.exit(friction.length === 0 ? 0 : 1);
