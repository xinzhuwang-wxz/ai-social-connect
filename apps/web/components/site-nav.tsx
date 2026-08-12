"use client";

/**
 * 常驻导航。
 *
 * ## 为什么它必须存在
 *
 * 在有这个文件之前，每一屏都做好了，但**没有任何东西把它们连起来**——
 * 一个刚打开这个网页的人只能停在首页。产品的每一片都能单独演示，
 * 合起来却走不动，而这正是"完整"和"看起来完整"的区别。
 *
 * ## 四个入口，不是十个
 *
 * 十个页面里只有四个是**用户自己会主动去的地方**：说一件事、等配队、
 * 有哪些招募、我的记录。其余六个都是从这四个里走进去的（小队、授权、
 * 邀请、项目空间、留下什么），把它们并排放进导航只会让人不知道从哪开始。
 *
 * 导航栏的长度是一种判断：每多一项，前面那些就少被看见一点。
 *
 * ## 手机上是底部标签栏，不是把同一排字挤小
 *
 * 一排横向文字在 390px 宽的屏上会折成竖排——「等配队」三个字一个字一行。
 * 那不是"有点挤"，是**不能用**。
 *
 * 换成底栏还有第二条理由：这个产品的用户是走在路上的学生，单手握着手机，
 * 拇指够得到的是屏幕下缘，不是顶端。
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { comingUp, unansweredSeeds, type ComingUp } from "@/lib/inbox";

/** 用户会主动去的四个地方。措辞用动词，不用名词——
 *  "我的记录"是个抽屉，"说一件事"是个动作。
 *  `short` 是底栏用的：那里一格只有约五个字的宽度。 */
const PLACES = [
  { href: "/", label: "花园", short: "花园" },
  { href: "/seeds", label: "信箱", short: "信箱" },
  { href: "/waiting", label: "行动中", short: "行动中" },
  { href: "/me", label: "森林", short: "森林" },
  { href: "/opportunities", label: "在招什么", short: "在招" },
] as const;

export function SiteNav() {
  const here = usePathname();
  // 首页只在完全相等时高亮：否则它在每一页上都亮着，
  // 等于没有"我现在在哪"这个信息。
  const active = (href: string) =>
    href === "/" ? here === "/" : here.startsWith(href);

  // **还没进门的人不该看到导航。**
  //
  // 欢迎屏上顶着一条空顶栏（这一屏不在导航项里，屏名取不到）、
  // 底下还挂着五个标签——一个刚打开这个产品、连名字都还没填的人，
  // 看到的应该是一件事，不是一整个应用的骨架。
  //
  // 这一条要放在所有 hook 之后：提前 return 会让 hook 的调用次数
  // 在两次渲染之间不一致。
  const bare = here.startsWith("/welcome");

  // 顶栏左侧：首页显示品牌，其余屏显示当前屏的名字。
  // 同一个品牌名出现在每一页，在 390px 的屏上白占 52px，而且对用户
  // 没有信息量——他已经知道这是哪个应用了。
  const isHome = here === "/";
  const currentPlace = PLACES.find((p) =>
    p.href === "/" ? here === "/" : here.startsWith(p.href),
  );

  // 有人在等你答复。**这是"被邀请的那一侧"唯一的入口**——
  // 没有它，被邀请的人不知道有这回事，那一整屏等于不存在。
  const [waiting, setWaiting] = useState(0);
  // 这两天要出发的事。**它比"等你答复"更急**——那件事已经定了，
  // 人得按时出现。
  const [soon, setSoon] = useState<ComingUp[]>([]);

  useEffect(() => {
    const stop = new AbortController();
    void unansweredSeeds(stop.signal).then(setWaiting);
    void comingUp(stop.signal).then(setSoon);
    return () => stop.abort();
    // 换页时重数一次：刚答复完就该看到数字变小，否则用户会以为没生效。
  }, [here]);

  if (bare) return null;

  return (
    <>
      {/* 顶栏。pt-[env(safe-area-inset-top)] 让内容在刘海机型上不被遮住。
          手机上左侧首页品牌、其余屏名；桌面四个入口横排，Wordmark 始终可见。 */}
      <header className="sticky top-0 z-30 border-b border-line bg-paper/85 pt-[env(safe-area-inset-top)] backdrop-blur-md">
        <div className="mx-auto flex h-[52px] max-w-3xl items-center px-4 sm:h-14 sm:px-5">
          {/* 首页显示品牌；其余屏显示当前屏的名字。
              桌面的「横排导航」（nav 里的链接）不受影响——那是独立的节点。
              品牌已经通过整体风格建立，每一屏重复它，等于没有信息量。 */}
          {isHome ? (
            <Wordmark />
          ) : (
            <span className="text-[16px] font-semibold tracking-tight text-ink">
              {currentPlace?.label ?? ""}
            </span>
          )}

          {/* 两条导航同时存在于 DOM 里，由 CSS 决定显示哪一条。
              所以它们的可及名必须不同——两个同名的导航地标，
              读屏软件会念两遍"主导航"，而用户只看得见一条。 */}
          <nav aria-label="主导航" className="ml-6 hidden items-center gap-1 sm:flex">
            {PLACES.map((place) => (
              <Link
                key={place.href}
                href={place.href}
                aria-current={active(place.href) ? "page" : undefined}
                className={
                  "rounded-[10px] px-3 py-1.5 text-[14px] " +
                  (active(place.href)
                    ? "bg-accent-soft font-medium text-accent"
                    : "text-ink-soft hover:bg-line-soft hover:text-ink")
                }
              >
                {place.label}
              </Link>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            {soon.length > 0 && soon[0] && (
              // 快到了的排在待答复前面：那件事已经定了，人得按时出现。
              <Link
                href={soon[0].space_id ? `/spaces/${soon[0].space_id}` : "/me"}
                className="inline-flex items-center gap-2 rounded-full bg-pending-soft px-3 py-1.5 text-[13px] font-medium text-pending hover:bg-pending hover:text-paper"
              >
                <span
                  aria-hidden
                  className="inline-block size-1.5 rounded-full bg-current"
                />
                {soonWord(soon[0].starts_at)}要出发
              </Link>
            )}
            {waiting > 0 && (
              // 只在真有人等的时候出现。常驻一个「0」比不显示更差——
              // 它每天提醒你这里什么都没有。
              <Link
                href="/seeds"
                aria-current={here.startsWith("/seeds") ? "page" : undefined}
                className={
                  "inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[13px] font-medium " +
                  (here.startsWith("/seeds")
                    ? "bg-accent text-paper"
                    : "bg-accent-soft text-accent hover:bg-accent hover:text-paper")
                }
              >
                <span
                  aria-hidden
                  className="inline-block size-1.5 rounded-full bg-current"
                />
                {waiting} 颗种子等你看
              </Link>
            )}
          </div>
        </div>
      </header>

      {/* 底部标签栏。**这是主形态**——产品最终跑在手机上，而拇指够得到的
          是屏幕下缘不是顶端。桌面上它让位给顶栏，避免同一组入口出现两次。 */}
      <nav
        aria-label="主导航（底部）"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-paper/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md sm:hidden"
      >
        <div className="grid grid-cols-5">
          {PLACES.map((place) => (
            <Link
              key={place.href}
              href={place.href}
              aria-current={active(place.href) ? "page" : undefined}
              className={
                // 高度 ≥56px：规范要求按钮 44–52，而底栏一格还要塞下
                // 图标和字，所以给得更足一点。点空三次的人就走了。
                "flex min-h-[56px] flex-col items-center justify-center gap-1 " +
                "py-2 text-[11px] " +
                (active(place.href) ? "font-medium text-accent" : "text-ink-soft")
              }
            >
              <Glyph href={place.href} on={active(place.href)} />
              {place.short}
            </Link>
          ))}
        </div>
      </nav>
      {/* 底栏的让位**由每一屏自己的 `pb-24` 做**，不在这里放占位块——
          这个组件渲染在 children 之前，占位块只会在顶部白留一段，
          底部照样被压住。 */}
    </>
  );
}

/** 「明天早上」「今天下午」——**不写几点几分**：那是进去之后的事，
 *  在导航上只需要让他知道"快到了"。 */
function soonWord(iso: string): string {
  const t = new Date(iso);
  const days = Math.round(
    (new Date(t.getFullYear(), t.getMonth(), t.getDate()).getTime() -
      new Date().setHours(0, 0, 0, 0)) /
      86400000,
  );
  const half = t.getHours() < 12 ? "早上" : t.getHours() < 18 ? "下午" : "晚上";
  return days <= 0 ? `今天${half}` : days === 1 ? `明天${half}` : `${t.getMonth() + 1} 月 ${t.getDate()} 日`;
}

function Wordmark() {
  return (
    <Link href="/" className="flex shrink-0 items-center gap-2">
      <span
        aria-hidden
        className="grid size-8 place-items-center rounded-[10px] bg-brand text-[14px] font-semibold text-card"
      >
        共
      </span>
      <span className="text-[16px] font-semibold tracking-tight text-brand">共域</span>
    </Link>
  );
}

/**
 * 底栏的小图标。
 *
 * 手画的几何形，不引图标库：四个入口引进一整套图标字体，是为四个字形
 * 付一整包的体积。形状只要能被认出来是**四个不同的东西**就够了，
 * 字就写在它下面。
 */
function Glyph({ href, on }: { href: string; on: boolean }) {
  const common = {
    width: 20,
    height: 20,
    viewBox: "0 0 20 20",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: on ? 1.9 : 1.6,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  if (href === "/") {
    // 花园：一间小房子。首页是"我的花园"，不是一张列表。
    return (
      <svg {...common}>
        <path d="M3.2 9.6 10 4.2l6.8 5.4" />
        <path d="M4.8 9v7h10.4V9" />
        <path d="M8.4 16v-3.6h3.2V16" />
      </svg>
    );
  }
  if (href === "/waiting") {
    return (
      <svg {...common}>
        <circle cx="10" cy="10" r="6.5" />
        <path d="M10 6.6V10l2.4 1.6" />
      </svg>
    );
  }
  if (href === "/opportunities") {
    return (
      <svg {...common}>
        <path d="M3.5 7.5h13v8h-13z" />
        <path d="M7.5 7.5V6a2 2 0 0 1 2-2h1a2 2 0 0 1 2 2v1.5" />
      </svg>
    );
  }
  if (href === "/seeds") {
    // 信箱：一个有旗子的邮筒，不是一个信封——信封会和"消息"混起来，
    // 而这里收到的是种子。
    return (
      <svg {...common}>
        <path d="M3.5 8.5h9v7h-9z" />
        <path d="M12.5 8.5c0-1.9 1.3-3 3-3s3 1.1 3 3v7" />
        <path d="M6 5.5v3" />
      </svg>
    );
  }
  // 森林：三棵高矮不一的树。**高度不能一致**——一片一样高的树看着像栅栏。
  return (
    <svg {...common}>
      <path d="M5 16.5V13M5 13l-2.2 0 2.2-3.4L7.2 13 5 13Z" />
      <path d="M10 16.5V10.5M10 10.5 7.2 10.5 10 5.6l2.8 4.9-2.8 0Z" />
      <path d="M15 16.5V12.4M15 12.4l-2 0 2-3 2 3-2 0Z" />
    </svg>
  );
}
