/**
 * 八个 persona，各自走完他真的会走的那条路。
 *
 * ## 这个文件重写过一次，因为第一版是在自欺
 *
 * 第一版给每个 persona 打开**一屏**，检查有没有可点的东西、有没有领域
 * 词汇泄漏，然后报"总摩擦 0"。它八个全绿的那天，产品里躺着一个
 * 「两个真人从来没有可能被配到一起」的洞。
 *
 * 逐屏打开永远发现不了那种事。**只有真的走完才行**：填自己这边、发起、
 * 配一轮、在另一个人的浏览器里收到邀请、答复、看到小队。
 *
 * ## 规则
 *
 * 只通过界面。不读源码、不看文档、不直接打 API——**除了两处**：
 *
 * 1. 往 localStorage 写一个身份（演示期没有登录页）
 * 2. 判断某一步是否成功时读 DOM 文本
 *
 * 「现在就配一轮」那个按钮是界面上真有的（演示模式），所以走查用它推进，
 * 不是绕过界面调 API。
 *
 * ## 每个 persona 用自己的浏览器上下文
 *
 * 因为**成局需要每个人各自点头**，一个人的浏览器走不完。他们共享同一个
 * 后端——这正是真实情况：不同的人，同一个校园。
 *
 * ## 跑之前先把校园清干净
 *
 * ```
 * docker compose exec api python -m cofield.cli seed
 * node e2e/persona-walkthrough.mjs
 * ```
 *
 * **不清的话第⑨幕会时灵时不灵**：上几轮留下的同类需求还在池子里，
 * 它们会把这一轮的搭档先占走（一个人一轮里最多被提两次，这正是曝光上限
 * 该做的事），于是搭档被配给了一个上一轮的、再也不会打开这个网页的人。
 *
 * 那不是产品的毛病，是走查在和自己上几次打架。第⑩幕会收走这一轮自己
 * 留下的需求，但收不走别的轮次的。
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
  "信封", "凭证", "席位", "成局",
];

/**
 * 一次性的身份。每个 persona 一个，互不相干，**而且每跑一次都是新人**。
 *
 * 固定 id 的时候第二遍就跑不过了：上一遍的承诺还挂在同一个人身上，
 * 撞上"同时进行的事不能太多"这条约束，于是队配不出来。那不是产品的毛病，
 * 是走查在和自己上一次打架。每次来的是几个新同学，这也正是真实情况。
 */
const RUN = (Date.now() % 0xffffffff).toString(16).padStart(8, "0");
const id = (n) => `00000000-0000-4000-8000-${RUN}${String(n).padStart(4, "0")}`;

/** 第⑨幕那位搭档。身份每轮都不同，名字由他自己在第一屏填。 */
const HELPER = `00000000-0000-4000-8000-${RUN}${RUN.slice(0, 4)}`;

const friction = [];

/** 明天几点，写成 `datetime-local` 认的那种本地时间串。 */
function tomorrowAt(hour) {
  const t = new Date(Date.now() + 24 * 3600 * 1000);
  t.setHours(hour, 0, 0, 0);
  const p = (n) => String(n).padStart(2, "0");
  return `${t.getFullYear()}-${p(t.getMonth() + 1)}-${p(t.getDate())}T${p(hour)}:00`;
}

function stuck(persona, step, why) {
  friction.push({ persona, step, why });
  console.log(`    ✗ ${step} —— ${why}`);
}
function ok(step, note = "") {
  console.log(`    ✓ ${step}${note ? " —— " + note : ""}`);
}

/** 屏上的字，**包括输入框里的值**——只读 innerText 会把填好的卡看成空卡。 */
async function textOf(page) {
  return page.evaluate(() => {
    const typed = [...document.querySelectorAll("input, textarea")]
      .map((e) => e.value)
      .filter(Boolean)
      .join("\n");
    return document.body.innerText + "\n" + typed;
  });
}

function checkWords(text, persona, step) {
  const leaks = BANNED.filter((t) => text.includes(t));
  if (leaks.length) stuck(persona, step, `界面上出现领域词汇：${leaks.join("、")}`);
}

/** 打开一屏并读它。顺手把泄漏和"这一屏几乎是空的"一起查了。 */
async function open(page, persona, path, step) {
  await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  const text = await textOf(page);
  if (text.trim().length < 40) stuck(persona, step, "这一屏几乎是空的");
  checkWords(text, persona, step);
  return text;
}

/**
 * 第一次进来先给自己起个名。
 *
 * **这是产品的第一步，不是走查的准备工作。** 没有它，队友在群里看到的是
 * 一个占位名——而这个产品的第一件事是让两个人愿意一起做点事，
 * 一个连名字都没有的人提出的邀请，收到的人先要判断这是不是真人。
 */
async function nameSelf(page, persona, name) {
  await page.goto(`${BASE}/welcome`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  const field = page.getByLabel("你叫什么名字");
  if ((await field.count()) === 0) {
    stuck(persona, "起名", "第一次进来没有地方说自己叫什么");
    return;
  }
  await field.fill(name);
  await page.getByRole("button", { name: /进去/ }).first().click();
  await page.waitForTimeout(2000);
  if (page.url().includes("/welcome")) {
    stuck(persona, "起名", "填了名字还是停在这一屏");
  } else ok("起了名", name);
}

/** 一个人的浏览器。**开场先起名**——那是产品的第一屏。 */
async function personFor(browser, principal, persona, name) {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 1000 },
  });
  await context.addInitScript(
    (me) => window.localStorage.setItem("cofield.principal", me),
    principal,
  );
  const page = await context.newPage();
  page.on("pageerror", (e) =>
    friction.push({
      persona: "(页面报错)",
      step: principal.slice(-4),
      why: String(e).slice(0, 120),
    }),
  );
  if (name) await nameSelf(page, persona, name);
  return page;
}

/** 「我这边」填一遍。这是一个人**被找到的唯一方式**。 */
async function describeSelf(page, persona, { can = [], want = [], intro = "" }) {
  await open(page, persona, "/me/about", "我这边");
  for (const [name, words] of [
    ["我能做的", can],
    ["我想参与的", want],
  ]) {
    for (const word of words) {
      const chip = page.getByRole("region", { name }).getByRole("checkbox", { name: word });
      if ((await chip.count()) === 0) {
        stuck(persona, "我这边", `「${name}」里没有「${word}」可选`);
        continue;
      }
      await chip.first().click();
    }
  }
  if (intro) await page.getByLabel("我是什么样的人").fill(intro);

  const save = page.getByRole("button", { name: "存下来" });
  if ((await save.count()) === 0) {
    stuck(persona, "我这边", "填完了没有地方可以存");
    return;
  }
  await save.click();
  await page.waitForTimeout(1500);
  const after = await textOf(page);
  if (!/存好了/.test(after)) {
    stuck(persona, "我这边", "存不下来");
  } else {
    ok("我这边", `能做${can.join("、") || "—"} / 想参与${want.join("、") || "—"}`);
  }
}

/** 说一句话 → 需求卡 → 开始找人。 */
async function postNeed(page, persona, sentence, expect = []) {
  await open(page, persona, "/", "首页");
  const box = page.locator("textarea, input[type=text]").first();
  if ((await box.count()) === 0) {
    stuck(persona, "说一句话", "找不到可以打字的地方");
    return false;
  }
  await box.click();
  await box.fill(sentence);
  const go = page.getByRole("button", { name: /整理/ });
  if ((await go.count()) === 0) {
    stuck(persona, "说一句话", "打完字之后不知道点哪个");
    return false;
  }
  await go.first().click();
  await page.waitForTimeout(2500);

  const card = await textOf(page);
  const missed = expect.filter((w) => !card.includes(w));
  if (missed.length) {
    stuck(persona, "整理成需求卡", `屏上看不到它认出了${missed.join("、")}`);
  }

  const confirm = page.getByRole("button", { name: /开始找人|就这样|确认/ });
  if ((await confirm.count()) === 0) {
    stuck(persona, "开始找人", "整理完了不知道怎么让它开始找人");
    return false;
  }
  await confirm.first().click();
  await page.waitForTimeout(2500);
  ok("发出这条需求", sentence.slice(0, 18) + "…");
  return true;
}

/** 界面上的「现在就配一轮」。 */
async function runRound(page, persona) {
  await open(page, persona, "/waiting", "等配队");
  const now = page.getByRole("button", { name: /现在就配|快进/ });
  if ((await now.count()) === 0) {
    stuck(persona, "等配队", "没有任何办法看到配队结果——只能真等六小时");
    return false;
  }
  await now.first().click();
  await page.waitForTimeout(6000);
  ok("配了一轮");
  return true;
}

// --- 走 ---

const browser = await chromium.launch();
console.log(`\n对着 ${BASE} 走八个 persona。\n`);

// ① 大一新生：零历史，什么都不懂，打开首页要立刻明白能干什么。
console.log("① 大一新生，零历史，不知道这产品能干嘛");
const freshman = await personFor(browser, id(1), "大一新生", "陈小木");
{
  const P = "大一新生";
  const text = await open(freshman, P, "/", "首页");
  if (!/想做点什么/.test(text)) stuck(P, "首页", "看不出这一屏要我干什么");
  else ok("首页", text.split("\n").filter(Boolean)[1] ?? "");

  const starters = await freshman.getByRole("button").count();
  if (starters < 2) stuck(P, "首页", "只有一个空输入框，没有可点的示范");
  else ok("有示范可点", `${starters} 个可点的`);

  if (!/让别人来找你|能做什么/.test(text)) {
    stuck(P, "首页", "只能发起，说不出「我不发起也能被找到」");
  } else ok("不发起也有路可走");
}

// ② 慢热的技术生：不想主动开口，只想被找到。
console.log("\n② 慢热的大三技术生，不想主动开口");
const quiet = await personFor(browser, id(2), "慢热技术生", "沈知远");
{
  const P = "慢热技术生";
  await describeSelf(quiet, P, {
    // **不要在这里也声明「配乐」。** 第⑨幕的搭档靠它成为唯一候选；
    // 这里多声明一个，两个人就会在并列里靠 uuid 决胜负，
    // 而走查报出来的会是"他没收到这颗种子"，指向一个不存在的毛病。
    can: ["剪辑"],
    want: ["拍摄"],
    intro: "剪片子比较快，不太爱在群里说话",
  });
  const again = await open(quiet, P, "/me/about", "我这边（再打开）");
  if (!again.includes("剪片子比较快")) {
    stuck(P, "我这边", "存过之后再打开，填的东西不见了");
  } else ok("再打开还在");
}

// ③ 赶 deadline 的发起人：先把需求发出去。
//
// **这一轮配队故意押后。** 一个校园里同时只有两个真人的时候，三人队本来
// 就凑不出来——那不是产品的毛病，是人还没来。等 ④⑤ 也各自说清自己能做
// 什么，再配这一轮。
console.log("\n③ 赶 deadline 的发起人，只剩两天");
const rusher = await personFor(browser, id(3), "赶deadline的发起人", "周叙");
let needPosted = false;
{
  const P = "赶deadline的发起人";
  await describeSelf(rusher, P, { can: ["写脚本"] });
  needPosted = await postNeed(
    rusher,
    P,
    "想拍支短片，缺个会剪辑的，这周末，三四个人",
    ["剪辑"],
  );
  if (needPosted) {
    const waiting = await open(rusher, P, "/waiting", "等配队");
    if (!/配队/.test(waiting)) stuck(P, "等配队", "说不出下次什么时候配");
    else ok("等配队", waiting.match(/[^\n]*配队[^\n]*/)?.[0] ?? "");
  }
}

// ④ 社团组织者：他要看在招什么，也要能自己发一份。
console.log("\n④ 社团组织者，要为比赛凑三支队");
const organiser = await personFor(browser, id(4), "社团组织者", "许南屏");
{
  const P = "社团组织者";
  const text = await open(organiser, P, "/opportunities", "有哪些招募");
  if (!/招|队|人/.test(text)) stuck(P, "招募", "看不出这一屏在招什么");
  else ok("看得到在招什么", text.split("\n").filter(Boolean)[1] ?? "");

  await describeSelf(organiser, P, { can: ["拍摄"], want: ["剪辑"] });
  await open(organiser, P, "/opportunities", "有哪些招募（回到列表）");

  const post = organiser
    .getByRole("link", { name: /发一份|我要招|新建|自己发/ })
    .or(organiser.getByRole("button", { name: /发一份|我要招|新建|自己发/ }));
  if ((await post.count()) === 0) {
    stuck(P, "招募", "只能看别人招，自己发不了");
  } else {
    await post.first().click();
    await organiser.waitForTimeout(2000);
    const form = await textOf(organiser);
    checkWords(form, P, "发一份招募");
    if ((await organiser.locator("textarea, input").count()) === 0) {
      stuck(P, "发一份招募", "点进来之后没有可以填的东西");
    } else ok("能自己发一份");
  }
}

// ⑤ 隐私敏感者：想知道系统记了自己什么，并且改得了别人怎么找到他。
console.log("\n⑤ 隐私敏感者，想知道系统记了自己什么");
const careful = await personFor(browser, id(5), "隐私敏感者", "何清让");
{
  const P = "隐私敏感者";
  const text = await open(careful, P, "/me", "我的记录");
  if (!/只有你看得到/.test(text)) stuck(P, "我的记录", "说不清这一页给谁看");
  else ok("说清了这页不给别人看");

  if (!/去|说说|先|试试|我这边/.test(text)) {
    stuck(P, "我的记录", "空态只说了「没有」，没说下一步做什么");
  } else ok("空态说得出下一步");

  if (!/我这边|能做什么/.test(text)) {
    stuck(P, "我的记录", "改不了「别人怎么找到我」——那正是他最想改的");
  } else ok("改得了别人怎么找到我");

  // 他愿意参与，但不想被当成会做——这正是「我想参与的」那一栏的用处。
  await describeSelf(careful, P, { want: ["剪辑"] });
}

// 校园里现在有四个说清了自己的人。**这时候才投得出去。**
console.log("\n—— 人齐了，配一轮 ——");
let sowed = false;
if (needPosted) {
  const P = "赶deadline的发起人";
  await runRound(rusher, P);

  // 投递制（ADR 0010）：种子先投到候选的信箱，他们表态，发起人再挑。
  // **发起人面对的每一个人都已经说过愿意**——这一屏消灭的正是「石沉大海」。
  let willing = 0;
  for (const [who, page] of [["慢热技术生", quiet], ["社团组织者", organiser]]) {
    const text = await open(page, P, "/seeds", "信箱");
    const card = page.getByRole("region", { name: /短片|剪辑/ });
    if ((await card.count()) === 0) {
      stuck(P, `${who}的信箱`, `没收到这颗种子：${text.split("\n").filter(Boolean)[2] ?? ""}`);
      continue;
    }
    if (!/不等于|还要.*挑|还要.*选/.test(text)) {
      stuck(P, "信箱", "没说清「说了愿意不等于已经加入」");
    }
    await card.first().getByRole("button", { name: "我愿意" }).click();
    await page.waitForTimeout(2000);
    willing += 1;
    ok(`${who}说了愿意`);
  }

  if (willing > 0) {
    const seen = await open(rusher, P, "/waiting", "行动中");
    const link = rusher.getByRole("link", { name: /谁说了愿意|看看/ });
    if ((await link.count()) === 0) {
      stuck(P, "看结果", "有人说了愿意，却没有入口通向他们");
    } else {
      await link.first().click();
      await rusher.waitForTimeout(2500);
      const screen = await textOf(rusher);
      checkWords(screen, P, "谁说了愿意");
      if (/%|匹配度|评分|得分|第 ?\d+ ?名/.test(screen)) {
        stuck(P, "谁说了愿意", "屏上出现了分数或名次");
      }
      const pickable = rusher.getByRole("button", { name: /选 ?TA/ });
      if ((await pickable.count()) === 0) {
        stuck(P, "谁说了愿意", `一个能挑的人都没有：${seen.split("\n").filter(Boolean)[2] ?? ""}`);
      } else {
        await pickable.first().click();
        await rusher.waitForTimeout(2500);
        sowed = true;
        ok("挑了一个人", (await textOf(rusher)).match(/[^\n]*人齐了[^\n]*|[^\n]*还差[^\n]*/)?.[0] ?? "");
      }
    }
  }
}

// ⑥ 收到种子但想拒绝的人。
console.log("\n⑥ 收到种子但这次不想参与的人");
{
  const P = "想拒绝的人";
  const text = await open(careful, P, "/seeds", "信箱");
  const card = careful.getByRole("region", { name: /短片|剪辑|配乐/ });
  if ((await card.count()) > 0) {
    await card.first().getByRole("button", { name: "这次不感兴趣" }).click();
    await careful.waitForTimeout(2000);
    const after = await textOf(careful);
    if (!/这次不参与|不感兴趣|知道了/.test(after)) {
      stuck(P, "这次不感兴趣", "拒绝之后屏上没有任何交代");
    } else ok("这次不感兴趣", "一步完成，不问为什么");
  } else if (/还没有人找你|没有种子|空/.test(text)) {
    ok("信箱是空的", "说得清楚，不是白屏");
  } else {
    stuck(P, "信箱", "既没有种子，也没说清楚现在没有");
  }
}

// ⑦ 中途要退出的人：他得看得到自己参加过什么。
console.log("\n⑦ 中途要退出的成员");
{
  const P = "要退出的人";
  const text = await open(rusher, P, "/me", "我参加过的");
  if (!/我的森林|森林还是空的/.test(text)) {
    stuck(P, "我的森林", "看不到自己参加过什么");
  } else ok("看得到我参加过什么");
}

// ⑧ 完成过一次、两周后回来的人。
console.log("\n⑧ 完成过一次、两周后回来的人");
{
  const P = "回头的人";
  const text = await open(rusher, P, "/me", "我留下过什么");
  if (!/关于我的记录|谁能看到我|森林还是空的/.test(text)) {
    stuck(P, "我留下过什么", "看不到自己留下过什么");
  } else ok("看得到我留下过什么");
}

// ⑨ 成了之后：这半条链走查一直没碰过。
//
// 前面每个人都停在「还差谁点头」。而**这个产品的一半在成局之后**——
// 项目空间、话题卡、留下了什么。用一支两人队把它走完：两人是最小的队，
// 也是唯一能确定成局的规模。
console.log("\n⑨ 都点头之后，这件事有地方可做吗");
const helper = await personFor(browser, HELPER, "成了之后", "陶昀嘉");
/** 第⑨幕真的成了没有。**放在块外**——⑨½ 要用它决定自己跑不跑，
 *  而一件没成的事谈不上"做完之后"。 */
let formed = false;
{
  const P = "成了之后";
  const posted = await postNeed(
    rusher,
    P,
    "想给一支社团回顾配段音乐，缺个会配乐的，两个人就行",
    ["配乐"],
  );
  if (!posted) {
    stuck(P, "再发一条", "第二条需求没发出去");
  } else {
    // 这一轮的搭档：一个只说自己会配乐的新同学。
    await describeSelf(helper, P, { can: ["配乐"] });
    await runRound(rusher, P);

    // **搭档先说愿意，发起人再挑他。**
    //
    // 投递制下这一步天然没有歧义：搭档只会在自己那一颗种子上表态，
    // 而发起人看到的是"已经说了愿意的人"——他挑谁就是谁，不用再等回音。
    await open(helper, P, "/seeds", "信箱");
    const his = helper.getByRole("region", { name: /配乐|音乐/ });
    if ((await his.count()) === 0) {
      stuck(P, "搭档的信箱", "他没收到这颗种子");
    } else {
      await his.first().getByRole("button", { name: "我愿意" }).click();
      await helper.waitForTimeout(2500);
      ok("搭档说了愿意");

      await open(rusher, P, "/waiting", "行动中");
      const link = rusher.getByRole("link", { name: /谁说了愿意|看看/ });
      if ((await link.count()) === 0) {
        stuck(P, "看结果", "有人说了愿意，却没有入口通向他们");
      } else {
        await link.first().click();
        await rusher.waitForTimeout(2500);
        const pickable = rusher.getByRole("button", { name: /选 ?TA/ });
        if ((await pickable.count()) === 0) {
          stuck(P, "挑人", "一个能挑的人都没有");
        } else {
          await pickable.first().click();
          await rusher.waitForTimeout(3000);
          formed = /人齐了|这件事定下来了|去这件事的地方/.test(await textOf(rusher));
          if (!formed) stuck(P, "挑人", "挑完了却没成局");
          else ok("挑了他，这件事成了");
        }
      }
    }

    if (formed) {
      {
        // **刷新一次再找门。** 一次性的响应不能是入口的唯一来源。
        await rusher.reload({ waitUntil: "networkidle" });
        await rusher.waitForTimeout(1500);
        const door = rusher.getByRole("link", { name: /去这件事的地方/ });
        if ((await door.count()) === 0) {
          stuck(P, "进项目空间", "刷新之后，刚答应下来的那件事没有门");
        } else {
          await door.first().click();
          await rusher.waitForTimeout(2500);
          // 验的是**走进来的这个人**的屏。原来读的是 helper——
          // 于是行动房间的用词从来没有被真正检查过。
          const space = await textOf(rusher);
          checkWords(space, P, "项目空间");
          if (!rusher.url().includes("/spaces/")) {
            stuck(P, "进项目空间", `那扇门通向的不是这件事的地方：${rusher.url()}`);
          }

          const board = rusher.getByRole("region", { name: "这件事现在到哪了" });
          if ((await board.count()) === 0) {
            stuck(P, "项目空间", "看不出这件事现在到哪了");
          } else {
            ok("看得出到哪了", (await board.first().innerText()).split("\n")[0]);
          }

          const start = rusher.getByRole("region", { name: "从哪开始" });
          if ((await start.count()) === 0) {
            stuck(P, "项目空间", "进来之后不知道该干什么");
          } else {
            ok("知道先做什么", (await start.first().innerText()).split("\n")[0]);
          }

          if ((await rusher.getByRole("textbox").count()) === 0) {
            stuck(P, "项目空间", "组起来了却没有地方说话");
          } else ok("有地方说话");

          // **助手是按出来的，不是自己冒出来的。** PRD 把这一条列在
          // 阶段五：一次只处理眼前一个卡点，而且要留一条"继续聊聊"的出路。
          const push = rusher.getByRole("button", { name: "推进一下" });
          if ((await push.count()) === 0) {
            stuck(P, "推进一下", "卡住的时候没有任何办法让它帮一把");
          } else {
            await push.first().click();
            await rusher.waitForTimeout(4000);
            const after = await textOf(rusher);
            if (/不算定下来|还要有人点头|继续聊聊/.test(after)) {
              ok("助手帮了一把，而且说清了它不算数");
            } else {
              stuck(P, "推进一下", "它说了话，但没说清这不算定下来");
            }
            checkWords(after, P, "推进一下");
          }

          // **这半条链是产品的终点**：PRD 说它不以"聊起来"为终点，
          // 以真的一起完成了一次行动为终点。
          const plan = rusher.getByRole("region", { name: "这次怎么办" });
          const write = plan.getByRole("button", { name: "写一张" });
          if ((await write.count()) === 0) {
            stuck(P, "这次怎么办", "没有地方把时间地点定下来");
          } else {
            await write.click();
            await rusher.waitForTimeout(800);
            await rusher.getByLabel("这次做什么").fill("周六去后山配乐");
            // **定在明天，不是写死的某个周六。**「到那天了」那一块在行动日
            // 前一天才出现——把日期写死在未来，走查就永远走不到"做完了"，
            // 而报出来的会是"找不到那个按钮"，指向一个不存在的毛病。
            await rusher.getByLabel("什么时候").fill(tomorrowAt(9));
            await rusher.getByLabel("在哪集合").fill("北门地铁口");
            await rusher.getByRole("button", { name: "存下来" }).click();
            // **在 rusher 自己的屏上验，并且等它出现。**
            // 原来这里读的是 helper 的屏——存的人是 rusher，去另一个人
            // 那儿找刚写的东西，报出来的"没存上"指向一个不存在的毛病。
            const saved = await rusher
              .getByText("北门地铁口")
              .first()
              .waitFor({ timeout: 8000 })
              .then(() => "北门地铁口")
              .catch(() => textOf(rusher));
            if (!/北门地铁口/.test(saved)) {
              stuck(P, "这次怎么办", "写完了没存上");
            } else {
              ok("把这次怎么办定下来了");
              await rusher.getByRole("button", { name: "就这么办" }).click();
              await rusher.waitForTimeout(2000);
              if (!/你确认过了/.test(await textOf(rusher))) {
                stuck(P, "就这么办", "点完之后没说我已经确认");
              } else ok("我确认了这次就这么办");
            }
          }
        }
      }
    }
  }
}

// ⑨½ 做完之后：一株结出下一颗种子
//
// PRD 的最后一段。**这一幕必须排在⑩之前**——⑩会把这一轮留下的需求全部
// 收回，而"照上次再来一次"发出的那条正是要被收回的东西之一。
console.log("\n⑨½ 做完之后，还能不能长出下一件");
if (formed) {
  const P = "做完一次的人";

  // 两个人各自说做完了。**这一步不能只有一个人按**：
  // 一个人说完了就算完，等于让一个人替另一个人作证。
  //
  // **搭档得自己走进去。** 他一直待在信箱那一屏——直接给他一个 URL
  // 等于替他找到了门，而"被挑中的人怎么进到这件事里"正是要验的东西。
  await open(helper, P, "/seeds", "信箱");
  const door = helper.getByRole("link", { name: /去这件事的地方/ });
  if ((await door.count()) === 0) {
    stuck(P, "进这件事", "被挑中了，信箱里却没有门通向那件事");
  } else {
    await door.first().click();
    await helper.waitForTimeout(2500);
  }

  let marked = 0;
  for (const page of [rusher, helper]) {
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(1500);
    const done = page.getByRole("button", { name: "我这边做完了" });
    if ((await done.count()) === 0) continue;
    await done.first().click();
    await page.waitForTimeout(1800);
    marked += 1;
  }
  if (marked < 2) {
    stuck(P, "做完了", `只有 ${marked} 个人能说做完——另一个人找不到那个按钮`);
  } else ok("两个人各自说了做完");

  await open(rusher, P, "/me", "我的森林");
  const into = rusher.getByRole("link", { name: /看看这次留下了什么|打开这件事/ });
  if ((await into.count()) === 0) {
    stuck(P, "再来一次", "森林里的一株点不进去");
  } else {
    await into.first().click();
    await rusher.waitForTimeout(2500);
  }
  const forest = await textOf(rusher);
  if (!/还想再来一次/.test(forest)) {
    stuck(P, "再来一次", "做完了，却没有任何办法照着再来一次");
  } else {
    ok("做完的那件事问我要不要再来一次");

    // **先照着发下一条，再回来问他们。** 这才是这一圈的真实顺序：
    // 「问他们」问的是一条**新的**需求，而这条新需求正是从上次那件事
    // 长出来的——PRD 说的"一株结出下一颗种子"指的就是这个。
    const echoUrl = rusher.url();
    const again = rusher.getByRole("link", { name: "照这个再来一次" });
    if ((await again.count()) === 0) {
      stuck(P, "再来一次", "看得到问句，却没有照着再发一条的入口");
    } else {
      await again.first().click();
      await rusher.waitForTimeout(2500);
      const draft = await textOf(rusher);
      if (!/配乐|音乐/.test(draft)) {
        stuck(P, "再来一次", "带过去的是一张空卡，上次做的什么没带上");
      } else ok("上次的目标带过去了", "时间地点留空——它们必然是新的");

      await rusher.getByRole("button", { name: /整理/ }).first().click();
      await rusher.waitForTimeout(2500);
      const go = rusher.getByRole("button", { name: /开始找人/ });
      if ((await go.count()) === 0) {
        stuck(P, "再来一次", "带过来的这张卡发不出去");
      } else {
        await go.first().click();
        await rusher.waitForTimeout(2500);
        ok("下一件事发出去了");
      }

      await rusher.goto(echoUrl, { waitUntil: "networkidle" });
      await rusher.waitForTimeout(2000);
      const pick = rusher.getByRole("combobox", { name: "选一条需求" });
      if ((await pick.count()) === 0) {
        stuck(P, "问上次的人", "发了新需求，却没法直接问上次那几个人");
      } else {
        const options = await pick.first().locator("option").all();
        if (options.length < 2) {
          stuck(P, "问上次的人", "选不到刚发出去的那条需求");
        } else {
          await pick.first().selectOption({ index: 1 });
          await rusher.getByRole("button", { name: "问他们" }).first().click();
          await rusher.waitForTimeout(3000);
          const said = await textOf(rusher);
          // **"问过了"和"人回来了"是两句话。** 不变量 3：未获真人确认
          // 不创建关系边。写成"他们回来了"，等于系统替他们答应了。
          if (/问过了|等他们/.test(said)) {
            ok("问过上次那几个人了", "说的是等他们答，不是他们回来了");
          } else {
            stuck(P, "问上次的人", "按完之后不知道到底问出去没有");
          }
          checkWords(said, P, "问上次的人");
        }
      }
    }
  }
}

// ⑩ 不找了：说得出口，而且**走查要收拾自己留下的东西**。
//
// 一条发出去的需求会一直待在池子里，一轮一轮占着会这一样的人。走查跑第二遍
// 时正是被这个绊住的：上一遍留下的「缺剪辑」把唯一那个会剪辑的人先占走了，
// 于是这一遍配不出队——**产品在正确地配给稀缺的人，是走查在和自己上一次打架。**
console.log("\n⑩ 不找了");
{
  const P = "不找了的人";
  for (const [who, page] of [
    ["发起人", rusher],
    ["慢热技术生", quiet],
    ["搭档", helper],
  ]) {
    await open(page, P, "/waiting", "等配队");
    let dropped = 0;
    for (;;) {
      const button = page.getByRole("button", { name: "这事不找了" });
      if ((await button.count()) === 0) break;
      await button.first().click();
      await page.waitForTimeout(1200);
      dropped += 1;
      if (dropped > 6) break;
    }
    if (who === "发起人" && dropped === 0) {
      stuck(P, "这事不找了", "发出去的需求没有任何办法收回");
    } else if (dropped > 0) {
      ok(`${who}收回了 ${dropped} 条`, "一步完成，不问为什么");
    }
  }
  const after = await textOf(rusher);
  if (/你在等的事/.test(after) && !/还没有正在等配队的事/.test(after)) {
    stuck(P, "这事不找了", "收回之后它还留在屏上");
  } else ok("收回之后屏上就没有了");
}

// ⑪ 头一天就用的人，想只问熟人
//
// 「只问一起做过事的人」对他是**一条走不通的路**——他还没和谁做成过事。
// 这一幕验的不是那一档能不能选，是**它在他选之前就说清了**：
// 让他选完、等一轮、再看见一屏"没找到"，他会以为是这产品没人用。
console.log("\n⑪ 头一天就用的人，想只问熟人");
{
  const P = "第一天就用的人";
  const newbie = await personFor(browser, id(9), "第一天就用的人", "苏见月");
  await open(newbie, P, "/", "首页");
  const box = newbie.locator("textarea, input[type=text]").first();
  await box.fill("想找人一起去后山拍点素材");
  await newbie.getByRole("button", { name: /整理/ }).first().click();
  await newbie.waitForTimeout(2500);

  const choice = newbie.getByRole("radio", { name: /只问一起做过事的人/ });
  if ((await choice.count()) === 0) {
    stuck(P, "这条给谁看见", "只能问全校，选不了范围");
  } else {
    const card = await textOf(newbie);
    if (!/一个人都问不到|还没和谁一起做成过事/.test(card)) {
      stuck(P, "这条给谁看见", "那一档对他是空的，屏上却不说");
    } else ok("选之前就知道那一档现在问不到人");
    checkWords(card, P, "这条给谁看见");
  }
}

await browser.close();

console.log(`\n${"─".repeat(60)}`);
if (friction.length === 0) {
  console.log("八个 persona 都走完了，一处没卡。");
} else {
  console.log(`卡了 ${friction.length} 处：`);
  for (const f of friction) console.log(`  · [${f.persona}] ${f.step}：${f.why}`);
}
process.exit(friction.length === 0 ? 0 : 1);
