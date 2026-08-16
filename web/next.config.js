/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: process.env.INTERNAL_API_URL || 'http://127.0.0.1:8000/api/:path*',
      },
      {
        source: '/stream/:path*',
        destination: process.env.INTERNAL_API_URL || 'http://127.0.0.1:8000/stream/:path*',
      },
      {
        source: '/hls/:path*',
        destination: process.env.INTERNAL_API_URL || 'http://127.0.0.1:8000/hls/:path*',
      },
    ];
  },
};

module.exports = nextConfig;
