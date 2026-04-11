import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactCompiler: true,
  async rewrites() {
    return [
      {
        source: "/uploads/:path*",
        destination: "http://localhost:6060/uploads/:path*",
      },
    ];
  },
};

export default nextConfig;
