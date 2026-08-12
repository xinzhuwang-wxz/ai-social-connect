import type { NextConfig } from "next";

/**
 * `/api/*` 的转发**不在这里**，在 `app/api/[...path]/route.ts`。
 *
 * `rewrites()` 在构建时求值，结果被写进路由清单——容器里构建那一刻
 * `API_ORIGIN` 还没设（它是 compose 运行时注入的服务名），于是烘进镜像的是
 * `localhost:8000`，而在 web 容器里 localhost 是它自己。
 *
 * **同一个变量，dev 每次请求重读、production 构建时定死。** 这个差别在
 * dev server 上永远看不见，只有换成 production build 才暴露。
 */
const config: NextConfig = {};

export default config;
