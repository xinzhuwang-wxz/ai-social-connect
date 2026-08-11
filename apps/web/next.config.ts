import type { NextConfig } from "next";

const config: NextConfig = {
  async rewrites() {
    // 前端只认 /api，后端地址是部署细节。
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.API_ORIGIN ?? "http://localhost:8000"}/api/:path*`,
      },
    ];
  },
};

export default config;
