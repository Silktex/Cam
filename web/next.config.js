/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const backend = process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000';
    return [
      { source: '/api/:path*', destination: `${backend}/api/:path*` },
      { source: '/ws/:path*', destination: `${backend}/ws/:path*` },
      { source: '/media/:path*', destination: `${backend}/media/:path*` },
    ];
  },
};

module.exports = nextConfig;
