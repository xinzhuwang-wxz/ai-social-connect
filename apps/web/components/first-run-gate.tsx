"use client";

/**
 * 第一次打开这个产品的人，先问他叫什么。
 *
 * ## 为什么需要一道门，而不只是一屏
 *
 * 欢迎屏本身建出来是不够的——**没有任何东西把人带过去的话，它等于不存在**。
 * 这个仓库已经在同一件事上栽过好几次：真人对话区建好了没挂载、
 * 「照这个再来一次」只挂在一条走不到的分支上、森林里的一株点不进去。
 *
 * ## 为什么是客户端判断
 *
 * 身份存在 localStorage 里（演示期没有登录页），服务端中间件看不见它，
 * 所以这道门只能在浏览器里做。等换成校园身份接入时，换掉的是"身份从哪来"，
 * 这道门本身照旧。
 *
 * ## 为什么不拦住整个界面
 *
 * 只在**还没起过名**的时候拦一次，而且只拦一次。一个每次打开都要过一道
 * 欢迎屏的产品会让人学会闭着眼睛点下一步——那时候这一步就白问了。
 *
 * 判断结果拿不到（接口挂了）时**放行**：一个连不上后端的人被卡在欢迎屏上，
 * 会以为产品坏了，而他本来至少能看看别的屏。
 */

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { api } from "@/lib/api";

/** 不需要名字也能待着的地方。欢迎屏自己当然在里面，否则会转圈。 */
const OPEN = ["/welcome"];

export function FirstRunGate() {
  const router = useRouter();
  const here = usePathname();

  useEffect(() => {
    if (OPEN.some((path) => here.startsWith(path))) return;
    let cancelled = false;
    api
      .profile()
      .then((me) => {
        if (!cancelled && !me.named_self) router.replace("/welcome");
      })
      .catch(() => {
        // 放行。见文件头：连不上后端的人不该被卡在门口。
      });
    return () => {
      cancelled = true;
    };
  }, [here, router]);

  return null;
}
