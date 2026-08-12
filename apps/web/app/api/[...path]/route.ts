/**
 * `/api/*` 的转发。
 *
 * ## 为什么不用 `next.config` 的 rewrites
 *
 * 因为 `rewrites()` 在 **构建时**求值：`next build` 会把结果写进路由清单。
 * 容器里构建那一刻 `API_ORIGIN` 还没设（它是 compose 运行时才注入的服务名），
 * 于是烘进镜像的是 `http://localhost:8000`——而在 web 容器里 localhost
 * 是它自己。**每一屏的每一次取数都 ECONNREFUSED，整个前端退到错误态。**
 *
 * 这个洞在 dev server 上看不见：dev 每次请求都重读配置，所以它一直是对的。
 * 换成 production build 才暴露出来——**同一个变量，两种求值时机**。
 *
 * 路由处理器在**每次请求**时读环境变量，部署目标因此是运行时配置，
 * 不是镜像的一部分。同一个镜像可以指向不同的后端。
 *
 * ## 前端仍然只认 `/api`
 *
 * 后端地址是部署细节。浏览器里跑的代码从来不该知道它——这条没变，
 * 变的只是"谁来把 `/api` 接到真地址上"。
 */

import { NextRequest } from "next/server";

const ORIGIN = () => process.env.API_ORIGIN ?? "http://localhost:8000";

/** 逐跳首部不能透传：它们描述的是**这一段连接**，不是这次请求。 */
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);

function forwardable(headers: Headers): Headers {
  const out = new Headers();
  headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) out.set(key, value);
  });
  return out;
}

async function proxy(request: NextRequest): Promise<Response> {
  const url = new URL(request.url);
  const target = `${ORIGIN()}${url.pathname}${url.search}`;

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers: forwardable(request.headers),
      body:
        request.method === "GET" || request.method === "HEAD"
          ? undefined
          : await request.arrayBuffer(),
      redirect: "manual",
      cache: "no-store",
    });
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: forwardable(upstream.headers),
    });
  } catch {
    // 后端没起来时给一个**说得清的** 502，而不是一个 Next 的错误页。
    // 界面那一侧对 5xx 有降级路径，对一个 HTML 错误页没有。
    return Response.json(
      { detail: "现在连不上，稍后再试" },
      { status: 502, headers: { "content-type": "application/json" } },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;

/** 每次请求都真的转发出去，不缓存、不预渲染。 */
export const dynamic = "force-dynamic";
