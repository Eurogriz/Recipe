/** @type {import('next').NextConfig} */
const API_BASE = process.env.FW_API_INTERNAL || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  // Allow the E2B preview host to embed the app + Server Actions to accept
  // that origin. Without this Next.js 14 blocks the preview iframe.
  experimental: {
    serverActions: {
      allowedOrigins: ["*.e2b.app", "*.localhost", "localhost:3000"],
    },
  },
  async rewrites() {
    // Every /api/* request from the browser is forwarded server-side to
    // the FastAPI backend on 8000. Keeps the browser away from CORS + the
    // sandbox proxy from having to expose the API port.
    return [
      { source: "/api/:path*", destination: `${API_BASE}/:path*` },
    ];
  },
};

export default nextConfig;
