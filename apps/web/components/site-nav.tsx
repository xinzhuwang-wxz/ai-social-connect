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
 */

import Link from "next/link";
import { usePathname } from "next/navigation";

/** 用户会主动去的四个地方。措辞用动词，不用名词——
 *  "我的记录"是个抽屉，"说一件事"是个动作。 */
const PLACES = [
  { href: "/", label: "说一件事" },
  { href: "/waiting", label: "等配队" },
  { href: "/opportunities", label: "有哪些招募" },
  { href: "/me", label: "我的记录" },
] as const;

export function SiteNav() {
  const here = usePathname();

  return (
    <nav aria-label="主导航" className="border-b border-line bg-paper">
      <div className="mx-auto flex max-w-3xl items-center gap-1 px-4 py-3">
        <Link href="/" className="mr-4 text-sm font-medium tracking-tight">
          共域
        </Link>
        {PLACES.map((place) => {
          // 首页只在完全相等时高亮：否则它在每一页上都亮着，
          // 等于没有"我现在在哪"这个信息。
          const active =
            place.href === "/" ? here === "/" : here.startsWith(place.href);
          return (
            <Link
              key={place.href}
              href={place.href}
              aria-current={active ? "page" : undefined}
              className={
                "rounded-md px-3 py-1.5 text-sm transition-colors " +
                (active
                  ? "bg-accent-soft text-accent"
                  : "text-ink-soft hover:text-ink")
              }
            >
              {place.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
